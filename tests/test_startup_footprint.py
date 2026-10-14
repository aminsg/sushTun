"""Startup footprint: heavy modules must stay unimported until first use.

Covers the lazy-import work: urllib/ssl (update/subscription/geo fetches),
segno (QR dialog), the Persian table (English mode), and the dialog windows
with the core modules behind them. A fresh interpreter per check, since the
test session itself imports everything by the time this runs.
"""
from __future__ import annotations

import json
import subprocess
import sys

# Importing xrayui.ui.main_window must not pull any of these in.
LIGHT_AT_LAUNCH = (
    "urllib.request",
    "urllib.error",
    "http.client",
    "ssl",
    "segno",
    "xrayui.i18n_fa",
    "xrayui.ui.dialogs",
    "xrayui.ui.settings_window",
    "xrayui.core.updates",
    "xrayui.core.geo",
)


def _fresh_modules(setup: str) -> set[str]:
    code = (
        "import json, sys; "
        f"{setup}; "
        "print(json.dumps(sorted(sys.modules)))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=".", timeout=120,
    )
    assert out.returncode == 0, out.stderr[-500:]
    return set(json.loads(out.stdout))


def test_launch_imports_stay_light():
    mods = _fresh_modules("import xrayui.ui.main_window")
    assert [m for m in LIGHT_AT_LAUNCH if m in mods] == []


def test_first_use_still_loads_what_it_needs():
    # The lazied pieces must keep working when actually reached.
    mods = _fresh_modules(
        "import xrayui.ui.main_window as m; "
        "from xrayui.ui.server_table import QrDialog; "
        "from xrayui.core import geo_exit; "
        "from xrayui import i18n; "
        "i18n.set_language('fa'); "
        "assert i18n.tr('Servers') != 'Servers'; "
        "assert geo_exit.build_opener(None) is not None"
    )
    assert "segno" not in mods  # only the dialog's __init__ needs it
    assert "xrayui.i18n_fa" in mods


def test_flag_cache_is_bounded():
    from xrayui.ui import flags

    assert flags._render.cache_info().maxsize is not None
    assert flags._render_icon.cache_info().maxsize is not None
