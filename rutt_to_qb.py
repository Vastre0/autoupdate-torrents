"""Совместимость со старым API модуля ``rutt_to_qb``.

Вся логика переехала в пакет :mod:`torrent_manager`; этот модуль оставлен,
чтобы старые скрипты и привычные вызовы продолжали работать.
"""

from __future__ import annotations

import sys
from typing import Any, Callable

from torrent_manager import paths
from torrent_manager.bypass import BypassManager
from torrent_manager.config import ConfigManager
from torrent_manager.cookies import load_cookies as _load_cookies
from torrent_manager.cookies import save_cookies as _save_cookies
from torrent_manager.service import TorrentService
from torrent_manager.torrent_store import TorrentStore
from torrent_manager.torrents import (
    QBittorrentClient,
    RutrackerClient,
    extract_torrent_id,
    topic_url,
)

# Имена файлов (на диске лежат в ~/.config/autoupdate-torrents)
COOKIES_FILE = paths.COOKIES_FILE
CONFIG_FILE = paths.TORRENT_CONFIG_FILE

# Значения по умолчанию (переопределяются в user-config.json)
QB_HOST = "localhost:8080"
QB_USERNAME = "admin"
QB_PASSWORD = "adminadmin"

NBSP = "\u00a0"

_notified = False


def _notify() -> None:
    global _notified
    if not _notified:
        print(
            "rutt_to_qb: модуль оставлен для совместимости, "
            "используйте torrent_manager.* (подробности: --help).",
            file=sys.stderr,
        )
        _notified = True


def _service(log_func: Callable[[str], None] | None = None) -> TorrentService:
    _notify()
    return TorrentService(config=ConfigManager(), log=log_func)


def load_cookies(log_func: Callable[[str], None] | None = None) -> dict[str, str] | None:
    """Читает куки из XDG-каталога (или из старой раскладки)."""
    return _load_cookies(log=log_func)


def save_cookies(cookies: dict[str, str]) -> None:
    _save_cookies(cookies)


def load_config(log_func: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Возвращает ``{"torrents": {...}}`` — совместимо со старым форматом."""
    store = TorrentStore(log=log_func)
    return {"torrents": store.items()}


def save_config(config: dict[str, Any]) -> None:
    store = TorrentStore()
    store.data = {"torrents": dict(config.get("torrents", {}))}
    store.save()


def add_torrent_from_url(topic_url_: str, save_path: str, log_func: Callable[[str], None] | None = None) -> None:
    _service(log_func).add_torrent(topic_url_, save_path)


def download_torrent(topic_id: str, log_func: Callable[[str], None] | None = None):
    """Скачивает .torrent и возвращает ``(содержимое, ссылка)``."""
    service = _service(log_func)
    return service._rutracker().download_torrent(str(topic_id))  # noqa: SLF001 - совместимость


def add_to_qbittorrent(
    torrent_content: bytes,
    save_path: str,
    original_url: str,
    log_func: Callable[[str], None] | None = None,
) -> bool:
    service = _service(log_func)
    return service.qbittorrent().add_torrent(torrent_content, save_path, comment=original_url)


def update_torrents(log_func: Callable[[str], None] | None = None) -> None:
    _service(log_func).update_all()


def delete_torrent(topic_id: str, delete_files: bool, log_func: Callable[[str], None] | None = None) -> bool:
    return _service(log_func).remove_torrent(str(topic_id), delete_files=delete_files)


__all__ = [
    "COOKIES_FILE",
    "CONFIG_FILE",
    "QB_HOST",
    "QB_USERNAME",
    "QB_PASSWORD",
    "BypassManager",
    "QBittorrentClient",
    "RutrackerClient",
    "extract_torrent_id",
    "topic_url",
    "load_cookies",
    "save_cookies",
    "load_config",
    "save_config",
    "add_torrent_from_url",
    "download_torrent",
    "add_to_qbittorrent",
    "update_torrents",
    "delete_torrent",
]
