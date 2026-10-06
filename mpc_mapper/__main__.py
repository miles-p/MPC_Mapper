import sys

from PySide6.QtWidgets import QApplication

from .gui.main_window import MainWindow


def main() -> int:
    if sys.platform == "win32":
        # Own taskbar entry/icon instead of being grouped under python.exe.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MPCMapper.MPCMapper")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("MPC Mapper")
    app.setStyle("Fusion")
    w = MainWindow()
    w.resize(1450, 950)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
