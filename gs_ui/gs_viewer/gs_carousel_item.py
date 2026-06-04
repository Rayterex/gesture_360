"""Single card in the 360-video carousel."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QLinearGradient,
    QPainter, QPen, QPixmap,
)
from PySide6.QtWidgets import QGraphicsItem

from gs_core.gs_qt.gs_node import GsNode

CARD_W = 560
CARD_H = 315


class GsCarouselItem(QGraphicsItem):
    BASE_W = CARD_W
    BASE_H = CARD_H

    def __init__(self, node: GsNode, parent=None):
        super().__init__(parent)
        self.node        = node
        self._pixmap: QPixmap | None = None
        self._is_centre  = False
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)

    def set_thumbnail(self, qimage: QImage) -> None:
        self._pixmap = QPixmap.fromImage(qimage)
        self.update()

    def set_centre(self, val: bool) -> None:
        if self._is_centre != val:
            self._is_centre = val
            self.update()

    def boundingRect(self) -> QRectF:
        m = 2
        return QRectF(
            -self.BASE_W / 2 - m, -self.BASE_H / 2 - m,
             self.BASE_W + m * 2,  self.BASE_H + m * 2,
        )

    def _card_rect(self) -> QRectF:
        return QRectF(-self.BASE_W / 2, -self.BASE_H / 2, self.BASE_W, self.BASE_H)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        r = self._card_rect()

        painter.fillRect(r, QBrush(QColor("#0d0d1a")))

        if self._pixmap:
            painter.drawPixmap(r.toRect(), self._pixmap)
        else:
            # placeholder gradient while thumbnail loads
            grad = QLinearGradient(r.topLeft(), r.bottomRight())
            grad.setColorAt(0.0, QColor("#0f0f22"))
            grad.setColorAt(1.0, QColor("#1a1a35"))
            painter.fillRect(r, grad)
            painter.setPen(QPen(QColor("#2a2a4a")))
            painter.setFont(QFont("Sans", 11))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, "360°")

        # dim non-centre cards
        if not self._is_centre:
            painter.fillRect(r, QColor(0, 0, 10, 110))

        # border — highlight centre card
        pen_color = "#3a6ac0" if self._is_centre else "#1e1e32"
        painter.setPen(QPen(QColor(pen_color), 1.5 if self._is_centre else 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(r)

        # label
        lbl_h = 32
        lbl_r = QRectF(r.left(), r.bottom() - lbl_h, r.width(), lbl_h)
        grad  = QLinearGradient(0, lbl_r.top(), 0, lbl_r.bottom())
        grad.setColorAt(0.0, QColor(0, 0, 15, 0))
        grad.setColorAt(1.0, QColor(0, 0, 15, 220))
        painter.fillRect(lbl_r, grad)

        font = QFont("Segoe UI", 10 if self._is_centre else 8)
        font.setWeight(QFont.Weight.Medium if self._is_centre else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor("#ffffff" if self._is_centre else "#999999"))
        painter.drawText(lbl_r, Qt.AlignmentFlag.AlignCenter, self.node.name)
