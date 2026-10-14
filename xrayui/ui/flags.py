"""Country flags as crisp, rounded pixmaps, rendered once per size.

The bundled 4x3 SVGs are drawn with QSvgRenderer straight at the screen's
device pixel ratio, so they stay sharp on HiDPI; a hairline edge keeps white
flags (Japan, Finland) from dissolving into a light background.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ..core import geo_exit

FLAG_W, FLAG_H = 20, 15
_RADIUS = 3.0

# Every country × size × screen-scale pixmap is a few KB; ~250 countries still
# fit easily, but the cache must not grow without bound over a long session
# (each new monitor scale used to add entries forever).
_FLAG_CACHE_SIZE = 256


def _device_ratio() -> float:
    screen = QGuiApplication.primaryScreen()
    return screen.devicePixelRatio() if screen else 1.0


@lru_cache(maxsize=_FLAG_CACHE_SIZE)
def _render(code: str, width: int, height: int, dpr: float) -> QPixmap | None:
    renderer = QSvgRenderer(str(geo_exit.flag_path(code)))
    if not renderer.isValid():
        return None
    pix = QPixmap(round(width * dpr), round(height * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    rect = QRectF(0, 0, width, height)
    clip = QPainterPath()
    clip.addRoundedRect(rect, _RADIUS, _RADIUS)
    p.setClipPath(clip)
    renderer.render(p, rect)
    p.setClipping(False)
    edge = QPen(QColor(0, 0, 0, 46))
    edge.setWidthF(1.0)
    p.setPen(edge)
    p.setBrush(Qt.NoBrush)
    inset = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    p.drawRoundedRect(inset, _RADIUS - 0.5, _RADIUS - 0.5)
    p.end()
    return pix


@lru_cache(maxsize=_FLAG_CACHE_SIZE)
def _render_icon(code: str, width: int, height: int, dpr: float) -> QIcon | None:
    pix = _render(code, width, height, dpr)
    return QIcon(pix) if pix is not None else None


def flag_pixmap(code: str | None, width: int = FLAG_W, height: int = FLAG_H) -> QPixmap | None:
    code = geo_exit.normalize(code)
    if not code:
        return None
    return _render(code, width, height, _device_ratio())


def flag_icon(code: str | None) -> QIcon | None:
    code = geo_exit.normalize(code)
    if not code:
        return None
    return _render_icon(code, FLAG_W, FLAG_H, _device_ratio())
