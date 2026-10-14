"""Activity page Live log: toolbar (filter/Copy/Clear), empty-state hint and
cheap incremental filtering (T3-05)."""
from __future__ import annotations

import os
import time

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from xrayui import i18n  # noqa: E402
from xrayui.ui.pages.activity_page import ActivityPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(qapp):
    p = ActivityPage()
    p.show()
    QApplication.processEvents()
    yield p
    p.close()
    p.deleteLater()
    QApplication.processEvents()


@pytest.fixture
def english():
    old = i18n.current()
    i18n.set_language("en")
    yield
    i18n.set_language(old)


def _pump(condition, timeout=5.0) -> None:
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


def _buttons(page):
    return {b.text(): b for b in page.findChildren(QPushButton)}


# -- toolbar exists and is wired -------------------------------------------
def test_log_toolbar_has_filter_copy_and_clear(page, english):
    assert page.log_filter.placeholderText()  # the filter field
    assert page.log_filter.toolTip()
    btns = _buttons(page)
    assert "Copy" in btns and "Clear" in btns
    assert btns["Copy"].toolTip() and btns["Clear"].toolTip()


def test_log_clear_button_empties_the_view(page, english):
    page.append_log("[sys] hello")
    QApplication.processEvents()
    assert page.log.toPlainText().strip()
    _buttons(page)["Clear"].click()
    assert page.log.toPlainText().strip() == ""


def test_log_copy_button_copies_what_is_visible(page, english, monkeypatch):
    copied = []
    monkeypatch.setattr("xrayui.ui.widgets.clipboard_bridge.set_text",
                        lambda text: copied.append(text))
    page.log.clear_log()
    page.log.append_lines(["first line", "second line"])
    _buttons(page)["Copy"].click()
    assert copied == ["first line\nsecond line"]


def test_log_empty_hint_shows_until_output_arrives(page, english):
    page.log.clear_log()
    QApplication.processEvents()
    assert page.log.empty_hint.isVisible()
    page.append_log("[sys] connected")
    QApplication.processEvents()
    assert not page.log.empty_hint.isVisible()
    page.log.clear_log()
    QApplication.processEvents()
    assert page.log.empty_hint.isVisible()


# -- filtering is cheap ------------------------------------------------------
def test_log_filter_debounces_a_full_rerender(page, english, monkeypatch):
    page.log.clear_log()
    page.log.append_lines([f"line {i}" for i in range(1000)])
    QApplication.processEvents()
    calls = []
    orig = page.log._apply_filter
    monkeypatch.setattr(page.log, "_apply_filter",
                        lambda: (calls.append(1), orig()), raising=False)
    # Keystrokes without pumping in between: the timer cannot fire mid-word,
    # so no keystroke may trigger a full re-render on its own.
    for ch in "line 1":
        page.log_filter.setText(page.log_filter.text() + ch)
    assert calls == []
    _pump(lambda: calls, timeout=5.0)
    assert len(calls) == 1  # one render for the whole word, not six


def test_log_new_lines_filter_incrementally(page, english, monkeypatch):
    page.log.clear_log()
    page.log.append_lines(["error one", "info one", "error two"])
    page.log_filter.setText("error")
    _pump(lambda: "info one" not in page.log.toPlainText(), timeout=5.0)
    assert "error one" in page.log.toPlainText()

    calls = []
    orig = page.log._apply_filter
    monkeypatch.setattr(page.log, "_apply_filter",
                        lambda: (calls.append(1), orig()), raising=False)
    page.log.append_lines(["info two", "error three"])
    QApplication.processEvents()
    assert calls == []  # no full re-render for new lines
    shown = page.log.toPlainText()
    assert "error three" in shown
    assert "info two" not in shown


def test_log_copy_respects_the_filter(page, english, monkeypatch):
    copied = []
    monkeypatch.setattr("xrayui.ui.widgets.clipboard_bridge.set_text",
                        lambda text: copied.append(text))
    page.log.clear_log()
    page.log.append_lines(["error one", "info one"])
    page.log_filter.setText("error")
    _pump(lambda: "info one" not in page.log.toPlainText(), timeout=5.0)
    _buttons(page)["Copy"].click()
    assert copied == ["error one"]
    page.log_filter.clear()


def test_log_keeps_the_5000_line_cap(page, english):
    page.log.clear_log()
    page.log_filter.clear()
    _pump(lambda: page.log._needle == "", timeout=5.0)
    page.log.append_lines([f"line {i}" for i in range(6000)])
    assert page.log.document().blockCount() <= 5000
    assert len(page.log._lines) == 5000
    assert page.log._lines[-1] == "line 5999"  # newest lines are kept


def test_log_view_runs_no_timers_when_idle_or_hidden(page, english):
    _pump(lambda: not page.log._debounce.isActive(), timeout=5.0)
    assert all(t.isSingleShot() for t in page.log.findChildren(QTimer))
    assert not any(t.isActive() for t in page.log.findChildren(QTimer))
    page.hide()
    QApplication.processEvents()
    assert not any(t.isActive() for t in page.log.findChildren(QTimer))
    page.show()


def test_log_toolbar_strings_are_translated(page):
    old = i18n.current()
    i18n.set_language("fa")
    try:
        fa_page = ActivityPage()
        fa_page.show()
        QApplication.processEvents()
        assert fa_page.log_filter.placeholderText() != "Filter log…"
        texts = {b.text() for b in fa_page.findChildren(QPushButton)}
        assert "Copy" not in texts and "Clear" not in texts
        assert fa_page.log.empty_hint.text() != "Connect to see xray's output here."
        fa_page.close()
        fa_page.deleteLater()
    finally:
        i18n.set_language(old)
    QApplication.processEvents()
