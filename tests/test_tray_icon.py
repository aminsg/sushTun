"""Menu-bar (tray) status icon: mascot glyph when idle, flag when connected."""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.core import geo_exit  # noqa: E402
from xrayui.core.profiles import Profile  # noqa: E402
from xrayui.i18n import set_language  # noqa: E402
from xrayui.ui import tray_icon as tray_mod  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
    tray_mod.clear_cache()
    yield
    set_language("en")
    tray_mod.clear_cache()


def _argb(img):
    return img.convertToFormat(QImage.Format.Format_ARGB32)


def _opaque_pixels(pix) -> int:
    img = _argb(pix.toImage())
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 10:
                n += 1
    return n


def _sig(pix) -> bytes:
    img = _argb(pix.toImage())
    out = bytearray()
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            out += bytes((c.red(), c.green(), c.blue(), c.alpha()))
    return bytes(out)


def test_pixmap_is_retina_sized_and_non_empty(qapp):
    pix = tray_mod.tray_pixmap("disconnected")
    assert not pix.isNull()
    assert pix.devicePixelRatio() == 2.0
    assert pix.width() == round(22 * pix.devicePixelRatio())
    assert _opaque_pixels(pix) > 100


def test_same_country_is_cached_and_countries_differ(qapp):
    assert tray_mod.tray_pixmap("connected", "de") is tray_mod.tray_pixmap("connected", "de")
    assert tray_mod.tray_pixmap("connected", "de") is not tray_mod.tray_pixmap("connected", "fr")
    assert _sig(tray_mod.tray_pixmap("connected", "de")) != _sig(
        tray_mod.tray_pixmap("connected", "fr"))
    # White flag (Japan) still draws an edge: visible, not dissolved.
    assert _opaque_pixels(tray_mod.tray_pixmap("connected", "jp")) > 100


def test_unknown_country_is_badged_glyph_not_blank_or_wrong_flag(qapp):
    unknown = tray_mod.tray_pixmap("connected", None)
    bad_code = tray_mod.tray_pixmap("connected", "xx")
    plain = tray_mod.tray_pixmap("disconnected")
    assert _opaque_pixels(unknown) > 100
    assert _sig(unknown) == _sig(bad_code)
    assert _sig(unknown) != _sig(plain)  # the connected badge marks it
    assert _sig(unknown) != _sig(tray_mod.tray_pixmap("connected", "de"))


def test_connecting_is_distinct_from_both_ends(qapp):
    states = {s: _sig(tray_mod.tray_pixmap(s)) for s in (
        "disconnected", "connecting", "connected")}
    assert len(set(states.values())) == 3


def test_mask_flag_per_state(qapp):
    # Only the idle glyph is a macOS template image; badges and flags carry
    # colour, which a mask would destroy.
    assert tray_mod.tray_icon("disconnected").isMask() is True
    assert tray_mod.tray_icon("connecting").isMask() is False
    assert tray_mod.tray_icon("connected", None).isMask() is False
    assert tray_mod.tray_icon("connected", "de").isMask() is False
    assert tray_mod.tray_icon("bogus-state").isMask() is True
    assert tray_mod.tray_icon("connected", "de") is tray_mod.tray_icon("connected", "de")


def test_idle_glyph_is_template_safe(qapp):
    # A template keeps only alpha: every drawn pixel must be black, on a
    # fully transparent background with no tile or frame at the corners.
    pix = tray_mod.tray_pixmap("disconnected")
    img = _argb(pix.toImage())
    seen = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 10:
                assert (c.red(), c.green(), c.blue()) == (0, 0, 0)
                seen += 1
    assert seen > 100
    for x, y in ((0, 0), (43, 0), (0, 43), (43, 43), (21, 0)):
        assert img.pixelColor(x, y).alpha() < 10


def test_appearance_dark_only_where_it_is_baked_in(qapp):
    # The template glyph and full-colour flags ignore `dark` (macOS tints the
    # mask itself); the badged states pre-tint the glyph, so they must differ.
    assert _sig(tray_mod.tray_pixmap("disconnected", None, True)) == _sig(
        tray_mod.tray_pixmap("disconnected", None, False))
    assert tray_mod.tray_pixmap("disconnected", None, True) is \
        tray_mod.tray_pixmap("disconnected", None, False)
    assert _sig(tray_mod.tray_pixmap("connected", "de", True)) == _sig(
        tray_mod.tray_pixmap("connected", "de", False))
    assert _sig(tray_mod.tray_pixmap("connecting", None, True)) != _sig(
        tray_mod.tray_pixmap("connecting", None, False))
    assert _sig(tray_mod.tray_pixmap("connected", None, True)) != _sig(
        tray_mod.tray_pixmap("connected", None, False))


def test_tooltips_carry_state_server_and_country(qapp):
    assert tray_mod.tray_tooltip("disconnected") == "sushTun — Disconnected"
    assert tray_mod.tray_tooltip("connecting") == "sushTun — Connecting…"
    tip = tray_mod.tray_tooltip("connected", "Berlin", "de")
    assert "Berlin" in tip and "Germany" in tip
    assert "Berlin" in tray_mod.tray_tooltip("connected", "Berlin", None)
    assert "Germany" in tray_mod.tray_tooltip("connected", "", "de")


def test_tooltips_are_translated(qapp):
    set_language("fa")
    assert tray_mod.tray_tooltip("disconnected") != "sushTun — Disconnected"
    tip = tray_mod.tray_tooltip("connected", "Berlin", "de")
    assert "آلمان" in tip and "Berlin" in tip


# -- wiring: the existing state callbacks move the tray, even when hidden ----
@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    from xrayui.ui.main_window import MainWindow
    win = MainWindow(elevated=False)
    yield win
    win.close()


class _FakeTray:
    def __init__(self):
        self.icons = []
        self.tips = []

    def setIcon(self, icon):
        self.icons.append(icon)

    def setToolTip(self, tip):
        self.tips.append(tip)

    def showMessage(self, *a, **k):
        pass


def test_tray_follows_connect_and_exit_detection(window, monkeypatch):
    p = window.store.save(Profile(name="Berlin", address="a.example.com", port=443, id="u"))
    window.store.set_active(p.uid)
    window._reload_profiles()
    fake = _FakeTray()
    window.tray = fake

    window._refresh_tray()
    assert "Disconnected" in fake.tips[-1]

    window._set_busy(True)
    assert "Connecting" in fake.tips[-1]

    window._set_busy(False)
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    monkeypatch.setattr(type(window.conn.state), "profile_uid",
                        property(lambda _s: p.uid))
    window._refresh_tray()
    assert "Berlin" in fake.tips[-1] and "Germany" not in fake.tips[-1]

    window._on_exit_detected(p.uid, geo_exit.ExitInfo("de", "9.9.9.9"))
    assert "Berlin" in fake.tips[-1] and "Germany" in fake.tips[-1]


def test_tray_keeps_updating_while_the_window_is_hidden(window, monkeypatch):
    p = window.store.save(Profile(name="Berlin", address="a.example.com", port=443, id="u"))
    window.store.set_active(p.uid)
    window._reload_profiles()
    fake = _FakeTray()
    window.tray = fake
    window.hide()

    # The 2s status timer skips on-screen work while hidden; the tray is not
    # on-screen work and must still move (regression: it returned early).
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    monkeypatch.setattr(type(window.conn.state), "profile_uid",
                        property(lambda _s: p.uid))
    window.results.set(p.uid, country="fr", exit_ip="1.2.3.4")
    window.profiles.update_detail(p.uid, {"country": "fr", "exit_ip": "1.2.3.4"})
    window._refresh_status()
    assert "Berlin" in fake.tips[-1] and "France" in fake.tips[-1]

    monkeypatch.setattr(window.conn, "is_connected", lambda: False)
    window._refresh_status()
    assert "Disconnected" in fake.tips[-1]


def test_tray_disconnect_returns_to_plain_glyph(window, monkeypatch):
    p = window.store.save(Profile(name="Berlin", address="a.example.com", port=443, id="u"))
    window.store.set_active(p.uid)
    window._reload_profiles()
    fake = _FakeTray()
    window.tray = fake
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    monkeypatch.setattr(type(window.conn.state), "profile_uid",
                        property(lambda _s: p.uid))
    window.results.set(p.uid, country="de", exit_ip="1.2.3.4")
    window.profiles.update_detail(p.uid, {"country": "de", "exit_ip": "1.2.3.4"})
    window._refresh_tray()
    connected_sig = _sig(fake.icons[-1].pixmap(44, 44))

    monkeypatch.setattr(window.conn, "is_connected", lambda: False)
    window._refresh_tray()
    assert _sig(fake.icons[-1].pixmap(44, 44)) != connected_sig
    assert _sig(fake.icons[-1].pixmap(44, 44)) == _sig(
        tray_mod.tray_icon("disconnected").pixmap(44, 44))
