"""macOS: the elevated app reads and writes the user's clipboard through them.

Root cannot see the logged-in user's pasteboard, so every paste into sushTun
found nothing while other apps pasted fine, and a copied share link never left
the app. Nothing here can reach a real pasteboard on Linux: these pin who runs
pbpaste/pbcopy, and how the Qt side stays in step without echoing.
"""
from __future__ import annotations

import os
import subprocess
import sys
import types

import pytest

from xrayui.core import desktop


@pytest.fixture
def mac_root(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(desktop.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setenv("SUDO_UID", "501")
    monkeypatch.delenv("PKEXEC_UID", raising=False)
    entry = types.SimpleNamespace(pw_uid=501, pw_gid=20, pw_name="ada", pw_dir="/Users/ada")
    monkeypatch.setitem(sys.modules, "pwd", types.SimpleNamespace(getpwuid=lambda _u: entry))
    monkeypatch.setattr(desktop.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name in ("pbpaste", "pbcopy", "sudo")
                        else None)


@pytest.fixture
def ran(monkeypatch):
    calls = []

    def fake(argv, **kw):
        calls.append((argv, kw))
        out = b"vless://copied-in-safari\n" if argv[-1] == "pbpaste" else b""
        return subprocess.CompletedProcess(argv, 0, out, b"")

    monkeypatch.setattr(desktop.subprocess, "run", fake)
    return calls


def test_paste_reads_the_users_clipboard_as_the_user(mac_root, ran):
    assert desktop.session_clipboard_text() == "vless://copied-in-safari\n"
    argv, kw = ran[0]
    assert argv == ["launchctl", "asuser", "501", "sudo", "-n", "-u", "#501", "--", "pbpaste"]
    assert kw["env"]["LANG"] == "en_US.UTF-8"  # non-ASCII survives


def test_copy_writes_to_the_users_clipboard_as_the_user(mac_root, ran):
    assert desktop.set_session_clipboard_text("سرور آلمان") is True
    argv, kw = ran[0]
    assert argv == ["launchctl", "asuser", "501", "sudo", "-n", "-u", "#501", "--", "pbcopy"]
    assert kw["input"] == "سرور آلمان".encode()


def test_nothing_is_done_where_qt_can_reach_the_clipboard(monkeypatch, ran):
    # Not elevated, or not macOS: Qt's own clipboard is the user's.
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(desktop.os, "geteuid", lambda: 501, raising=False)
    assert desktop.session_clipboard_text() is None
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(desktop.os, "geteuid", lambda: 0, raising=False)
    assert desktop.set_session_clipboard_text("x") is False
    assert ran == []


def test_a_failed_read_is_not_mistaken_for_an_empty_clipboard(mac_root, monkeypatch):
    monkeypatch.setattr(desktop.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, b"", b"denied"))
    assert desktop.session_clipboard_text() is None


# -- the Qt side ---------------------------------------------------------------
pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui.ui import clipboard_bridge  # noqa: E402


@pytest.fixture
def bridge(monkeypatch):
    app = QApplication.instance() or QApplication([])
    app.clipboard().setText("")
    pushed = []
    monkeypatch.setattr(clipboard_bridge.desktop, "session_clipboard_text",
                        lambda: "vless://copied-in-safari")
    monkeypatch.setattr(clipboard_bridge.desktop, "set_session_clipboard_text",
                        lambda text: pushed.append(text) or True)
    b = clipboard_bridge.SessionClipboard(app)
    yield app, b, pushed
    # deleteLater needs an event loop the tests never run; a bridge left
    # connected would answer the next test's clipboard changes too.
    app.applicationStateChanged.disconnect(b._on_state)
    app.clipboard().dataChanged.disconnect(b._on_changed)


def test_coming_to_the_front_brings_in_what_the_user_copied(bridge):
    app, b, pushed = bridge
    b.pull()
    assert app.clipboard().text() == "vless://copied-in-safari"
    assert pushed == []  # not echoed straight back out


def test_a_copy_inside_the_app_goes_out_to_the_user(bridge):
    app, _b, pushed = bridge
    app.clipboard().setText("vless://share-link-from-the-table")
    app.processEvents()
    assert pushed == ["vless://share-link-from-the-table"]


# -- cut, copy and paste where Qt's clipboard cannot be reached ---------------
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit  # noqa: E402


@pytest.fixture
def session(monkeypatch):
    """A fake user pasteboard behind desktop.py, with the process 'elevated'."""
    app = QApplication.instance() or QApplication([])
    box = {"text": "vless://from-safari"}
    monkeypatch.setattr(clipboard_bridge, "elevated_on_mac", lambda: True)
    monkeypatch.setattr(clipboard_bridge.desktop, "session_clipboard_text",
                        lambda: box["text"])
    monkeypatch.setattr(clipboard_bridge.desktop, "set_session_clipboard_text",
                        lambda t: box.update(text=t) or True)
    # The keys act through the helper directly; no event filter is installed.
    return app, box, clipboard_bridge.ClipboardKeys.__new__(clipboard_bridge.ClipboardKeys)


def test_text_reads_the_users_pasteboard_when_elevated(session):
    _app, box, _keys = session
    assert clipboard_bridge.text() == "vless://from-safari"


def test_text_falls_back_to_qt_when_the_read_failed(session, monkeypatch):
    app, _box, _keys = session
    monkeypatch.setattr(clipboard_bridge.desktop, "session_clipboard_text", lambda: None)
    app.clipboard().setText("qt-text")
    assert clipboard_bridge.text() == "qt-text"


def test_set_text_reaches_the_users_pasteboard(session):
    _app, box, _keys = session
    clipboard_bridge.set_text("vless://share")
    assert box["text"] == "vless://share"


def test_paste_inserts_the_users_text_into_a_line_edit(session):
    _app, _box, keys = session
    field = QLineEdit("ab")
    field.setCursorPosition(1)
    assert keys.paste(field) is True
    assert field.text() == "avless://from-safarib"


def test_paste_inserts_into_a_multiline_field(session):
    _app, box, keys = session
    box["text"] = "line1\nline2"
    field = QPlainTextEdit()
    keys.paste(field)
    assert field.toPlainText() == "line1\nline2"


def test_paste_leaves_a_read_only_field_alone(session):
    _app, _box, keys = session
    field = QLineEdit("fixed")
    field.setReadOnly(True)
    assert keys.paste(field) is False
    assert field.text() == "fixed"


def test_copy_and_cut_send_the_selection_out(session):
    _app, box, keys = session
    field = QLineEdit("hello world")
    field.setSelection(0, 5)
    keys.copy(field)
    assert box["text"] == "hello"
    box["text"] = ""
    keys.cut(field)
    assert box["text"] == "hello"
    assert field.text() == " world"


def test_copy_of_a_multiline_selection_keeps_its_line_breaks(session):
    _app, box, keys = session
    field = QPlainTextEdit("a\nb")
    field.selectAll()
    keys.copy(field)
    assert box["text"] == "a\nb"
