"""Activity page: a segmented tab bar switching between the live log, the
diagnostics tools and a read-only diagnostics readout."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import ltr, tr
from ..help import help_html, set_help
from ..mac import InsetGroup
from ..tools_panel import ToolsPanel
from ..widgets import LogView


class _DiagnosticsPanel(QWidget):
    """The four-inset diagnostics readout: current xray process/interface
    pairing plus a "Run diagnostics" button and its raw output."""

    runRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        self._values: dict[str, QLabel] = {}
        group = InsetGroup()
        # Labels translated here, not at module level: tr() bakes the language
        # at call time, but this module is imported before run() sets fa.
        for label, key in (
            (tr("Xray process"), "process"),
            (tr("Interface"), "iface"),
            (tr("Source IPv4"), "ip"),
            (tr("Gateway"), "gateway"),
            (tr("Tunnel device"), "tun"),
        ):
            value = QLabel("—")
            value.setObjectName("Mono")
            group.add_row(label, value)
            self._values[key] = value
        outer.addWidget(group)

        run = QPushButton(tr("Run diagnostics"))
        run.clicked.connect(self.runRequested)
        set_help(run,
                 tr("Collects the network details the tunnel relies on: server ping, "
                    "DNS, routes and the latest log lines."),
                 tr("Asking for help? Paste this output along with your question."))
        run_row = QHBoxLayout()
        run_row.addWidget(run)
        run_row.addStretch(1)
        outer.addLayout(run_row)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        # Raw paths and numbers -- force LTR so lines don't reorder in fa.
        self.output.setLayoutDirection(Qt.LeftToRight)
        outer.addWidget(self.output, 1)

    def set_detail(self, key: str, value: str) -> None:
        label = self._values.get(key)
        # Called from the status tick: an unchanged setText still repaints.
        new = ltr(value)
        if label is not None and label.text() != new:
            label.setText(new)

    def set_output(self, text: str) -> None:
        self.output.setPlainText(text)


class ActivityPage(QWidget):
    pingRequested = Signal()
    delayRequested = Signal()
    throughputRequested = Signal()
    baselineRequested = Signal()
    diagnosticsRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        self.tabs = QTabBar()
        self.tabs.addTab(tr("Live log"))
        self.tabs.addTab(tr("Tools"))
        self.tabs.addTab(tr("Diagnostics"))
        outer.addWidget(self.tabs, 0, Qt.AlignLeft)
        self.tabs.setTabToolTip(0, help_html(
            tr("Everything Xray reports, as it happens."),
            tr("Watch it while you connect to see exactly where it stops.")))
        self.tabs.setTabToolTip(1, help_html(
            tr("Quick checks: ping, delay and speed."),
            tr("Is the slow part the server or your Wi-Fi? Find out in seconds.")))
        self.tabs.setTabToolTip(2, help_html(
            tr("The connection's technical details in one place."),
            tr("Handy to copy when someone asks \"what does it say?\".")))

        self.stack = QStackedWidget()
        self.log = LogView()
        self.tools = ToolsPanel()
        self.diagnostics = _DiagnosticsPanel()
        for widget in (self._build_log_tab(), self.tools, self.diagnostics):
            self.stack.addWidget(widget)
        outer.addWidget(self.stack, 1)
        self.tabs.currentChanged.connect(self.stack.setCurrentIndex)

        # The page is the single surface a sidebar consumer wires into its
        # handlers; the tools segment's signals become the page's own.
        self.tools.pingRequested.connect(self.pingRequested)
        self.tools.delayRequested.connect(self.delayRequested)
        self.tools.throughputRequested.connect(self.throughputRequested)
        self.tools.baselineRequested.connect(self.baselineRequested)
        self.tools.diagnosticsRequested.connect(self.diagnosticsRequested)
        self.diagnostics.runRequested.connect(self.diagnosticsRequested)

    def _build_log_tab(self) -> QWidget:
        """The Live log tab: a compact toolbar (filter, Copy, Clear, same
        row pattern as the Servers table's toolbar) above the log view."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.log_filter = QLineEdit()
        self.log_filter.setPlaceholderText(tr("Filter log…"))
        set_help(self.log_filter,
                 tr("Shows only the log lines containing what you type."),
                 tr("Type \"error\" to see only the failures."))
        self.log_filter.textChanged.connect(self.log.set_filter)
        bar.addWidget(self.log_filter, 1)
        self.btn_copy_log = QPushButton(tr("Copy"))
        self.btn_copy_log.clicked.connect(self.log.copy_visible)
        set_help(self.btn_copy_log,
                 tr("Copies the log lines you see right now."),
                 tr("Paste them into a message when asking for help."))
        bar.addWidget(self.btn_copy_log)
        self.btn_clear_log = QPushButton(tr("Clear"))
        self.btn_clear_log.clicked.connect(self.log.clear_log)
        set_help(self.btn_clear_log,
                 tr("Empties the log view. New lines keep arriving."),
                 tr("Clear it right before connecting to catch fresh output."))
        bar.addWidget(self.btn_clear_log)
        layout.addLayout(bar)
        layout.addWidget(self.log, 1)
        return tab

    def set_busy(self, busy: bool) -> None:
        self.tools.set_busy(busy)

    def append_log(self, line: str) -> None:
        # append_line, not QTextEdit.append: the view's filter buffer must
        # see every line or filtering and Copy drift from what's shown.
        self.log.append_line(line)
