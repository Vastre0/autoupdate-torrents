"""Конфигурация пользователя (``user-config.json``) с XDG-путями."""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

from . import paths
from .jsonstore import atomic_write_json, read_json


class ConfigManager:
    """Чтение и запись пользовательских настроек.

    Недостающие ключи берутся из :attr:`DEFAULTS`, поэтому обновление
    версии приложения не ломает существующий конфиг.
    """

    FILENAME = paths.USER_CONFIG_FILE

    DEFAULTS: dict[str, Any] = {
        "theme": "light",
        "logs_expanded": True,
        "window_geometry": {"x": 100, "y": 100, "width": 900, "height": 700},
        "minimize_to_tray": True,
        "close_to_tray": True,
        "show_tray_notifications": True,
        "torrent_columns_width": [300, 100, 400],
        "autostart": False,
        "qbittorrent": {
            "host": "localhost:8080",
            "username": "admin",
            "password": "adminadmin",
            "use_https": False,
        },
        "bypass": {
            # Встроенный обход блокировок: разбор PAC-скрипта Антизапрета
            # (то же решение, что использует расширение «Обход блокировок Рунета»).
            "enabled": True,
            "pac_urls": [
                "https://antizapret.prostovpn.org:8443/proxy.pac",
                "https://antizapret.prostovpn.org:18443/proxy.pac",
                "https://antizapret.prostovpn.org/proxy.pac",
                "https://e.cen.rodeo:8443/proxy.pac",
            ],
            "pac_cache_ttl_hours": 12,
            "prefer_https_proxy": True,
            # Ручной прокси (например, socks5://127.0.0.1:9050 для Tor) —
            # используется, если PAC недоступен или обход выключен.
            "manual_proxy": "",
            # Проверять IP-адреса хостов по спискам PAC (медленнее, но точнее).
            "dns_check": True,
        },
    }

    def __init__(self, path: str | Path | None = None):
        self._lock = threading.RLock()
        self.path = Path(path) if path else paths.resolve_data_file(self.FILENAME)
        self.config = self._load()

    # ------------------------------------------------------------------ загрузка
    def _load(self) -> dict[str, Any]:
        data = read_json(self.path, default=None)
        if not isinstance(data, dict):
            defaults = copy.deepcopy(self.DEFAULTS)
            self._write(defaults)
            return defaults
        return self._merge(copy.deepcopy(self.DEFAULTS), data)

    @classmethod
    def _merge(cls, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        for key, value in override.items():
            if key not in base:
                base[key] = value
            elif isinstance(base[key], dict) and isinstance(value, dict):
                cls._merge(base[key], value)
            else:
                base[key] = value
        return base

    def _write(self, data: dict[str, Any]) -> None:
        atomic_write_json(self.path, data)

    # ------------------------------------------------------------------- доступ
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self.config[key] = value

    def update(self, values: dict[str, Any]) -> None:
        with self._lock:
            self._merge(self.config, values)

    def get_section(self, key: str) -> dict[str, Any]:
        """Возвращает словарь-секцию (для настроек qBittorrent/обхода)."""
        with self._lock:
            section = self.config.get(key)
            if not isinstance(section, dict):
                section = copy.deepcopy(self.DEFAULTS.get(key, {}))
                self.config[key] = section
            return copy.deepcopy(section)

    def set_section(self, key: str, values: dict[str, Any]) -> None:
        with self._lock:
            section = self.config.get(key)
            if not isinstance(section, dict):
                section = copy.deepcopy(self.DEFAULTS.get(key, {}))
                self.config[key] = section
            self._merge(section, values)

    def save(self) -> None:
        with self._lock:
            self._write(self.config)
