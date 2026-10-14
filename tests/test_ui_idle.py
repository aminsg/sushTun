"""Idle-battery regression tests: while the window is hidden or minimised,
nothing UI-only may run. A timer that keeps firing there wakes the CPU (and
on a laptop, the whole machine) for nobody.
"""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.ui.connection_header import ConnectionHeader  # noqa: E402
from xrayui.ui.log_tailer import LogTailer  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    from xrayui.ui.main_window import MainWindow
    win = MainWindow(elevated=False)
    yield win
    # A bare close() only hides on macOS (the tunnel keeps running), which
    # would leave the log tailer thread behind; quit for real instead.
    win.prepare_quit()
    win.close()
    qapp.processEvents()


def _pump(qapp):
    qapp.processEvents()
    qapp.processEvents()


def test_status_timer_stops_while_hidden_and_resumes_on_show(window, qapp):
    window.show()
    _pump(qapp)
    assert window.timer.isActive()
    assert window.timer.interval() == 2000
    window.hide()
    _pump(qapp)
    assert not window.timer.isActive(), "hidden window must not tick the status timer"
    assert window.tailer.interval == LogTailer.IDLE_INTERVAL
    window.show()
    _pump(qapp)
    assert window.timer.isActive()
    assert window.timer.interval() == 2000
    assert window.tailer.interval == LogTailer.INTERVAL


def test_route_supervision_slows_but_continues_while_connected_hidden(
        window, qapp, monkeypatch):
    from xrayui.ui import main_window as mw
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    window.show()
    _pump(qapp)
    assert window.route_timer.interval() == 15_000
    window.hide()
    _pump(qapp)
    assert not window.timer.isActive()
    assert window.route_timer.isActive(), "the tunnel check must survive hiding"
    assert window.route_timer.interval() == mw._ROUTE_HIDDEN_MS
    assert mw._ROUTE_HIDDEN_MS > 15_000
    window.show()
    _pump(qapp)
    assert window.route_timer.interval() == 15_000


def test_route_timer_stops_while_hidden_and_disconnected(window, qapp):
    window.show()
    _pump(qapp)
    window.hide()
    _pump(qapp)
    assert not window.timer.isActive()
    assert not window.route_timer.isActive(), \
        "nothing supervises a tunnel that is not running"


def test_minimise_pauses_the_status_tick(window, qapp):
    window.show()
    _pump(qapp)
    assert window.timer.isActive()
    window.showMinimized()
    _pump(qapp)
    assert window.isMinimized()
    assert not window.timer.isActive(), "a minimised window must not tick either"
    window.showNormal()
    _pump(qapp)
    assert window.timer.isActive()


def test_hidden_window_buffers_log_lines_and_flushes_on_show(window, qapp):
    window.hide()
    _pump(qapp)
    before = window.log.toPlainText()
    window._on_log_lines(["hidden line 1", "hidden line 2"])
    _pump(qapp)
    assert window.log.toPlainText() == before, "no layout work while hidden"
    assert window._pending_log == ["hidden line 1", "hidden line 2"]
    window.show()
    _pump(qapp)
    text = window.log.toPlainText()
    assert "hidden line 1" in text and "hidden line 2" in text
    assert window._pending_log == []


def test_pending_log_buffer_is_bounded(window, qapp):
    window.hide()
    _pump(qapp)
    window._on_log_lines([f"line {i}" for i in range(2000)])
    assert len(window._pending_log) <= 500
    assert window._pending_log[-1] == "line 1999"


def test_polling_timers_are_coarse(window):
    assert window.timer.timerType() == Qt.CoarseTimer
    assert window.route_timer.timerType() == Qt.CoarseTimer
    assert window.alert_timer.timerType() == Qt.CoarseTimer
    assert window.autorefresh_timer.timerType() == Qt.VeryCoarseTimer
    assert window.geo_timer.timerType() == Qt.VeryCoarseTimer
    assert window.update_check_timer.timerType() == Qt.VeryCoarseTimer


def test_tailer_wakes_less_often_while_hidden():
    assert LogTailer.IDLE_INTERVAL > LogTailer.INTERVAL


def test_header_skips_settext_when_nothing_changed(qapp, monkeypatch):
    h = ConnectionHeader()
    calls: list[str] = []
    orig = QLabel.setText
    monkeypatch.setattr(QLabel, "setText",
                        lambda self, text: (calls.append(text), orig(self, text)))
    h.set("throughput", "1.0 Mbit/s")
    h.set("endpoint", "de.example.com:443")
    first = len(calls)
    assert first > 0
    h.set("throughput", "1.0 Mbit/s")
    h.set("endpoint", "de.example.com:443")
    assert len(calls) == first, "re-setting the same values must not touch labels"
    h.set("throughput", "2.0 Mbit/s")
    assert len(calls) > first


# -- tray state while hidden -------------------------------------------------
# Offscreen there is no system tray, so these install a stub that records
# tooltip changes. The point: connection-state changes reach the tray
# through events, never through the status tick that stops while hidden.
class _TrayStub:
    def __init__(self):
        self.tips: list[str] = []

    def setToolTip(self, tip: str) -> None:
        self.tips.append(tip)


@pytest.fixture
def tray_window(window, monkeypatch):
    from xrayui.core.profiles import Profile
    a = window.store.save(Profile(name="A", address="a.example.com",
                                  port=443, id="u1"))
    b = window.store.save(Profile(name="B", address="b.example.com",
                                  port=8443, id="u2"))
    window.store.set_active(a.uid)
    window._reload_profiles()
    window.tray = _TrayStub()
    window._tray_tip = None
    # Exit detection would probe the real network from a pool worker.
    monkeypatch.setattr(window, "_detect_exit_after_connect", lambda: None)
    return window, a, b


def test_hidden_connect_updates_the_tray_tooltip(tray_window, qapp, monkeypatch):
    window, a, _b = tray_window
    window.hide()
    _pump(qapp)
    assert not window.timer.isActive()
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    window._on_conn_done()
    _pump(qapp)
    assert window.tray.tips, "a hidden connect must still reach the tray"
    assert "A" in window.tray.tips[-1]
    assert window.tray.tips[-1] != "sushTun"
    assert not window.timer.isActive(), "no timer restart for the tray update"
    # The re-armed route supervision keeps watching the tunnel while hidden.
    assert window.route_timer.isActive()


def test_hidden_disconnect_resets_the_tray_tooltip(tray_window, qapp, monkeypatch):
    window, _a, _b = tray_window
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    window._on_conn_done()
    assert window.tray.tips[-1] != "sushTun"
    window.hide()
    _pump(qapp)
    monkeypatch.setattr(window.conn, "is_connected", lambda: False)
    window._on_conn_done()
    _pump(qapp)
    assert window.tray.tips[-1] == "sushTun"
    assert not window.timer.isActive()


def test_hidden_failure_resets_the_tray_tooltip(tray_window, qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    window, _a, _b = tray_window
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    window._on_conn_done()
    window.hide()
    _pump(qapp)
    monkeypatch.setattr(window.conn, "is_connected", lambda: False)
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: None))
    window._on_conn_done(error="boom")
    _pump(qapp)
    assert window.tray.tips[-1] == "sushTun"
    assert not window.timer.isActive()


def test_hidden_server_switch_updates_the_tray_tooltip(tray_window, qapp, monkeypatch):
    window, _a, b = tray_window
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    window.hide()
    _pump(qapp)
    window._set_active(b.uid)
    _pump(qapp)
    assert "B" in window.tray.tips[-1], "switching servers must reach the tray hidden"
    assert not window.timer.isActive()


def test_hidden_reconnect_keeps_the_tray_current(tray_window, qapp, monkeypatch):
    window, _a, _b = tray_window
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    window.hide()
    _pump(qapp)
    before = list(window.tray.tips)
    window._on_conn_done()
    _pump(qapp)
    assert window.tray.tips[-1] != "sushTun"
    assert len(window.tray.tips) >= len(before)
    assert not window.timer.isActive()


def test_hidden_exit_detection_lands_without_the_tick(tray_window, qapp, monkeypatch):
    from types import SimpleNamespace
    window, a, _b = tray_window
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    window.hide()
    _pump(qapp)
    window._on_exit_detected(a.uid, SimpleNamespace(country="de", ip="9.9.9.9"))
    _pump(qapp)
    assert window.results.get(a.uid) == {"country": "de", "exit_ip": "9.9.9.9"}
    assert not window.timer.isActive()
