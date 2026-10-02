"""Высокоуровневый слой: связывает конфиг, куки, обход блокировок, rutracker и qBittorrent.

Используется и графическим интерфейсом, и CLI (``--update`` для systemd-таймера).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from . import cookies as cookies_mod
from . import paths
from .antizapret import PacError
from .bypass import BypassManager
from .config import ConfigManager
from .torrent_store import TorrentStore
from .torrents import (
    QBittorrentClient,
    QBittorrentError,
    RutrackerClient,
    RutrackerError,
    extract_torrent_id,
    topic_url,
)

LogFunc = Callable[[str], None]


@dataclass
class UpdateResult:
    """Итог обновления всех раздач."""

    updated: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.updated) + len(self.failed) + len(self.skipped)

    def summary(self) -> str:
        return (
            f"Обновлено: {len(self.updated)}, ошибок: {len(self.failed)}, "
            f"пропущено: {len(self.skipped)} (всего {self.total})"
        )

    def ok(self) -> bool:
        return not self.failed


class TorrentService:
    """Прикладная логика приложения."""

    def __init__(
        self,
        config: ConfigManager | None = None,
        log: LogFunc | None = None,
    ):
        self._log_func = log
        self.config = config or ConfigManager()
        self.store = TorrentStore(log=self.log)
        self.bypass = BypassManager(self.config, log=self.log)
        self._cookies: dict[str, str] | None = None
        self._cookies_loaded = False

    # ------------------------------------------------------------------ сервисное
    def log(self, message: str) -> None:
        if self._log_func:
            self._log_func(message)

    @property
    def config_dir(self):
        return paths.config_dir()

    # ----------------------------------------------------------------------- куки
    def cookies(self, reload: bool = False) -> dict[str, str] | None:
        if reload or not self._cookies_loaded:
            self._cookies = cookies_mod.load_cookies(log=self.log)
            self._cookies_loaded = True
        return self._cookies

    def has_cookies(self) -> bool:
        return bool(self.cookies())

    def import_cookies(self, text: str) -> dict[str, str]:
        """Импортирует куки из строки (формат DevTools или JSON)."""
        parsed = cookies_mod.parse_cookie_string(text)
        if not parsed:
            raise ValueError("Не удалось разобрать куки: пустая строка или неизвестный формат.")
        problems = cookies_mod.validate_cookies(parsed)
        path = cookies_mod.save_cookies(parsed)
        self._cookies = parsed
        self._cookies_loaded = True
        for problem in problems:
            self.log(f"Предупреждение: {problem}")
        self.log(f"Куки сохранены: {path}")
        return parsed

    # ------------------------------------------------------------------- обход
    def refresh_pac(self, force: bool = True) -> bool:
        return self.bypass.refresh(force=force)

    def bypass_status(self) -> dict[str, Any]:
        return self.bypass.status()

    def check_host(self, host: str) -> str:
        self.bypass.ensure_loaded(background_refresh=False)
        return self.bypass.describe_host(host)

    # ---------------------------------------------------------------- qBittorrent
    def qbittorrent(self) -> QBittorrentClient:
        return QBittorrentClient(self.config.get_section("qbittorrent"), log=self.log)

    def qbittorrent_test(self) -> tuple[bool, str]:
        return self.qbittorrent().test()

    # ------------------------------------------------------------------- раздачи
    def _rutracker(self) -> RutrackerClient:
        cookies = self.cookies(reload=True)
        if not cookies:
            raise RutrackerError(
                "Не найдены куки rutracker.org.\n" + cookies_mod.HELP_TEXT
            )
        self.bypass.ensure_loaded()
        return RutrackerClient(cookies, bypass=self.bypass, log=self.log)

    def list_tracked(self) -> list[dict[str, Any]]:
        """Список отслеживаемых раздач для интерфейса."""
        result: list[dict[str, Any]] = []
        for topic_id, data in self.store.items().items():
            save_path = str(data.get("save_path", ""))
            result.append(
                {
                    "topic_id": str(topic_id),
                    "save_path": save_path,
                    "url": data.get("url") or topic_url(topic_id),
                    "name": os.path.basename(os.path.normpath(save_path)) if save_path else "—",
                }
            )
        return result

    def add_torrent(self, url: str, save_path: str) -> dict[str, Any]:
        """Добавляет раздачу в список отслеживания."""
        if not url or not url.strip():
            raise ValueError("Не указана ссылка на раздачу.")
        if not save_path:
            raise ValueError("Не указана папка для сохранения.")
        topic_id = extract_torrent_id(url)
        url = url.strip() if url.strip().startswith("http") else topic_url(topic_id)
        is_new = self.store.add(topic_id, save_path, url)
        self.log(
            f"Раздача {topic_id} {'добавлена' if is_new else 'обновлена'} "
            f"(папка: {save_path})."
        )
        return {"topic_id": topic_id, "is_new": is_new, "save_path": save_path, "url": url}

    def remove_torrent(self, topic_id: str, delete_files: bool = False) -> bool:
        """Удаляет раздачу из qBittorrent и из списка отслеживания."""
        topic_id = str(topic_id)
        client = self.qbittorrent()
        try:
            torrent_hash = client.find_hash_by_topic(topic_id)
            if torrent_hash:
                removed = client.delete_torrent(torrent_hash, delete_files)
                self.log(
                    f"Торрент {topic_id} (hash {torrent_hash}) "
                    f"{'удалён из qBittorrent' if removed else 'уже отсутствовал в qBittorrent'}."
                )
            else:
                self.log(f"Торрент {topic_id} не найден в qBittorrent — удаляем только из списка.")
        except QBittorrentError as error:
            self.log(f"{error} Запись из списка всё равно будет удалена.")

        removed_from_store = self.store.remove(topic_id)
        self.log(
            f"Раздача {topic_id} "
            f"{'удалена из списка отслеживания' if removed_from_store else 'отсутствовала в списке'}."
        )
        return removed_from_store

    def update_all(self, progress: LogFunc | None = None) -> UpdateResult:
        """Обновляет все раздачи из списка."""
        report = progress or (lambda message: None)

        def emit(message: str) -> None:
            self.log(message)
            report(message)

        result = UpdateResult()
        torrents = self.store.items()
        if not torrents:
            emit("Список отслеживаемых раздач пуст — обновлять нечего.")
            return result

        client = self._rutracker()
        qb = self.qbittorrent()
        ok, message = qb.test()
        if not ok:
            raise QBittorrentError(message)
        emit(message)

        emit(f"Начинаю обновление {len(torrents)} раздач...")
        for topic_id, settings in torrents.items():
            topic_id = str(topic_id)
            save_path = str(settings.get("save_path", ""))
            emit(f"--- Раздача {topic_id} ---")
            try:
                content, url = client.download_torrent(topic_id)
            except (RutrackerError, PacError) as error:
                emit(f"Не удалось скачать .torrent для {topic_id}: {error}")
                result.failed.append((topic_id, str(error)))
                continue
            try:
                qb.add_torrent(content, save_path, comment=url)
            except QBittorrentError as error:
                emit(f"Не удалось добавить {topic_id} в qBittorrent: {error}")
                result.failed.append((topic_id, str(error)))
                continue
            emit(f"Раздача {topic_id} отправлена на обновление в qBittorrent.")
            result.updated.append(topic_id)

        emit(result.summary())
        return result

    # ------------------------------------------------------------------ диагностика
    def diagnostics(self) -> dict[str, Any]:
        """Проверка готовности приложения (для CLI ``--check`` и GUI)."""
        report: dict[str, Any] = {}

        cookie_data = self.cookies(reload=True)
        report["cookies"] = {
            "ok": bool(cookie_data),
            "path": str(cookies_mod.cookies_path()),
            "problems": cookies_mod.validate_cookies(cookie_data),
        }

        qb_ok, qb_message = self.qbittorrent_test()
        report["qbittorrent"] = {"ok": qb_ok, "message": qb_message}

        bypass_loaded = self.bypass.ensure_loaded(background_refresh=False)
        status = self.bypass_status()
        report["bypass"] = {**status, "ok": bypass_loaded or bool(status.get("manual_proxy"))}

        report["paths"] = {
            "config": str(paths.config_dir()),
            "cache": str(paths.cache_dir()),
            "data": str(paths.data_dir()),
        }

        if cookie_data:
            try:
                client = RutrackerClient(cookie_data, bypass=self.bypass, log=self.log)
                ok, message = client.check_connection()
                report["rutracker"] = {"ok": ok, "message": message}
            except (RutrackerError, PacError) as error:
                report["rutracker"] = {"ok": False, "message": str(error)}
        else:
            report["rutracker"] = {"ok": False, "message": "нет куки"}
        return report
