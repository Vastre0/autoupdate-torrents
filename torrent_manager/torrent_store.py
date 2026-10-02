"""Список отслеживаемых раздач (``torrent_config.json``)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from . import paths
from .jsonstore import atomic_write_json, read_json

LogFunc = Callable[[str], None]


class TorrentStore:
    """Хранилище соответствий «ID раздачи → папка сохранения».

    Структура файла::

        {"torrents": {"123456": {"save_path": "/data/torrents", "url": "..."}}}
    """

    def __init__(self, path: str | Path | None = None, log: LogFunc | None = None):
        self._lock = threading.RLock()
        self.path = Path(path) if path else paths.resolve_data_file(paths.TORRENT_CONFIG_FILE)
        self.data: dict[str, Any] = self._load(log)

    def _load(self, log: LogFunc | None) -> dict[str, Any]:
        data = read_json(self.path, default=None)
        if isinstance(data, dict) and isinstance(data.get("torrents"), dict):
            return data
        if data is not None and log:
            log(f"Файл {self.path.name} повреждён, создаём новый.")
        fresh: dict[str, Any] = {"torrents": {}}
        self._write(fresh)
        return fresh

    def _write(self, data: dict[str, Any]) -> None:
        atomic_write_json(self.path, data)

    def save(self) -> None:
        with self._lock:
            self._write(self.data)

    def items(self) -> dict[str, Any]:
        """Копия словаря отслеживаемых раздач."""
        with self._lock:
            return dict(self.data.get("torrents", {}))

    def get(self, topic_id: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self.data.get("torrents", {}).get(str(topic_id))
            return dict(entry) if isinstance(entry, dict) else None

    def add(self, topic_id: str, save_path: str, url: str) -> bool:
        """Добавляет/обновляет раздачу. ``True`` — запись была новой."""
        with self._lock:
            torrents = self.data.setdefault("torrents", {})
            is_new = str(topic_id) not in torrents
            torrents[str(topic_id)] = {"save_path": save_path, "url": url}
            self._write(self.data)
            return is_new

    def remove(self, topic_id: str) -> bool:
        """Удаляет раздачу из списка. ``True`` — запись существовала."""
        with self._lock:
            torrents = self.data.setdefault("torrents", {})
            existed = torrents.pop(str(topic_id), None) is not None
            if existed:
                self._write(self.data)
            return existed

    def __len__(self) -> int:
        with self._lock:
            return len(self.data.get("torrents", {}))
