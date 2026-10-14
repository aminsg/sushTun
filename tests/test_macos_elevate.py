import ast
import os
import re
import shlex
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

from xrayui import elevate


def _shell_of(script: str) -> str:
    prefix = 'do shell script "'
    suffix = '" with administrator privileges'
    assert script.startswith(prefix) and script.endswith(suffix)
    return ast.literal_eval('"' + script[len(prefix):-len(suffix)] + '"')


def _errlog_of(script: str) -> str:
    return re.search(r"2>(\S+) & echo", _shell_of(script)).group(1)


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(elevate, "IS_MAC", True)
    monkeypatch.setattr(elevate, "_elevated_cmd", lambda: ["/Applications/sushTun.app/x"])
    monkeypatch.setattr(elevate, "_session_args", lambda: [])
    monkeypatch.setattr(elevate, "mac_privacy_blocked", False)
    monkeypatch.setattr(elevate, "_MAC_START_WATCH", 0.3)
    return monkeypatch


def _osascript(mac, returncode=0, stdout="4242\n", stderr="", errlog_text=None, seen=None):
    def fake_run(args, **kwargs):
        assert args[0] == "osascript"
        if seen is not None:
            seen.append(args[2])
        if errlog_text is not None:
            with open(_errlog_of(args[2]), "w") as f:
                f.write(errlog_text)
        return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)
    mac.setattr(subprocess, "run", fake_run)


def test_the_elevated_app_is_started_in_the_background(mac):
    # Waiting for it kept osascript alive all session, and macOS listed that
    # helper as a second "sushTun" in the Dock and Cmd+Tab.
    seen = []
    _osascript(mac, seen=seen)
    mac.setattr(elevate, "_pid_alive", lambda pid: True)
    assert elevate._relaunch_macos() is True
    shell = _shell_of(seen[0])
    assert shell.endswith(" & echo $!")
    assert " >/dev/null 2>" in shell


def test_the_launcher_stops_watching_once_the_app_is_up(mac):
    _osascript(mac)
    mac.setattr(elevate, "_pid_alive", lambda pid: True)
    assert elevate._relaunch_macos() is True


def test_a_cancelled_prompt_opens_unelevated(mac):
    _osascript(mac, returncode=1, stdout="", stderr="execution error: User canceled. (-128)")
    assert elevate._relaunch_macos() is False
    assert elevate.mac_privacy_blocked is False


def test_a_failed_authorization_opens_unelevated(mac):
    _osascript(mac, returncode=1, stdout="", stderr="execution error: not allowed (-60007)")
    assert elevate._relaunch_macos() is False


def test_privacy_protection_is_recognised_when_the_app_dies_at_once(mac):
    _osascript(mac, errlog_text="PermissionError: [Errno 1] Operation not permitted: 'x'")
    mac.setattr(elevate, "_pid_alive", lambda pid: False)
    assert elevate._relaunch_macos() is False
    assert elevate.mac_privacy_blocked is True


def test_any_other_early_exit_is_the_apps_own_and_not_reopened(mac):
    _osascript(mac, errlog_text="something else went wrong")
    mac.setattr(elevate, "_pid_alive", lambda pid: False)
    assert elevate._relaunch_macos() is True
    assert elevate.mac_privacy_blocked is False


def test_no_pid_back_means_nothing_to_watch(mac):
    _osascript(mac, stdout="")
    assert elevate._relaunch_macos() is True


def test_the_log_file_is_removed_afterwards(mac):
    seen = []
    _osascript(mac, seen=seen)
    mac.setattr(elevate, "_pid_alive", lambda pid: True)
    elevate._relaunch_macos()
    assert not os.path.exists(_errlog_of(seen[0]))


def test_pid_alive_treats_a_root_owned_process_as_alive(monkeypatch):
    def deny(pid, sig):
        raise PermissionError
    monkeypatch.setattr(os, "kill", deny)
    assert elevate._pid_alive(1) is True

    def gone(pid, sig):
        raise ProcessLookupError
    monkeypatch.setattr(os, "kill", gone)
    assert elevate._pid_alive(1) is False


def test_relaunch_macos_escaping(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(elevate, "IS_MAC", True)

    script_passed = []

    def fake_run(args, **kwargs):
        if args[0] == "osascript":
            script_passed.append(args[2])
            return MagicMock(returncode=0, stdout="4242\n", stderr="")
        return MagicMock(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    # The actual paths can contain single quotes too, e.g. John's App
    monkeypatch.setattr(elevate, "_elevated_cmd", lambda: ["/path/to/John's app/xrayui", "--some-arg", "He said \"Hello\\World\""])
    monkeypatch.setattr(elevate, "_session_args", lambda: [])
    monkeypatch.setattr(elevate, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(elevate, "_MAC_START_WATCH", 0.2)

    assert elevate._relaunch_macos() is True

    assert len(script_passed) == 1
    script = script_passed[0]
    prefix = 'do shell script "'
    suffix = '" with administrator privileges'
    assert script.startswith(prefix)
    assert script.endswith(suffix)
    literal = script[len(prefix):-len(suffix)]

    evaluated = ast.literal_eval('"' + literal + '"')
    # Only the command itself: the redirections and `& echo $!` are ours.
    evaluated = evaluated.rsplit(" >/dev/null 2>", 1)[0]

    parsed = shlex.split(evaluated)
    assert parsed == ["/path/to/John's app/xrayui", "--some-arg", 'He said "Hello\\World"']
