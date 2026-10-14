"""Minimize, hide-to-tray and restore: the window must always come back.

The title bar's minimize button and closing the window (which hides it to
the tray while the tunnel keeps running) broke: on macOS a hidden window
could only come back through the tray menu or a second launch -- clicking
the Dock icon did nothing -- and without a tray icon closing quit the app
(and tore the tunnel down) instead of hiding.
"""
from __future__ import annotations

import os
import sys

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui import paths  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    """A real MainWindow on the real platform (native title bar on macOS)."""
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    from xrayui.ui.main_window import MainWindow
    win = MainWindow(elevated=False)
    yield win
    win.tray = None
    win.prepare_quit()
    win.close()


@pytest.fixture
def frameless_window(qapp, tmp_path, monkeypatch):
    """A real MainWindow with the custom traffic lights (Windows/Linux)."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    from xrayui.ui.main_window import MainWindow
    win = MainWindow(elevated=False)
    yield win
    win.tray = None
    win.prepare_quit()
    win.close()


class _FakeTray:
    def __init__(self):
        self.messages = []

    def showMessage(self, *args):
        self.messages.append(args[1])


def test_frameless_window_keeps_the_hints_minimize_needs(frameless_window):
    # showMinimized() is a no-op for a window whose manager hints forbid
    # it; the custom chrome draws its own buttons, so the hints must stay.
    flags = frameless_window.windowFlags()
    assert flags & Qt.WindowMinimizeButtonHint
    assert flags & Qt.WindowMaximizeButtonHint
    assert flags & Qt.WindowCloseButtonHint


def test_native_window_keeps_the_minimize_hint(window):
    assert window.windowFlags() & Qt.WindowMinimizeButtonHint


def test_minimize_light_minimizes_the_window(frameless_window, qapp):
    frameless_window.show()
    qapp.processEvents()
    QTest.mouseClick(frameless_window.titlebar.btn_minimize, Qt.LeftButton)
    qapp.processEvents()
    assert frameless_window.isMinimized()


def test_minimized_window_comes_back(frameless_window, qapp):
    frameless_window.show()
    qapp.processEvents()
    frameless_window.showMinimized()
    qapp.processEvents()
    assert frameless_window.isMinimized()
    # This is what the tray menu and a second launch call.
    frameless_window._show_window()
    qapp.processEvents()
    assert frameless_window.isVisible()
    assert not frameless_window.isMinimized()


def test_close_light_hides_to_the_tray(frameless_window, qapp):
    frameless_window.tray = _FakeTray()
    try:
        frameless_window.show()
        qapp.processEvents()
        QTest.mouseClick(frameless_window.titlebar.btn_close, Qt.LeftButton)
        qapp.processEvents()
        assert not frameless_window.isVisible()
        assert frameless_window.timer.isActive()
    finally:
        frameless_window.tray = None


def test_hidden_window_comes_back_from_the_tray(window, qapp):
    window.tray = _FakeTray()
    try:
        window.show()
        qapp.processEvents()
        window.close()
        qapp.processEvents()
        assert not window.isVisible()
        window._show_window()
        qapp.processEvents()
        assert window.isVisible()
    finally:
        window.tray = None


def test_hidden_window_comes_back_on_app_activate(window, qapp):
    # Clicking the Dock icon activates the app with no visible windows; the
    # hidden window must come back, not stay stranded.
    window.tray = _FakeTray()
    try:
        window.show()
        qapp.processEvents()
        window.close()
        qapp.processEvents()
        assert not window.isVisible()
        QApplication.instance().applicationStateChanged.emit(
            Qt.ApplicationActive)
        qapp.processEvents()
        assert window.isVisible()
    finally:
        window.tray = None


def test_startup_hidden_window_stays_hidden_on_app_activate(window, qapp):
    # A login launch that stays in the tray must not pop up just because
    # the app became active; only an explicit show brings it back.
    assert not window.isVisible()
    QApplication.instance().applicationStateChanged.emit(
        Qt.ApplicationActive)
    qapp.processEvents()
    assert not window.isVisible()


def test_close_without_a_tray_quits_outside_macos(window, qapp, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    window.tray = None
    window.show()
    qapp.processEvents()
    window.close()
    qapp.processEvents()
    assert not window.timer.isActive()


def test_close_on_macos_without_a_tray_hides(window, qapp, monkeypatch):
    # The red button closes the window, not the tunnel: even with no tray
    # icon the window hides (Dock / second launch bring it back) and the
    # tunnel keeps running.
    monkeypatch.setattr(sys, "platform", "darwin")
    window.tray = None
    window.show()
    qapp.processEvents()
    window.close()
    qapp.processEvents()
    assert not window.isVisible()
    assert window.timer.isActive()
    window._show_window()
    qapp.processEvents()
    assert window.isVisible()
