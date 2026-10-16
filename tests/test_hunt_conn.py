"""Bug-hunt cover for the connect/teardown path (hunt-conn)."""
from __future__ import annotations

import subprocess
import types
from unittest.mock import Mock

import pytest
from test_tun_routing import _iface, _stub_connect

from xrayui import paths
from xrayui.core import connection
from xrayui.core.network import DnsState


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


def test_fail_connect_cleans_up_when_bridge_stop_raises(monkeypatch, tmp_path):
    conn, calls = _stub_connect(monkeypatch, tmp_path)

    def hung_bridge():
        calls.append("bridge_stop")
        raise subprocess.TimeoutExpired("tun2socks", 1)

    monkeypatch.setattr(conn.tun2socks, "stop", hung_bridge)
    runtime = paths.runtime_config()
    runtime.write_text("secret")
    removed = []
    monkeypatch.setattr(connection.network, "remove_routes", lambda ip: removed.append(ip))

    def start(cfg):
        raise OSError(13, "Permission denied")

    conn.xray.start = start
    server = "203.0.113.10"
    with pytest.raises(connection.ConnectError, match="Could not start Xray"):
        conn._connect_generic(types.SimpleNamespace(uid="p1"), _iface(), server,
                              DnsState())

    assert "xray_stop" in calls  # teardown continued past the hung bridge
    assert removed == [server, server]  # pre-start sweep plus the failure sweep
    assert not runtime.exists()
    assert not conn.state.is_connected()
