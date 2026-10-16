import json

from xrayui.core import profiles as profiles_mod
from xrayui.core.profiles import Profile, ProfileStore


def _store(tmp_path, monkeypatch) -> ProfileStore:
    monkeypatch.setattr(profiles_mod.paths, "base_dir", lambda: tmp_path)
    return ProfileStore()


def test_list_skips_the_subscriptions_file(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    kept = store.save(Profile(name="a", address="x", port=1, id="y"))
    (store.dir / profiles_mod.SUBSCRIPTIONS_FILENAME).write_text(
        '[{"url": "https://sub.example/x"}]', encoding="utf-8"
    )

    got = store.list()

    assert [p.uid for p in got] == [kept.uid]


def test_list_skips_a_json_file_that_is_not_an_object(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    kept = store.save(Profile(name="a", address="x", port=1, id="y"))
    (store.dir / "not-a-profile.json").write_text("[1, 2, 3]", encoding="utf-8")

    got = store.list()

    assert [p.uid for p in got] == [kept.uid]


def test_valid_pqv_accepts_only_an_unpadded_base64url_ml_dsa_65_key():
    import base64
    key = base64.urlsafe_b64encode(bytes(range(256)) * 7 + bytes(160)).rstrip(b"=").decode()
    assert len(key) == 2603
    assert profiles_mod.valid_pqv(key)
    assert profiles_mod.valid_pqv(f"  {key}\n")
    assert not profiles_mod.valid_pqv("")
    assert not profiles_mod.valid_pqv(key[:-1])  # one byte short
    assert not profiles_mod.valid_pqv(key + "=")  # padded
    assert not profiles_mod.valid_pqv(key[:-1] + "+")  # standard, not url alphabet

def test_uid_matches_filename(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    store.dir.mkdir(parents=True, exist_ok=True)
    (store.dir / "fileuid.json").write_text(json.dumps({"uid": "wronguid", "name": "Test"}), encoding="utf-8")

    profiles = store.list()
    assert len(profiles) == 1
    assert profiles[0].uid == "fileuid"

    p = store.get("fileuid")
    assert p.uid == "fileuid"


def test_save_never_writes_outside_the_profiles_dir(tmp_path, monkeypatch):
    # A profile imported from JSON (importer.parse_json -> Profile.from_dict)
    # carries whatever "uid" the JSON had. Saved as the filename, a uid like
    # "../evil" or an absolute path escapes profiles/ and writes anywhere the
    # (often elevated) process can -- so save must never trust it.
    store = _store(tmp_path, monkeypatch)
    p = Profile(name="evil", address="x", port=1, id="y")
    p.uid = "../evil"

    saved = store.save(p)

    assert not (tmp_path / "evil.json").exists()
    assert saved.uid != "../evil"
    assert [f.name for f in store.dir.glob("*.json")] == [f"{saved.uid}.json"]


def test_save_never_writes_an_absolute_path(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    p = Profile(name="evil", address="x", port=1, id="y")
    p.uid = str(tmp_path / "outside")

    saved = store.save(p)

    assert not (tmp_path / "outside.json").exists()
    assert (store.dir / f"{saved.uid}.json").exists()


def test_get_and_delete_ignore_a_uid_that_escapes_the_profiles_dir(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    store.dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    assert store.get("../outside") is None
    store.delete("../outside")
    assert outside.exists()


def test_imported_profile_cannot_overwrite_an_existing_uid(tmp_path, monkeypatch):
    # A uid is this app's own filename, not server data. A config (or a
    # subscription entry) that carries someone else's -- even a valid-looking
    # -- uid must not overwrite that stored profile when it is imported.
    from xrayui.core import importer

    store = _store(tmp_path, monkeypatch)
    victim = store.save(Profile(name="Victim", address="real.example", port=443, id="v"))
    hostile = json.dumps({"protocol": "vless", "address": "evil.example",
                          "port": 443, "id": "e", "uid": victim.uid})

    store.save(importer.parse_json(hostile))

    again = store.get(victim.uid)
    assert again is not None and again.address == "real.example"
    assert again.name == "Victim"


def test_profile_dict_serialization_equivalence():
    from dataclasses import asdict

    # Verify to_dict matches asdict across various profiles
    p_default = Profile()
    assert p_default.to_dict() == asdict(p_default)

    p_custom = Profile(
        name="Custom", protocol="hysteria2", address="1.2.3.4", port=8443,
        id="pass", allow_insecure=True, hy2_up_mbps=100, hy2_down_mbps=200,
        hy2_ports="20000-30000", uid="test-uid-123",
    )
    assert p_custom.to_dict() == asdict(p_custom)

    # Verify from_dict type safety and filtering
    raw = {
        "name": "Imported",
        "port": "not-an-int",  # invalid type for port: should keep default 443
        "allow_insecure": "not-a-bool",  # invalid type: should keep default False
        "unknown_field": "dropped",
        "address": "example.com",
    }
    p_loaded = Profile.from_dict(raw)
    assert p_loaded.name == "Imported"
    assert p_loaded.address == "example.com"
    assert p_loaded.port == 443
    assert p_loaded.allow_insecure is False
    assert not hasattr(p_loaded, "unknown_field")


def test_normalize_pcs_drops_all_unicode_whitespace():
    assert profiles_mod.normalize_pcs("ab:cd\x0bef\xa0gh ") == "abcdefgh"


