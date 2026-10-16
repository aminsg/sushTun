import json

from xrayui.core import settings as app_settings


def _load_from(tmp_path, monkeypatch, data: dict) -> dict:
    monkeypatch.setattr(app_settings.paths, "base_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps(data), encoding="utf-8")
    return app_settings.load()


def test_legacy_file_without_schema_version_gets_stamped(tmp_path, monkeypatch):
    got = _load_from(tmp_path, monkeypatch, {"ping_target": "9.9.9.9"})
    assert got["schema_version"] == app_settings.SCHEMA_VERSION
    assert got["ping_target"] == "9.9.9.9"


def test_file_already_at_current_version_is_unchanged(tmp_path, monkeypatch):
    got = _load_from(
        tmp_path, monkeypatch,
        {"schema_version": app_settings.SCHEMA_VERSION, "ping_target": "1.2.3.4"},
    )
    assert got["schema_version"] == app_settings.SCHEMA_VERSION
    assert got["ping_target"] == "1.2.3.4"


def test_stale_unknown_keys_are_still_dropped(tmp_path, monkeypatch):
    got = _load_from(tmp_path, monkeypatch, {"no_longer_a_setting": True})
    assert "no_longer_a_setting" not in got


def test_missing_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings.paths, "base_dir", lambda: tmp_path)
    got = app_settings.load()
    assert got == app_settings.DEFAULTS
    assert got is not app_settings.DEFAULTS


def test_non_dict_json_falls_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings.paths, "base_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text("[]", encoding="utf-8")
    got = app_settings.load()
    assert got == app_settings.DEFAULTS


def test_an_old_file_predating_the_speedtest_key_still_loads_and_gains_it(tmp_path, monkeypatch):
    # A settings.json saved before "speedtest" existed has no such key at
    # all -- unlike schema_version's reshape, a brand new DEFAULTS key needs
    # no migration: _merge already fills anything the saved file lacks.
    got = _load_from(tmp_path, monkeypatch, {"ping_target": "9.9.9.9"})
    assert got["speedtest"] == app_settings.DEFAULTS["speedtest"]


def test_a_non_dict_value_for_a_dict_setting_keeps_the_default(tmp_path, monkeypatch):
    # routing/dns/... are always read as dicts (routing.build_rules(cfg[
    # "routing"]), dns.build_dns_and_rules(cfg["dns"])). A hand-edited or
    # corrupt file holding a list/string there used to replace the default,
    # and every connect then died on "'list' object has no attribute 'get'".
    got = _load_from(tmp_path, monkeypatch, {"routing": [], "dns": "x"})
    assert got["routing"] == app_settings.DEFAULTS["routing"]
    assert got["dns"] == app_settings.DEFAULTS["dns"]


def test_a_partly_valid_dict_setting_still_merges_its_good_keys(tmp_path, monkeypatch):
    got = _load_from(tmp_path, monkeypatch, {"routing": {"direct_iran": False}})
    assert got["routing"]["direct_iran"] is False
    assert got["routing"]["block_ads"] == app_settings.DEFAULTS["routing"]["block_ads"]
