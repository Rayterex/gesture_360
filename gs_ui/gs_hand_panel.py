"""Gesture control side-panel — camera preview + tracker controls."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame, QLabel, QPushButton, QSizePolicy, QSlider,
    QVBoxLayout, QWidget,
)

from gs_core.gs_qt.gs_hand_tracker import GsHandTracker, MEDIAPIPE_OK


class GsHandPanel(QWidget):
    """
    Relays gesture signals upward:
      swipe_left / swipe_right  →  navigate carousel
      fist_changed(bool)        →  notify main window
      look_delta(dyaw, dpitch)  →  pan/tilt 360 viewer
    """
    swipe_left   = Signal()
    swipe_right  = Signal()
    fist_changed = Signal(bool)
    look_delta   = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#0e0e1c;")
        self._tracker: GsHandTracker | None = None

        # ── camera preview ───────────────────────────────────────────────
        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._preview.setFixedHeight(168)
        self._preview.setStyleSheet(
            "background:#080814; border:1px solid #1e1e30; border-radius:4px;")
        self._preview.setText("Camera preview")

        # ── gesture mode indicator ───────────────────────────────────────
        self._mode_lbl = QLabel("")
        self._mode_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mode_lbl.setStyleSheet(
            "color:#e05010; font-size:13px; font-weight:bold; padding:2px;")

        self._swipe_lbl = QLabel("")
        self._swipe_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._swipe_lbl.setStyleSheet(
            "color:#2a7de1; font-size:16px; font-weight:bold; padding:2px;")

        self._status = QLabel("Ready")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("color:#888; font-size:10px; padding:4px;")
        self._status.setWordWrap(True)

        # ── start/stop button ────────────────────────────────────────────
        self._btn = QPushButton("▶  Start gesture control")
        self._btn.setStyleSheet(
            "QPushButton { background:#1a3060; color:#7ab4ff; border:1px solid #2a4080;"
            " border-radius:4px; font-size:11px; padding:6px; }"
            "QPushButton:hover { background:#1e3870; color:#fff; }"
            "QPushButton:checked { background:#0d1e40; color:#5580cc; }")
        self._btn.setCheckable(True)
        self._btn.clicked.connect(self._toggle)

        # ── swipe sensitivity slider ─────────────────────────────────────
        sens_lbl = QLabel("Swipe sensitivity")
        sens_lbl.setStyleSheet("color:#666; font-size:10px; padding:4px 4px 0;")
        self._sens = QSlider(Qt.Orientation.Horizontal)
        self._sens.setRange(5, 30)
        self._sens.setValue(11)
        self._sens.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sens.setToolTip("Wrist travel (% of frame) to trigger a swipe")
        self._sens.setStyleSheet(self._slider_style())
        self._sens.valueChanged.connect(self._on_sens_changed)

        # ── look sensitivity slider ───────────────────────────────────────
        look_lbl = QLabel("Look sensitivity (fist mode)")
        look_lbl.setStyleSheet("color:#666; font-size:10px; padding:4px 4px 0;")
        self._look = QSlider(Qt.Orientation.Horizontal)
        self._look.setRange(30, 300)
        self._look.setValue(120)
        self._look.setCursor(Qt.CursorShape.PointingHandCursor)
        self._look.setToolTip("Multiplier for 360° look when fist is closed")
        self._look.setStyleSheet(self._slider_style())
        self._look.valueChanged.connect(self._on_look_changed)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#1a1a2a;")

        if not MEDIAPIPE_OK:
            warn = QLabel("⚠  mediapipe not found\npip install mediapipe")
            warn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            warn.setStyleSheet(
                "color:#e07010; font-size:10px; background:#1a0e00;"
                " border:1px solid #503010; border-radius:4px; padding:6px;")
        else:
            warn = None

        instr = QLabel(
            "Hand open + swipe  →  switch video\n"
            "Fist closed + move  →  look around 360°"
        )
        instr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instr.setStyleSheet("color:#555; font-size:10px; padding:6px 4px;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        if warn:
            lay.addWidget(warn)
        lay.addWidget(self._preview)
        lay.addWidget(self._mode_lbl)
        lay.addWidget(self._swipe_lbl)
        lay.addWidget(self._status)
        lay.addWidget(sep)
        lay.addWidget(self._btn)
        lay.addWidget(sens_lbl)
        lay.addWidget(self._sens)
        lay.addWidget(look_lbl)
        lay.addWidget(self._look)
        lay.addWidget(instr)
        lay.addStretch()

    # ------------------------------------------------------------------
    @staticmethod
    def _slider_style() -> str:
        return (
            "QSlider::groove:horizontal { background:#1e1e2e; height:6px;"
            "  border-radius:3px; margin:0 4px; }"
            "QSlider::handle:horizontal { background:#2a7de1; width:16px; height:16px;"
            "  margin:-5px 0; border-radius:8px; }"
            "QSlider::sub-page:horizontal { background:#2a4080; border-radius:3px; }"
        )

    def _toggle(self, checked: bool) -> None:
        if checked:
            self._start()
        else:
            self._stop()

    def _start(self) -> None:
        if self._tracker and self._tracker.isRunning():
            return
        self._btn.setText("■  Stop gesture control")
        self._status.setText("Starting camera…")
        self._tracker = GsHandTracker(source=0)
        self._tracker.frame_ready.connect(self._on_frame)
        self._tracker.status.connect(self._status.setText)
        self._tracker.swipe_left.connect(self._on_swipe_left)
        self._tracker.swipe_right.connect(self._on_swipe_right)
        self._tracker.fist_changed.connect(self._on_fist_changed)
        self._tracker.look_delta.connect(self.look_delta.emit)
        self._tracker.start()

    def _stop(self) -> None:
        self._btn.setText("▶  Start gesture control")
        if self._tracker:
            self._tracker.stop()
            self._tracker = None
        self._preview.setText("Camera preview")
        self._status.setText("Stopped")
        self._swipe_lbl.setText("")
        self._mode_lbl.setText("")

    # ------------------------------------------------------------------
    @Slot(QImage)
    def _on_frame(self, img: QImage) -> None:
        w, h = self._preview.width(), self._preview.height()
        if w > 0 and h > 0:
            scaled = img.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            self._preview.setPixmap(QPixmap.fromImage(scaled))
        if self._tracker:
            self._tracker.mark_consumed()

    @Slot()
    def _on_swipe_left(self) -> None:
        self._swipe_lbl.setText("◄  previous")
        self.swipe_left.emit()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(700, lambda: self._swipe_lbl.setText(""))

    @Slot()
    def _on_swipe_right(self) -> None:
        self._swipe_lbl.setText("next  ►")
        self.swipe_right.emit()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(700, lambda: self._swipe_lbl.setText(""))

    @Slot(bool)
    def _on_fist_changed(self, closed: bool) -> None:
        self._mode_lbl.setText("✊  LOOK MODE" if closed else "")
        self.fist_changed.emit(closed)

    def _on_sens_changed(self, val: int) -> None:
        if self._tracker:
            self._tracker.set_swipe_dist(val / 100.0)

    def _on_look_changed(self, val: int) -> None:
        if self._tracker:
            self._tracker.set_look_scale(float(val))

    def stop_tracker(self) -> None:
        if self._tracker:
            self._tracker.stop()
