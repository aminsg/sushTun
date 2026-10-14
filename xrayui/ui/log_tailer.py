"""Follow xray.log and stream new lines to the UI."""
from __future__ import annotations

import threading

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

    def __init__(self) -> None:
        super().__init__()
        self._running = True
        self._wake = threading.Event()
        self.interval = self.INTERVAL

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
