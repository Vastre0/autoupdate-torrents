"""Фоновые задачи, чтобы интерфейс не подвисал на сети."""

from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QThread, pyqtSignal


class UpdateWorker(QThread):
    """Обновление всех раздач в отдельном потоке."""

    log = pyqtSignal(str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, action: Callable[[Callable[[str], None]], Any], parent=None):
        super().__init__(parent)
        self._action = action

    def run(self) -> None:  # noqa: D102 - Qt
        try:
            result = self._action(self.log.emit)
        except Exception as error:  # noqa: BLE001 - показываем пользователю текст ошибки
            self.failed.emit(str(error))
            return
        self.finished_ok.emit(result)


class TaskWorker(QThread):
    """Произвольная короткая задача (проверка PAC, qBittorrent и т. п.)."""

    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, action: Callable[[], Any], parent=None):
        super().__init__(parent)
        self._action = action

    def run(self) -> None:  # noqa: D102 - Qt
        try:
            result = self._action()
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error))
            return
        self.finished_ok.emit(result)
