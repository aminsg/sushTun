"""Bug-hunt cover for the connect/teardown path (hunt-conn)."""
from __future__ import annotations

import subprocess
from unittest.mock import Mock


def test_xray_stop_never_raises_for_unkillable_child(monkeypatch, tmp_path):
    from xrayui.core import xray

    monkeypatch.setattr(xray, "_kill_all", lambda: None)
    child = Mock(pid=4321)
    child.poll.return_value = None
    child.wait.side_effect = subprocess.TimeoutExpired("xray", 3)
    process = xray.XrayProcess()
    process._proc = child
    log_path = tmp_path / "xray.log"
    process._log = open(log_path, "w", encoding="utf-8")

    process.stop()  # must not raise even when SIGKILL does not reap it

    assert process._proc is None
    assert process._log is None
