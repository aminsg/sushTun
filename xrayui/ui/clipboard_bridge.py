"""Keep Qt's clipboard and the macOS user's clipboard the same.

The elevated sushTun cannot see the user's pasteboard (core/desktop.py), so on
its own every paste into a field found nothing and every copy out of the app
stayed inside it. Whenever the app comes to the front it takes over whatever
the user copied elsewhere, and whatever is copied inside it goes back out.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTextEdit

from ..core import desktop


class SessionClipboard(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        # Last text seen on either side, so a copy this bridge made itself
        # is not sent straight back the way it came.
        self._last: str | None = None
        app.applicationStateChanged.connect(self._on_state)
        app.clipboard().dataChanged.connect(self._on_changed)

    def _on_state(self, state) -> None:
        if state == Qt.ApplicationActive:
            self.pull()

    def pull(self) -> None:
        text = desktop.session_clipboard_text()
        if text is None or text == self._last:
            return
        self._last = text
        self._app.clipboard().setText(text)

    def _on_changed(self) -> None:
        text = self._app.clipboard().text()
        if not text or text == self._last:
            return
        self._last = text
        desktop.set_session_clipboard_text(text)


# -- reaching the clipboard when Qt cannot ------------------------------------
# Qt's clipboard is the process's own pasteboard, and the elevated copy cannot
# reach the macOS pasteboard service at all (launchd: "failed lookup:
# com.apple.pasteboard.1"). SessionClipboard above can therefore read the
# user's text, but setText() has nowhere to put it: Ctrl+V found nothing and a
# copy never left the app. Everything below goes to the user's pasteboard
# through desktop.py directly and only uses Qt's clipboard as a fallback.

def elevated_on_mac() -> bool:
    return (sys.platform == "darwin" and hasattr(os, "geteuid")
            and os.geteuid() == 0)


def text() -> str:
    """What the user has copied."""
    if elevated_on_mac():
        session = desktop.session_clipboard_text()
        if session is not None:
            return session
    return QApplication.clipboard().text()


def set_text(value: str) -> None:
    """Copy `value` for the user."""
    QApplication.clipboard().setText(value)
    if elevated_on_mac():
        desktop.set_session_clipboard_text(value)


class ClipboardKeys(QObject):
    """Cut, copy and paste in text fields, for the elevated copy on macOS.

    The fields' own shortcuts talk to Qt's clipboard, which is unreachable
    there, so the three keys are answered here instead.
    """

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        app.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt API
        if event.type() != QEvent.KeyPress:
            return False
        if not isinstance(obj, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return False
        if event.matches(QKeySequence.Paste):
            return self.paste(obj)
        if event.matches(QKeySequence.Copy):
            return self.copy(obj)
        if event.matches(QKeySequence.Cut):
            return self.cut(obj)
        return False

    @staticmethod
    def _selected(field) -> str:
        if isinstance(field, QLineEdit):
            return field.selectedText()
        # A text cursor writes line breaks as U+2029.
        return field.textCursor().selectedText().replace(" ", "\n")

    def paste(self, field) -> bool:
        if field.isReadOnly():
            return False
        value = text()
        if not value:
            return True
        if isinstance(field, QLineEdit):
            field.insert(value)
        else:
            field.insertPlainText(value)
        return True

    def copy(self, field) -> bool:
        value = self._selected(field)
        if value:
            set_text(value)
        return True

    def cut(self, field) -> bool:
        value = self._selected(field)
        if not value or field.isReadOnly():
            return True
        set_text(value)
        if isinstance(field, QLineEdit):
            field.del_()
        else:
            field.textCursor().removeSelectedText()
        return True
