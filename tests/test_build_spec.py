"""The packaged build must carry every non-Python file the UI loads by path."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_build_spec_bundles_every_ui_data_file():
    spec = (ROOT / "tools" / "build.spec").read_text(encoding="utf-8")
    ui = ROOT / "xrayui" / "ui"
    suffixes = {p.suffix for p in ui.iterdir() if p.is_file() and p.suffix not in {".py", ".pyc"}}
    assert suffixes, "expected at least the checkbox glyph (.svg)"
    for suffix in suffixes:
        # A glob per suffix; a new data file type needs its own line in the spec.
        assert f'glob("*{suffix}")' in spec, f"build.spec does not bundle xrayui/ui/*{suffix}"


def test_build_spec_bundles_the_country_flags():
    spec = (ROOT / "tools" / "build.spec").read_text(encoding="utf-8")
    assert 'ROOT / "assets" / "flags"' in spec
    assert '"*.svg"' in spec
    assert '"*.json"' in spec
    assert '"assets/flags"' in spec
    assert (ROOT / "assets" / "flags" / "names.json").is_file()


def test_build_spec_drops_unused_qt_but_keeps_what_the_app_loads():
    spec = (ROOT / "tools" / "build.spec").read_text(encoding="utf-8")
    for framework in ("QtQml", "QtQuick", "QtPdf", "QtVirtualKeyboard", "QtOpenGL"):
        assert f'"{framework}"' in spec, f"{framework} is no longer excluded from the build"
    start = spec.index("_UNUSED_QT_FRAMEWORKS")
    unused = spec[start:spec.index(")", start)]
    for framework in ("QtSvg", "QtDBus", "QtCore", "QtGui", "QtWidgets", "QtNetwork"):
        # QtSvg renders the flags and the checkbox glyph, QtDBus is linked by
        # QtGui: excluding either would break the packaged app at runtime.
        assert framework not in unused, f"{framework} must stay in the build"
    assert '"PySide6.QtSvg"' not in spec
    assert '"PySide6.QtDBus"' not in spec
    # Qt's own .qm translations (nothing installs a QTranslator) and the
    # QtPdf-bound image plugin go through the same collected-files filter.
    assert "Qt/translations" in spec
    assert "libqpdf" in spec
