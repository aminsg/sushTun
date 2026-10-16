"""Two late-widget races around the editing dialogs:

1. Dialogs spawned from the main window (DNS / Routing / Settings) stay
   children of that window forever after close, one whole editor per cycle.
2. A validation worker whose page was destroyed before it finishes must
   stay silent, not raise against dead widgets.
"""
from __future__ import annotations

import os
import sys
import threading

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    from xrayui import paths
    from xrayui.ui.main_window import MainWindow

    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()

    def no_exec(self, *a, **k):
        return 0

    monkeypatch.setattr("xrayui.ui.main_window.DnsDialog.exec", no_exec)
    monkeypatch.setattr("xrayui.ui.main_window.RoutingDialog.exec", no_exec)
    monkeypatch.setattr(
        "xrayui.ui.settings_window.SettingsWindow.exec", no_exec)

    win = MainWindow(elevated=False)
    try:
        yield win
    finally:
        win.close()
        win.deleteLater()
        _flush()


def _flush() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_dns_dialog_cycles_leave_nothing_behind(window):
    from xrayui.ui.dns_dialog import DnsDialog

    for _ in range(4):
        window._open_dns()
    _flush()
    assert len(window.findChildren(DnsDialog)) == 0


def test_routing_dialog_cycles_leave_nothing_behind(window):
    from xrayui.ui.routing_dialog import RoutingDialog

    for _ in range(4):
        window._open_routing()
    _flush()
    assert len(window.findChildren(RoutingDialog)) == 0


def test_settings_window_cycles_leave_nothing_behind(window):
    from xrayui.ui.settings_window import SettingsWindow

    for _ in range(4):
        window._open_settings()
    _flush()
    assert len(window.findChildren(SettingsWindow)) == 0


def test_a_late_validation_result_does_not_touch_a_dead_page(qapp, monkeypatch):
    import gc

    from xrayui.ui.pages import dns_page as dns_mod
    from xrayui.ui.pages.dns_page import DnsPage

    blocker = threading.Event()

    def slow_check(text):
        blocker.wait(10)
        return ""

    monkeypatch.setattr(dns_mod.xraycheck, "check_config", slow_check)

    errors: list[BaseException] = []
    hook = sys.excepthook

    def recording(kind, value, tb):
        if kind is RuntimeError:
            errors.append(value)

    sys.excepthook = recording
    try:
        page = DnsPage({}, {})
        page.apply()
        page.deleteLater()
        _flush()
        blocker.set()
        for _ in range(20):
            qapp.processEvents()
        gc.collect()
    finally:
        sys.excepthook = hook

    bad = [e for e in errors if "already deleted" in str(e)]
    assert not bad, bad
