import sys

from PySide6.QtWidgets import QApplication

from .gui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MPC Mapper")
    app.setStyle("Fusion")
    w = MainWindow()
    w.resize(1450, 950)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
