"""Menu-bar (tray) status icon: sushbot when idle, the exit flag when connected.

The icon is derived only from (state, country, appearance) and cached, so the
window can refresh it from every existing connection-state callback at
near-zero cost with no timers or polling.

Why full-colour, not a macOS template image: a template image keeps only the
alpha channel and the system tints it monochrome (Qt: ``QIcon.setIsMask(True)``;
Apple: ``NSImage.template = YES``). That is right for a symbolic glyph but
destroys a flag and the mascot, so every icon here is explicitly *not* a mask
and is drawn to stay visible on both light and dark bars: flags get a neutral
hairline border (white flags on a light bar, dark flags on a dark bar), and
the status dot gets a contrasting ring.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from .. import paths
from ..core import geo_exit
from ..i18n import tr

# macOS menu-bar icons are ~22 pt high; the flag fills most of that height so
# it reads at a glance, with a small margin so the rounded corners never clip.
_TRAY_PT = 22
_FLAG_W, _FLAG_H = 20, 15
_FLAG_RADIUS = 3.0
_DOT_R = 5.0
_CONNECTED_DOT = QColor(48, 209, 88)  # iOS/macOS system green
_CONNECTING_DOT = QColor(255, 159, 10)  # system orange
# One hairline visible on both appearances: black vanishes on a dark bar and
# white vanishes on a light one, so a mid grey is used for the flag edge.
_EDGE = QColor(127, 127, 127, 150)

_cache: dict[tuple, QIcon] = {}
_pix_cache: dict[tuple, QPixmap] = {}


def system_is_dark() -> bool:
    """Best-effort dark-appearance probe via the app palette.

    The menu bar follows the system appearance and the app theme follows dark
    mode too, so the palette's lightness is a cheap proxy. Anything unknown
    (no app yet) is light; the icons are drawn to work on both anyway.
    """
    app = QApplication.instance()
    if app is None:
        return False
    try:
        return app.palette().window().color().lightness() < 128
    except Exception:
        return False


def _device_ratio() -> float:
    # Always ship at least @2x: offscreen (and a 1x external display) reports
    # 1.0, but the menu bar on a Retina Mac needs the 2x asset regardless.
    screen = QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    return max(float(ratio or 1.0), 2.0)


def _sushbot_source() -> QPixmap | None:
    png = paths.icon_png()
    if not png.exists():
        return None
    pix = QPixmap(str(png))
    return pix if not pix.isNull() else None


def tray_pixmap(state: str, country_code: str | None = None, dark: bool = False) -> QPixmap:
    """The tray image at logical 22pt, device pixels = 22 * dpr, DPR set on it."""
    code = geo_exit.normalize(country_code)
    if state not in ("disconnected", "connecting", "connected"):
        state = "disconnected"
    # Only the connected flag varies by country; the other states always show
    # the mascot (with or without a badge), so they share one cache entry.
    if state != "connected":
        code = None
    dpr = _device_ratio()
    key = (state, code, bool(dark), dpr)
    cached = _pix_cache.get(key)
    if cached is not None:
        return cached

    edge = round(_TRAY_PT * dpr)
    pix = QPixmap(edge, edge)
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

    if state == "connected" and code is not None:
        _paint_flag(p, code, dpr)
    else:
        _paint_sushbot(p, dpr, dark)
        if state == "connected":
            _paint_dot(p, _CONNECTED_DOT)
        elif state == "connecting":
            _paint_dot(p, _CONNECTING_DOT)
    p.end()
    _pix_cache[key] = pix
    return pix


def _paint_flag(p: QPainter, code: str, dpr: float) -> None:
    renderer = QSvgRenderer(str(geo_exit.flag_path(code)))
    if not renderer.isValid():
        # A flag that cannot be drawn must never be blank: fall back to the
        # mascot with the connected badge instead of a wrong/empty icon.
        _paint_sushbot(p, dpr, False)
        _paint_dot(p, _CONNECTED_DOT)
        return
    x = (_TRAY_PT - _FLAG_W) / 2
    y = (_TRAY_PT - _FLAG_H) / 2
    rect = QRectF(x, y, _FLAG_W, _FLAG_H)
    clip = QPainterPath()
    clip.addRoundedRect(rect, _FLAG_RADIUS, _FLAG_RADIUS)
    p.setClipPath(clip)
    renderer.render(p, rect)
    p.setClipping(False)
    edge = QPen(_EDGE)
    edge.setWidthF(1.0)
    p.setPen(edge)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), _FLAG_RADIUS - 0.5, _FLAG_RADIUS - 0.5)


def _paint_sushbot(p: QPainter, dpr: float, dark: bool) -> None:
    src = _sushbot_source()
    if src is None:
        # No mascot on disk (dev tree without assets): a filled disc keeps the
        # tray showing something rather than nothing.
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(140, 140, 140)))
        p.drawEllipse(QRectF(2, 2, _TRAY_PT - 4, _TRAY_PT - 4))
        return
    # Fit the square mascot inside the tray square with a 1pt margin.
    side = _TRAY_PT - 2
    target = QRectF(1, 1, side, side)
    p.drawPixmap(target, src, QRectF(0, 0, src.width(), src.height()))
    if dark:
        # The mascot tile is dark-baked, so on a dark bar its outline
        # dissolves; a faint light frame keeps it defined.
        frame = QPen(QColor(255, 255, 255, 90))
        frame.setWidthF(1.0)
        p.setPen(frame)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(target.adjusted(0.5, 0.5, -0.5, -0.5), 5.0, 5.0)


def _paint_dot(p: QPainter, color: QColor) -> None:
    # Bottom-right badge with a contrasting ring so it reads on either bar.
    cx, cy = _TRAY_PT - 1 - _DOT_R, _TRAY_PT - 1 - _DOT_R
    p.setPen(QPen(QColor(255, 255, 255, 230)))
    p.setBrush(QBrush(color))
    p.drawEllipse(QRectF(cx - _DOT_R, cy - _DOT_R, _DOT_R * 2, _DOT_R * 2))


def tray_icon(state: str, country_code: str | None = None, dark: bool = False) -> QIcon:
    """Cached full-colour tray QIcon for (state, country, appearance)."""
    pix = tray_pixmap(state, country_code, dark)
    key = (pix.cacheKey(),)
    icon = _cache.get(key)
    if icon is None:
        icon = QIcon(pix)
        # Full colour: a mask would reduce flags and the mascot to a silhouette.
        icon.setIsMask(False)
        _cache[key] = icon
    return icon


def tray_tooltip(state: str, server_name: str = "", country_code: str | None = None) -> str:
    """Tooltip text: state + server name + country, translated."""
    from ..i18n import current

    if state == "connected":
        code = geo_exit.normalize(country_code)
        country = geo_exit.country_name(code, current()) if code else ""
        name = (server_name or "").strip()
        if code and country and name:
            return tr("sushTun — Connected · {server} ({country})",
                      server=name, country=country)
        if name:
            return tr("sushTun — Connected · {server}", server=name)
        if code and country:
            return tr("sushTun — Connected · {country}", country=country)
        return tr("sushTun — Connected")
    if state == "connecting":
        return tr("sushTun — Connecting…")
    return tr("sushTun — Disconnected")


def clear_cache() -> None:
    _cache.clear()
    _pix_cache.clear()
