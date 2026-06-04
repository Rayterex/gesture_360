"""Gesture 360 — entry point."""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gs_ui.gs_main_window import GsMainWindow


def main() -> None:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = GsMainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
