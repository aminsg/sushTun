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


class _HungChild:
    def terminate(self):
        pass

    def kill(self):
        pass

    def poll(self):
        return None

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired("xray", timeout)


def test_speedtest_batch_never_leaves_a_zombie(monkeypatch, tmp_path):
    from xrayui import paths
    from xrayui.core import speedtest

    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(speedtest.subprocess, "Popen", lambda *a, **k: _HungChild())
    monkeypatch.setattr(speedtest, "build_test_config", lambda *a, **k: {})
    monkeypatch.setattr(speedtest, "_wait_ready", lambda *a, **k: True)
    monkeypatch.setattr(speedtest, "_measure_group",
                        lambda *a, **k: None)
    profile = types.SimpleNamespace(uid="p1")

    assert speedtest._run_batch(
        [profile], [54321], url="http://example.com/", timeout=5,
        iface_alias="", on_result=lambda *a: None,
        cancel=__import__("threading").Event()) is True


def test_chain_probe_never_leaves_a_zombie(monkeypatch):
    import threading

    from xrayui.core import chain_test, speedtest

    monkeypatch.setattr(chain_test.subprocess, "Popen", lambda *a, **k: _HungChild())
    monkeypatch.setattr(chain_test, "build_config", lambda *a, **k: {})
    monkeypatch.setattr(speedtest, "_port_open", lambda port: True)
    profiles = [types.SimpleNamespace(uid="p1")]

    with chain_test._temporary(profiles, timeout=5, cancel=threading.Event(),
                               iface_alias="", core_cfg=None) as port:
        assert port > 0


def test_posix_remove_routes_never_raises_when_helpers_missing(monkeypatch):
    from xrayui.core import _net_posix as posix

    def missing(cmd, **kw):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(posix.proc, "run", missing)
    posix.remove_routes("203.0.113.10")  # best effort: must not raise


def test_windows_remove_routes_never_raises_when_helpers_missing(win_net, monkeypatch):
    def missing(cmd, **kw):
        raise FileNotFoundError(2, "The system cannot find the file specified")

    monkeypatch.setattr(win_net.proc, "run", missing)
    win_net.remove_routes("203.0.113.10")  # best effort: must not raise


def test_linux_detect_returns_none_on_garbage_ip_json(monkeypatch):
    import types

    from xrayui.core import _net_posix as posix

    def garbage(cmd, **kw):
        return types.SimpleNamespace(returncode=0, stdout="<not json>")

    monkeypatch.setattr(posix.proc, "run", garbage)
    assert posix._linux_detect() is None  # odd output, not a traceback
    assert posix._link_types() == {}


def test_linux_wait_for_tun_ignores_garbage_ip_json(monkeypatch):
    import types

    from xrayui.core import _net_posix as posix

    def garbage(cmd, **kw):
        return types.SimpleNamespace(returncode=0, stdout="{oops")

    monkeypatch.setattr(posix, "IS_MAC", False)
    monkeypatch.setattr(posix.proc, "run", garbage)
    assert posix.wait_for_tun(timeout=5, alive=lambda: False) is None
