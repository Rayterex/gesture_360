"""
MediaPipe hand tracker with two gesture modes:

  Fist OPEN  — swipe detection (discrete left/right events) → navigate carousel
  Fist CLOSED — look detection (continuous dx/dy signal) → pan/tilt 360 viewer

Swipe model (fist open)
────────────────────────
A reference wrist position anchors when the hand first appears or after each
completed swipe.  When |dx| or |dy| ≥ _SWIPE_DIST a swipe fires and the
reference advances to the current position, so continuous sweeping fires
repeated events.

Look model (fist closed)
────────────────────────
Each frame we emit look_delta(dyaw, dpitch) where:
    dyaw   = (wrist_x − prev_x) * _LOOK_SCALE   (degrees, rightward +)
    dpitch = (wrist_y − prev_y) * _LOOK_SCALE    (degrees, downward  +)

The 360 viewer applies these directly as yaw/pitch increments.

Signals
───────
swipe_left, swipe_right  — navigate carousel left / right
fist_changed(bool)       — True = fist closed, False = open
look_delta(float, float) — (dyaw, dpitch) continuous look input while fist closed
frame_ready(QImage)      — annotated camera frame for the panel preview
status(str)              — human-readable status
"""
from __future__ import annotations

import threading
import time

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

try:
    import mediapipe as mp
    _MP_HANDS  = mp.solutions.hands
    _MP_DRAW   = mp.solutions.drawing_utils
    MEDIAPIPE_OK = True
except ImportError:
    MEDIAPIPE_OK = False

# ── Thresholds ────────────────────────────────────────────────────────────
_SWIPE_DIST  = 0.11    # normalized wrist movement to trigger one swipe step
_COOLDOWN    = 0.45    # seconds between swipe events
_FIST_CONFIRM = 5      # consecutive frames needed to confirm state change
_LOOK_SCALE  = 120.0   # normalized hand delta → yaw/pitch degrees


def _detect_fist(landmarks) -> bool:
    tips = [8, 12, 16, 20]
    mcps = [5,  9, 13, 17]
    curled = sum(1 for t, m in zip(tips, mcps) if landmarks[t].y > landmarks[m].y)
    return curled >= 3


class GsHandTracker(QThread):
    swipe_left   = Signal()
    swipe_right  = Signal()
    fist_changed = Signal(bool)          # True = fist closed
    look_delta   = Signal(float, float)  # (dyaw_deg, dpitch_deg) while fist closed
    frame_ready  = Signal(QImage)
    status       = Signal(str)

    def __init__(self, source: int = 0, parent=None):
        super().__init__(parent)
        self._source   = source
        self._stop_evt = threading.Event()
        self._consumed = threading.Event()
        self._consumed.set()

    # ------------------------------------------------------------------
    def run(self) -> None:
        if not MEDIAPIPE_OK:
            self.status.emit("mediapipe not installed — pip install mediapipe")
            return

        cap = cv2.VideoCapture(self._source)
        if not cap.isOpened():
            self.status.emit(f"Cannot open camera {self._source}")
            return

        self.status.emit("Camera ready — show your hand")

        # swipe state
        ref_x: float | None = None
        ref_y: float | None = None
        last_swipe: float   = 0.0

        # look state
        look_ref_x: float | None = None
        look_ref_y: float | None = None

        # fist debounce
        fist_state  = False
        fist_frames = 0
        open_frames = 0

        with _MP_HANDS.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.55,
            min_tracking_confidence=0.55,
        ) as hands:
            while not self._stop_evt.is_set():
                ok, bgr = cap.read()
                if not ok:
                    time.sleep(0.04)
                    continue

                bgr = cv2.flip(bgr, 1)
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                res = hands.process(rgb)
                now = time.time()

                if res.multi_hand_landmarks:
                    lm = res.multi_hand_landmarks[0]

                    _MP_DRAW.draw_landmarks(
                        bgr, lm, _MP_HANDS.HAND_CONNECTIONS,
                        _MP_DRAW.DrawingSpec(color=(60, 120, 255), thickness=2, circle_radius=4),
                        _MP_DRAW.DrawingSpec(color=(60, 230, 120), thickness=2),
                    )

                    wrist_x = lm.landmark[0].x
                    wrist_y = lm.landmark[0].y

                    # ── fist state machine ───────────────────────────────
                    if _detect_fist(lm.landmark):
                        fist_frames += 1
                        open_frames  = 0
                        if fist_frames == _FIST_CONFIRM and not fist_state:
                            fist_state = True
                            look_ref_x = wrist_x
                            look_ref_y = wrist_y
                            self.fist_changed.emit(True)
                    else:
                        open_frames  += 1
                        fist_frames   = 0
                        if open_frames == _FIST_CONFIRM and fist_state:
                            fist_state = False
                            look_ref_x = None
                            look_ref_y = None
                            self.fist_changed.emit(False)

                    if fist_state:
                        # ── look mode: emit per-frame pan/tilt delta ─────
                        if look_ref_x is not None:
                            dyaw   = (wrist_x - look_ref_x) * _LOOK_SCALE
                            dpitch = (wrist_y - look_ref_y) * _LOOK_SCALE
                            self.look_delta.emit(dyaw, dpitch)
                        look_ref_x = wrist_x
                        look_ref_y = wrist_y
                        self._draw_label(bgr, "✊ LOOK", (0, 180, 255))
                    else:
                        # ── swipe mode: discrete navigation ──────────────
                        if ref_x is None: ref_x = wrist_x
                        if ref_y is None: ref_y = wrist_y

                        dx = wrist_x - ref_x
                        dy = wrist_y - ref_y

                        if (now - last_swipe) > _COOLDOWN:
                            if abs(dx) >= _SWIPE_DIST or abs(dy) >= _SWIPE_DIST:
                                if abs(dx) >= abs(dy):
                                    if dx < 0:
                                        self.swipe_left.emit()
                                        self._draw_label(bgr, "◄◄◄", (0, 230, 230))
                                    else:
                                        self.swipe_right.emit()
                                        self._draw_label(bgr, "►►►", (0, 230, 230))
                                last_swipe = now
                                ref_x = wrist_x
                                ref_y = wrist_y
                else:
                    # hand gone — reset all state
                    ref_x = ref_y = None
                    look_ref_x = look_ref_y = None
                    fist_frames = open_frames = 0
                    if fist_state:
                        fist_state = False
                        self.fist_changed.emit(False)

                # emit annotated frame
                if self._consumed.is_set():
                    h, w = bgr.shape[:2]
                    rgb2 = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                    self._consumed.clear()
                    self.frame_ready.emit(
                        QImage(rgb2.data.tobytes(), w, h, w * 3,
                               QImage.Format.Format_RGB888)
                    )

        cap.release()
        self.status.emit("Camera stopped")

    # ------------------------------------------------------------------
    def _draw_label(self, frame: np.ndarray, text: str, color: tuple) -> None:
        h, w = frame.shape[:2]
        cv2.putText(frame, text,
                    (w // 2 - 90, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.8,
                    color, 3, cv2.LINE_AA)

    def mark_consumed(self) -> None:
        self._consumed.set()

    def stop(self) -> None:
        self._stop_evt.set()
        self.wait(3000)

    def set_swipe_dist(self, val: float) -> None:
        global _SWIPE_DIST
        _SWIPE_DIST = val

    def set_look_scale(self, val: float) -> None:
        global _LOOK_SCALE
        _LOOK_SCALE = val
