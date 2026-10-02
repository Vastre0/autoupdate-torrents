"""Запуск графического интерфейса."""

from __future__ import annotations

import sys

from ..config import ConfigManager


def run_gui(config: ConfigManager | None = None) -> int:
    """Создаёт QApplication и показывает главное окно."""
    from PyQt6.QtWidgets import QApplication

    from .. import APP_TITLE
    from ..resources import icon_path
    from .window import TorrentApp

    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationDisplayName(APP_TITLE)
    app.setDesktopFileName("autoupdate-torrents")

    path = icon_path()
    if path:
        from PyQt6.QtGui import QIcon

        app.setWindowIcon(QIcon(path))

    window = TorrentApp(config or ConfigManager())
    window.show()
    return app.exec()
