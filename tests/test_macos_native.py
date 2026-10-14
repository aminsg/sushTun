"""macOS-native behaviour: menu bar roles/shortcuts, Dock re-show, login
launch hidden, notification discipline, Cmd wording, and the .dmg offer.

Every behavioural change under test is guarded by sys.platform == "darwin"
(or IS_MAC captured from it), so each mac test builds the real widgets with
the platform faked and the matching non-mac test pins the old behaviour.
"""
from __future__ import annotations

import copy
import os
import sys

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QAction, QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.core import settings as app_settings  # noqa: E402
from xrayui.core import updates as updates_mod  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    return monkeypatch


@pytest.fixture
def mac_window(qapp, tmp_path, darwin):
    monkeypatch = darwin
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    from xrayui.ui.main_window import MainWindow
    win = MainWindow(elevated=False)
    yield win
    win.close()


@pytest.fixture
def lin_window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    from xrayui.ui.main_window import MainWindow
    win = MainWindow(elevated=False)
    yield win
    win.close()


def _menu_titles(win):
    from PySide6.QtWidgets import QMenu
    return [m.title() for m in win.menuBar().findChildren(QMenu)
            if m.parent() is win.menuBar()]


# -- menu bar --------------------------------------------------------------

def test_mac_menu_has_app_edit_window_help_menus(mac_window):
    assert _menu_titles(mac_window) == ["Connection", "Edit", "Window", "Help"]


def test_mac_menu_roles_and_shortcuts(mac_window):
    win = mac_window
    assert win.act_about.menuRole() == QAction.AboutRole
    assert win.act_settings.menuRole() == QAction.PreferencesRole
    assert win.act_quit.menuRole() == QAction.QuitRole
    assert win.act_hide.menuRole() == QAction.ApplicationSpecificRole
    # Explicit "Ctrl+," is Cmd+, on macOS (Qt maps Ctrl to Command there);
    # QKeySequence.Preferences would be Cmd+Shift+, on Apple platforms.
    assert win.act_settings.shortcut() == QKeySequence("Ctrl+,")
    assert win.act_hide.shortcut() == QKeySequence("Ctrl+H")
    assert win.act_minimize.shortcut() == QKeySequence("Ctrl+M")
    assert win.act_quit.shortcut() == QKeySequence(QKeySequence.Quit)
    assert win.act_close_window.shortcut() == QKeySequence(QKeySequence.Close)


def test_mac_edit_menu_uses_standard_keys(mac_window):
    from PySide6.QtWidgets import QMenu
    edit = next(m for m in mac_window.menuBar().findChildren(QMenu)
                if m.title() == "Edit")
    got = {a.text(): a.shortcut() for a in edit.actions()}
    assert got["Cut"] == QKeySequence(QKeySequence.Cut)
    assert got["Copy"] == QKeySequence(QKeySequence.Copy)
    assert got["Paste"] == QKeySequence(QKeySequence.Paste)
    assert got["Select All"] == QKeySequence(QKeySequence.SelectAll)


def test_mac_about_shows_the_version(mac_window, monkeypatch):
    seen = []
    monkeypatch.setattr(QMessageBox, "about",
                        staticmethod(lambda *a: seen.append(a)))
    mac_window.act_about.trigger()
    assert seen and "sushTun" in seen[0][1]


def test_no_mac_menu_off_darwin(lin_window):
    assert not hasattr(lin_window, "act_about")
    assert "Help" not in _menu_titles(lin_window)


# -- Edit menu on the focused field -----------------------------------------

def test_edit_menu_select_copies_and_pastes(mac_window, monkeypatch):
    # Offscreen never activates a window, so focus is faked: the point is
    # what the Edit action does to the focused field, not focus itself.
    win, field = mac_window, QLineEdit("hello")
    monkeypatch.setattr(QApplication, "focusWidget",
                        staticmethod(lambda: field))
    win._edit_focused("select")
    assert field.selectedText() == "hello"
    win._edit_focused("copy")
    field.clear()
    win._edit_focused("paste")
    assert field.text() == "hello"
    win._edit_focused("select")
    win._edit_focused("cut")
    assert field.text() == ""


# -- Dock re-show ------------------------------------------------------------

def test_dock_click_reshows_a_hidden_window(mac_window):
    win = mac_window
    win.hide()
    win._on_app_state_changed(Qt.ApplicationActive)
    assert win.isVisible()


def test_activation_leaves_a_visible_window_alone(mac_window):
    win = mac_window
    win.show()
    win.step_label.setText("untouched")
    win._on_app_state_changed(Qt.ApplicationActive)
    assert win.isVisible()
    assert win.step_label.text() == "untouched"


def test_activation_does_not_resurrect_a_quitting_window(mac_window):
    win = mac_window
    win.hide()
    win.prepare_quit()
    win._on_app_state_changed(Qt.ApplicationActive)
    assert win.isHidden()


# -- login launch starts hidden ----------------------------------------------

def test_autostart_launch_starts_hidden_on_macos(darwin):
    from xrayui.ui.app import starts_hidden
    settings = copy.deepcopy(app_settings.DEFAULTS)
    settings["startup"]["start_minimized"] = False
    assert starts_hidden(True, settings) is True
    assert starts_hidden(False, settings) is False
    assert starts_hidden(True, settings, tray=False) is False


def test_window_minimize_and_zoom_actions(mac_window):
    mac_window.act_minimize.trigger()
    assert mac_window.isMinimized()
    mac_window.showNormal()
    mac_window.act_zoom.trigger()
    assert mac_window.isMaximized()
    mac_window.act_zoom.trigger()
    assert not mac_window.isMaximized()


# -- notifications ------------------------------------------------------------

class _FakeTray:
    def __init__(self):
        self.messages = []

    def showMessage(self, *args):
        self.messages.append(args[1])


def test_notify_skipped_while_focused_on_macos(mac_window, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    win = mac_window
    win.tray = _FakeTray()
    try:
        monkeypatch.setattr(win, "isActiveWindow", lambda: True)
        win._notify("sushTun", "hello", QSystemTrayIcon.Information)
        assert win.tray.messages == []
        monkeypatch.setattr(win, "isActiveWindow", lambda: False)
        win._notify("sushTun", "hello", QSystemTrayIcon.Information)
        assert len(win.tray.messages) == 1
    finally:
        win.tray = None


def test_notify_fires_while_focused_off_macos(lin_window, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    win = lin_window
    win.tray = _FakeTray()
    try:
        monkeypatch.setattr(win, "isActiveWindow", lambda: True)
        win._notify("sushTun", "hello", QSystemTrayIcon.Information)
        assert len(win.tray.messages) == 1
    finally:
        win.tray = None


def test_tray_quit_names_the_app_on_macos(mac_window, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    # No tray icon exists offscreen; rebuild the menu with one available.
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable",
                        staticmethod(lambda: True))
    monkeypatch.setattr(QSystemTrayIcon, "show", lambda self: None)
    mac_window._build_tray()
    try:
        texts = [a.text() for a in mac_window.tray.contextMenu().actions()]
        assert "Quit sushTun" in texts
    finally:
        mac_window.tray = None


def test_tray_quit_stays_plain_off_macos(lin_window, monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable",
                        staticmethod(lambda: True))
    monkeypatch.setattr(QSystemTrayIcon, "show", lambda self: None)
    lin_window._build_tray()
    try:
        texts = [a.text() for a in lin_window.tray.contextMenu().actions()]
        assert "Quit" in texts
        assert "Quit sushTun" not in texts
    finally:
        lin_window.tray = None


def test_close_hint_uses_cmd_on_macos(mac_window):
    win = mac_window
    win.tray = _FakeTray()
    try:
        win.show()
        win.close()
        assert "Cmd+Q" in win.tray.messages[0]
        assert "menu bar" in win.tray.messages[0]
    finally:
        win.tray = None


# -- wording -------------------------------------------------------------------

def test_tour_uses_cmd_paste_on_macos(mac_window):
    texts = [s.text for s in mac_window._tour_steps()]
    assert any("Cmd+V" in t for t in texts)
    assert not any("Ctrl+V" in t for t in texts)


def test_tour_keeps_ctrl_paste_off_macos(lin_window):
    texts = [s.text for s in lin_window._tour_steps()]
    assert any("Ctrl+V" in t for t in texts)


def test_startup_page_uses_menu_bar_words_on_macos(qapp, darwin):
    from PySide6.QtWidgets import QLabel

    from xrayui.ui.settings_window import _StartupPage
    page = _StartupPage(copy.deepcopy(app_settings.DEFAULTS["startup"]))
    try:
        labels = [w.text() for w in page.findChildren(QLabel)]
        assert any("menu bar" in t for t in labels)
        assert not any("tray" in t for t in labels)
    finally:
        page.close()


# -- update flow names the .dmg ----------------------------------------------

def test_mac_download_name_picks_the_dmg():
    release = updates_mod.Release(
        tag="v9.9.9", url="https://example.com",
        assets={"sushTun-macos.dmg": "https://example.com/x.dmg",
                "sushTun-macos": "https://example.com/x"})
    assert updates_mod.mac_download_name(release) == "sushTun-macos.dmg"
    bare = updates_mod.Release(tag="v9.9.9", url="https://example.com",
                               assets={"sushTun-macos": "https://example.com/x"})
    assert updates_mod.mac_download_name(bare) is None


def test_update_dialog_points_installed_mac_at_the_dmg(qapp, darwin, monkeypatch):
    from xrayui.ui.update_dialog import UpdateDialog
    monkeypatch.setattr(updates_mod, "asset_for_this_build", lambda _r: None)
    release = updates_mod.Release(
        tag="v9.9.9", url="https://example.com",
        assets={"sushTun-macos.dmg": "https://example.com/x.dmg"})
    dlg = UpdateDialog(release)
    try:
        assert "sushTun-macos.dmg" in dlg.subtitle.text()
    finally:
        dlg.close()
