"""Follow xray.log and stream new lines to the UI."""
from __future__ import annotations

import threading
import weakref
from typing import ClassVar

from PySide6.QtCore import QThread, Signal

from .. import paths
from ..core.logtail import read_new_lines


class LogTailer(QThread):
    lines = Signal(list)
    INTERVAL = 0.5
    # While the window is hidden nobody reads the log view: lines still
    # arrive, just in larger batches, and the thread wakes ten times less
    # often (fewer CPU wake-ups on battery).
    IDLE_INTERVAL = 5.0
    # Every tailer ever started, for stop_all(): a window closed to the
    # tray keeps its tailer running by design, so a forgotten window must
    # not leave its thread to die with the interpreter (segfaults in QThread
    # teardown). Weak refs only; drained on every stop_all().
    _live: ClassVar[list] = []

    def __init__(self) -> None:
        super().__init__()
        self._running = True
        self._wake = threading.Event()
        self.interval = self.INTERVAL
        LogTailer._live.append(weakref.ref(self))

    def run(self) -> None:
        path = paths.log_file()
        pos: int | None = None
        while self._running:
            try:
                if path.exists():
                    batch, pos = read_new_lines(path, pos)
                    if batch:
                        self.lines.emit(batch)
            except OSError:
                pass
            # An event, not time.sleep, so stop() wakes the thread at once
            # instead of waiting out the whole (idle, seconds-long) interval.
            self._wake.wait(self.interval)

    def stop(self) -> None:
        self._running = False
        self._wake.set()
        self.wait(1500)

    @classmethod
    def stop_all(cls) -> None:
        """Join every tailer still running (test teardown safety net)."""
        live, cls._live = cls._live, []
        for ref in live:
            tailer = ref()
            if tailer is None:
                continue
            try:
                running = tailer.isRunning()
            except RuntimeError:
                continue
            if running:
                try:
                    tailer.stop()
                except RuntimeError:
                    pass
