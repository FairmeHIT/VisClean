from __future__ import annotations

import sys

def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
        from app.ui.main_window import MainWindow
    except ImportError as exc:
        print("Missing runtime dependency:", exc)
        print("Install the requirements from requirements.txt and run on Windows with Microsoft PowerPoint installed.")
        return 1

    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
