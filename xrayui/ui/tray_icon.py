"""Menu-bar (tray) status icon: mascot glyph when idle, the exit flag when connected.

The icon is derived only from (state, country, appearance) and cached, so the
window can refresh it from every existing connection-state callback at
near-zero cost with no timers or polling.

Why a macOS template image for the idle glyph: every other menu-bar icon is a
simple transparent monochrome glyph that the system tints black on a light bar
and white on a dark bar (Apple: ``NSImage.isTemplate`` — "only black and clear
content"; Qt: ``QIcon.setIsMask(True)`` — "menu icons on macOS"). The old icon
shrunk the full-colour 512px app tile to 22pt, which read as a busy dark square
with a light frame next to those glyphs. The disconnected state is therefore a
hand-drawn monochrome sushi-roll glyph with no tile and no frame, marked as a
mask so macOS tints it (including the highlighted/pressed state) for free.

A template keeps only alpha, so it cannot carry the amber/green badge: the
connecting and unknown-country states are non-mask icons instead, with the same
glyph pre-tinted black for a light bar and white for a dark bar (the ``dark``
parameter, refreshed from the existing appearance probe) plus the unchanged
coloured dot. The flag state is full colour and unchanged.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
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

# The glyph is drawn in one colour: pure black for the template (macOS keeps
# only alpha and tints it), black/white pre-tinted for the badged states.
_GLYPH_BLACK = QColor(0, 0, 0)
_GLYPH_WHITE = QColor(255, 255, 255)

_cache: dict[tuple, QIcon] = {}
_pix_cache: dict[tuple, QPixmap] = {}


def system_is_dark() -> bool:
    """Best-effort dark-appearance probe via the app palette.

    The menu bar follows the system appearance and the app theme follows dark
    mode too, so the palette's lightness is a cheap proxy. Anything unknown
    (no app yet) is light; the template glyph works on both anyway and the
    badged states are redrawn once the app exists.
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


def _needs_dark(state: str, code: str | None) -> bool:
    # Only the badged (non-template) states bake the bar colour in: the glyph
    # is pre-tinted black/white because a mask cannot carry the coloured dot.
    # The template glyph and the full-colour flags read on both bars as drawn.
    if state == "connecting":
        return True
    return state == "connected" and code is None


def tray_pixmap(state: str, country_code: str | None = None, dark: bool = False) -> QPixmap:
    """The tray image at logical 22pt, device pixels = 22 * dpr, DPR set on it."""
    code = geo_exit.normalize(country_code)
    if state not in ("disconnected", "connecting", "connected"):
        state = "disconnected"
    # Only the connected flag varies by country; the other states always show
    # the glyph (with or without a badge), so they share one cache entry.
    if state != "connected":
        code = None
    if not _needs_dark(state, code):
        dark = False
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
        _paint_flag(p, code, dark)
    elif state == "disconnected":
        _paint_glyph(p, _GLYPH_BLACK, detail="full")
    else:
        _paint_glyph(p, _GLYPH_WHITE if dark else _GLYPH_BLACK, detail="full")
        if state == "connected":
            _paint_dot(p, _CONNECTED_DOT)
        elif state == "connecting":
            _paint_dot(p, _CONNECTING_DOT)
    p.end()
    _pix_cache[key] = pix
    return pix


def _paint_flag(p: QPainter, code: str, dark: bool) -> None:
    renderer = QSvgRenderer(str(geo_exit.flag_path(code)))
    if not renderer.isValid():
        # A flag that cannot be drawn must never be blank: fall back to the
        # glyph with the connected badge instead of a wrong/empty icon.
        _paint_glyph(p, _GLYPH_WHITE if dark else _GLYPH_BLACK, detail="full")
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


def _paint_glyph(p: QPainter, color: QColor, detail: str = "full") -> None:
    """Simplified monochrome mascot: round sushi roll + chopsticks.

    Drawn in one opaque colour on transparency (a template when black). The
    roll is a bold ring on the 22pt grid (2+pt strokes survive @1x, curves are
    snapped so they don't blur); ``detail`` picks the interior: "full" keeps
    the brain|circuit split when legible, "split" only the centre line, and
    "plain" the silhouette alone. Production always uses "full".
    """
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.NoBrush)

    def stroke(width: float) -> None:
        pen = QPen(color)
        pen.setWidthF(width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

    # Chopsticks behind the roll: two parallel round-cap sticks reaching for
    # the top-right corner, the signature of the app tile.
    stroke(1.7)
    p.drawLine(QPointF(13.5, 8.5), QPointF(18.0, 1.2))
    p.drawLine(QPointF(15.6, 9.2), QPointF(20.2, 2.0))

    # Nori ring: the bold silhouette that reads even at 1x.
    stroke(2.2 if detail == "full" else 2.6)
    p.drawEllipse(QRectF(2.8, 7.7, 14.4, 11.6))

    if detail == "plain":
        return
    # Rice split: the brain|circuit centre line.
    stroke(1.3)
    p.drawLine(QPointF(10.0, 8.6), QPointF(10.0, 18.6))
    if detail == "split":
        return

    # Brain half (left): two sulcus squiggles, same 1.2pt round style.
    stroke(1.2)
    brain1 = QPainterPath(QPointF(8.6, 10.4))
    brain1.cubicTo(QPointF(6.6, 10.8), QPointF(6.4, 12.4), QPointF(8.0, 13.0))
    p.drawPath(brain1)
    brain2 = QPainterPath(QPointF(8.6, 16.6))
    brain2.cubicTo(QPointF(6.8, 16.2), QPointF(6.4, 14.8), QPointF(7.8, 14.2))
    p.drawPath(brain2)

    # Circuit half (right): three nodes joined in a triangle, like the tile.
    stroke(1.0)
    a, b, c = QPointF(12.4, 10.6), QPointF(12.4, 16.4), QPointF(14.9, 13.5)
    p.drawLine(a, b)
    p.drawLine(a, c)
    p.drawLine(b, c)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(color))
    for node in (a, b, c):
        p.drawEllipse(QRectF(node.x() - 1.15, node.y() - 1.15, 2.3, 2.3))


def _paint_dot(p: QPainter, color: QColor) -> None:
    # Bottom-right badge with a contrasting ring so it reads on either bar.
    cx, cy = _TRAY_PT - 1 - _DOT_R, _TRAY_PT - 1 - _DOT_R
    p.setPen(QPen(QColor(255, 255, 255, 230)))
    p.setBrush(QBrush(color))
    p.drawEllipse(QRectF(cx - _DOT_R, cy - _DOT_R, _DOT_R * 2, _DOT_R * 2))


def tray_icon(state: str, country_code: str | None = None, dark: bool = False) -> QIcon:
    """Cached tray QIcon for (state, country, appearance).

    Disconnected is a real macOS template image (mask: macOS tints it black on
    a light bar, white on a dark bar, including the pressed state). The badged
    states and flags are full colour (a mask would eat the dot/flag), with the
    glyph pre-tinted per appearance where needed.
    """
    pix = tray_pixmap(state, country_code, dark)
    if state not in ("disconnected", "connecting", "connected"):
        state = "disconnected"
    mask = state == "disconnected"
    key = (pix.cacheKey(), mask)
    icon = _cache.get(key)
    if icon is None:
        icon = QIcon(pix)
        icon.setIsMask(mask)
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
