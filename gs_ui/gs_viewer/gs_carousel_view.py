"""
Animated carousel for 360-video selection.

The middle card is largest (scale 1.0); cards fan out to the sides with
decreasing scale, drop offset, and opacity — like pages of a book.
A floating-point visual centre drives all layout properties simultaneously
during navigation so there is no snapping.
"""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QEasingCurve, QRectF, QThread, QTimer, QTimeLine, Qt, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QSizePolicy

from gs_core.gs_qt.gs_node import GsNode
from gs_ui.gs_viewer.gs_carousel_item import GsCarouselItem, CARD_W, CARD_H

# ── Layout table: (scale, drop_px, opacity) indexed by |dist| from centre ─
_LAYOUT = [
    (1.00,   0, 1.00),
    (0.55,  80, 0.80),
    (0.38, 125, 0.58),
    (0.27, 150, 0.36),
    (0.20, 165, 0.22),
]
_GAP     = 190
_ANIM_MS = 420


def _layout_float(dist: float):
    ad  = abs(dist)
    lo  = min(int(ad), len(_LAYOUT) - 1)
    hi  = min(lo + 1,  len(_LAYOUT) - 1)
    t   = ad - int(ad)
    s0, d0, o0 = _LAYOUT[lo]
    s1, d1, o1 = _LAYOUT[hi]
    return (
        s0 + (s1 - s0) * t,
        d0 + (d1 - d0) * t,
        o0 + (o1 - o0) * t,
    )


class _ThumbnailWorker(QThread):
    """Load a single video's first frame as a QImage in a background thread."""
    done = Signal(object, QImage)   # (GsNode, QImage)

    def __init__(self, node: GsNode, parent=None):
        super().__init__(parent)
        self._node = node

    def run(self) -> None:
        cap = cv2.VideoCapture(self._node.path)
        ok, bgr = cap.read()
        cap.release()
        if not ok or bgr is None:
            return
        # scale to card dimensions keeping aspect
        h, w = bgr.shape[:2]
        scale = min(CARD_W / w, CARD_H / h)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        bgr = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)
        # centre-crop to card size
        canvas = np.zeros((CARD_H, CARD_W, 3), dtype=np.uint8)
        y0 = (CARD_H - nh) // 2
        x0 = (CARD_W - nw) // 2
        canvas[y0:y0+nh, x0:x0+nw] = bgr
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        qimg = QImage(rgb.data.tobytes(), CARD_W, CARD_H, CARD_W * 3,
                      QImage.Format.Format_RGB888)
        self.done.emit(self._node, qimg.copy())


class GsCarouselView(QGraphicsView):
    centre_changed = Signal(object)   # GsNode

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("background:#0a0a15; border:none;")
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._items:         list[GsCarouselItem] = []
        self._centre:        int   = 0
        self._visual_centre: float = 0.0
        self._timeline: QTimeLine | None = None
        self._drag_start: float = 0.0
        self._thumb_workers: list[_ThumbnailWorker] = []

    # ── Public API ────────────────────────────────────────────────────────
    def set_nodes(self, nodes: list[GsNode]) -> None:
        self._scene.clear()
        self._items.clear()
        self._centre        = 0
        self._visual_centre = 0.0

        for node in nodes:
            item = GsCarouselItem(node)
            self._scene.addItem(item)
            self._items.append(item)

        self._apply_layout()
        if self._items:
            self.centre_changed.emit(self._items[0].node)

        # kick off thumbnail loading (staggered)
        for i, item in enumerate(self._items):
            QTimer.singleShot(i * 120, lambda n=item.node: self._load_thumb(n))

    def navigate_left(self)  -> None: self._shift(-1)
    def navigate_right(self) -> None: self._shift(+1)

    def centre_node(self) -> GsNode | None:
        return self._items[self._centre].node if self._items else None

    # ── Thumbnails ────────────────────────────────────────────────────────
    def _load_thumb(self, node: GsNode) -> None:
        worker = _ThumbnailWorker(node, parent=self)
        worker.done.connect(self._on_thumb)
        self._thumb_workers.append(worker)
        worker.start()

    def _on_thumb(self, node: GsNode, qimg: QImage) -> None:
        for item in self._items:
            if item.node is node:
                item.set_thumbnail(qimg)
                break

    # ── Layout ────────────────────────────────────────────────────────────
    def _apply_layout(self) -> None:
        max_scale, max_drop, _ = _LAYOUT[-1]
        arc_off = (-CARD_H / 2 + max_drop + CARD_H * max_scale / 2) / 2

        for i, item in enumerate(self._items):
            dist             = float(i) - self._visual_centre
            scale, drop, opacity = _layout_float(dist)
            item.setPos(dist * _GAP, drop - arc_off)
            item.setScale(scale)
            item.setZValue(100.0 - abs(dist) * 10.0)
            item.setOpacity(opacity)
            item.set_centre(abs(dist) < 0.35)

        self._fit_view()

    def _fit_view(self) -> None:
        vr = self.viewport().rect()
        if vr.isEmpty():
            return
        _SIDE = 120
        vis_w = CARD_W + 2 * _SIDE
        vis_h = vis_w * vr.height() / max(vr.width(), 1)
        self.fitInView(
            QRectF(-vis_w / 2, -vis_h / 2, vis_w, vis_h),
            Qt.AspectRatioMode.IgnoreAspectRatio,
        )

    # ── Navigation ────────────────────────────────────────────────────────
    def _shift(self, direction: int) -> None:
        new_centre = self._centre + direction
        if not (0 <= new_centre < len(self._items)):
            return
        self._centre = new_centre
        self._animate_to(float(new_centre))
        self.centre_changed.emit(self._items[self._centre].node)

    def _animate_to(self, target: float) -> None:
        if self._timeline and self._timeline.state() == QTimeLine.State.Running:
            self._timeline.stop()

        start = self._visual_centre
        delta = target - start
        tl    = QTimeLine(_ANIM_MS, self)
        tl.setEasingCurve(QEasingCurve.Type.InOutCubic)
        tl.setUpdateInterval(16)

        def _step(val: float) -> None:
            self._visual_centre = start + delta * val
            self._apply_layout()

        tl.valueChanged.connect(_step)
        self._timeline = tl
        tl.start()

    # ── Background ────────────────────────────────────────────────────────
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0.0, QColor("#0b0b18"))
        grad.setColorAt(1.0, QColor("#06060f"))
        painter.fillRect(rect, grad)

    # ── Input ─────────────────────────────────────────────────────────────
    def keyPressEvent(self, e) -> None:
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_A):
            self.navigate_left()
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_D):
            self.navigate_right()
        else:
            super().keyPressEvent(e)

    def wheelEvent(self, e) -> None:
        if e.angleDelta().y() > 0:
            self.navigate_left()
        else:
            self.navigate_right()

    def mousePressEvent(self, e) -> None:
        self._drag_start = e.position().x()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        delta = e.position().x() - self._drag_start
        if delta > 80:
            self.navigate_left()
        elif delta < -80:
            self.navigate_right()
        super().mouseReleaseEvent(e)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._fit_view()
