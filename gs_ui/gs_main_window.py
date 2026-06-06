"""Main application window for Gesture 360."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QSplitter, QStatusBar, QVBoxLayout, QWidget,
)

from gs_core.gs_qt.gs_node import GsNode
from gs_ui.gs_hand_panel import GsHandPanel
from gs_ui.gs_viewer.gs_360_viewer import Gs360ViewerWidget
from gs_ui.gs_viewer.gs_carousel_view import GsCarouselView

# Root of the repository — gs_assets lives here
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ASSETS_DIR = _REPO_ROOT / "gs_assets"

_HDR_STYLE = "background:#0d0d1a; border-bottom:1px solid #1a1a2e;"
_BTN_BASE  = (
    "QPushButton {{ background:{bg}; color:{fg};"
    " border:1px solid {border}; border-radius:4px;"
    " font-size:11px; font-weight:500; padding:5px 14px; }}"
    "QPushButton:hover {{ background:#1e3870; color:#fff; border-color:#2a7de1; }}"
)


def _btn(text: str, active: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setStyleSheet(_BTN_BASE.format(
        bg="#1a3060"  if active else "#151525",
        fg="#7ab4ff"  if active else "#888899",
        border="#2a4080" if active else "#252535",
    ))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class GsMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gesture 360")
        self.resize(1440, 900)
        self.setStyleSheet("QMainWindow { background:#0a0a15; }")

        self._nodes: list[GsNode] = []

        # ── widgets ──────────────────────────────────────────────────────
        self._viewer   = Gs360ViewerWidget()
        self._carousel = GsCarouselView()
        self._hand     = GsHandPanel()

        # ── header toolbar ───────────────────────────────────────────────
        self._btn_reset = _btn("⊙  Reset view")
        self._btn_reset.clicked.connect(self._viewer.reset_view)

        title = QLabel("GESTURE  360")
        title.setStyleSheet(
            "color:#2a7de1; font-size:12px; font-weight:bold; letter-spacing:3px;")

        toolbar = QWidget()
        toolbar.setStyleSheet(_HDR_STYLE)
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(12, 6, 12, 6)
        tl.setSpacing(10)
        tl.addWidget(title)
        tl.addStretch()
        tl.addWidget(self._btn_reset)

        # ── status bar ───────────────────────────────────────────────────
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color:#666; font-size:11px; padding:0 8px;")
        status = QStatusBar()
        status.setStyleSheet(
            "QStatusBar { background:#080810; border-top:1px solid #141424; }")
        status.addPermanentWidget(self._status_lbl)
        self.setStatusBar(status)

        # ── right column: viewer (top) + carousel (bottom) ───────────────
        right_split = QSplitter(Qt.Orientation.Vertical)
        right_split.addWidget(self._viewer)
        right_split.addWidget(self._carousel)
        right_split.setSizes([580, 280])
        right_split.setStyleSheet(
            "QSplitter::handle { background:#1a1a2a; height:2px; }")

        # ── body: hand panel (left) + viewer+carousel (right) ────────────
        body_split = QSplitter(Qt.Orientation.Horizontal)
        body_split.addWidget(self._hand)
        body_split.addWidget(right_split)
        body_split.setSizes([240, 1200])
        body_split.setStyleSheet(
            "QSplitter::handle { background:#1a1a2a; width:1px; }")

        root = QWidget()
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(toolbar)
        rl.addWidget(body_split, 1)
        self.setCentralWidget(root)

        # ── connections ──────────────────────────────────────────────────
        self._carousel.centre_changed.connect(self._on_centre_changed)
        self._viewer.status_changed.connect(self._status_lbl.setText)

        # gesture → carousel navigation
        self._hand.swipe_left.connect(self._carousel.navigate_left)
        self._hand.swipe_right.connect(self._carousel.navigate_right)

        # look_delta → 360 viewer pan/tilt
        self._hand.look_delta.connect(self._viewer.apply_look_delta)

        # keyboard shortcuts
        QShortcut(QKeySequence(Qt.Key.Key_Left),  self, self._carousel.navigate_left)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, self._carousel.navigate_right)
        QShortcut(QKeySequence("R"), self, self._viewer.reset_view)

        QTimer.singleShot(0, self._load_assets)

    # ------------------------------------------------------------------
    @Slot()
    def _load_assets(self) -> None:
        paths = sorted(_ASSETS_DIR.glob("*.mp4"))
        self._nodes = [GsNode(p.stem, str(p)) for p in paths]
        if not self._nodes:
            self._status_lbl.setText(
                f"No MP4 files found in {_ASSETS_DIR} — copy 360 videos there.")
            return
        self._carousel.set_nodes(self._nodes)

    @Slot(object)
    def _on_centre_changed(self, node: GsNode) -> None:
        self._viewer.reset_view()
        self._viewer.set_video_path(node.path)
        self._status_lbl.setText(
            f"▶  {node.name}   |   ← → keys · scroll · drag carousel   "
            f"|   hand open=swipe  fist=look"
        )

    def closeEvent(self, e) -> None:
        self._hand.stop_tracker()
        self._viewer.stop_stream()
        super().closeEvent(e)
