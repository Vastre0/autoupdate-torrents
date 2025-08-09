import sys
from PyQt6.QtWidgets import QApplication
from app_window import TorrentApp

if __name__ == "__main__":
    app = QApplication(sys.argv)
    QApplication.setApplicationName("Torrent Manager")

    window = TorrentApp()
    window.show()

    sys.exit(app.exec())