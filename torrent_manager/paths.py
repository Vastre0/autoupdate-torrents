"""Пути приложения.

Под Linux (CachyOS/Arch) данные хранятся в XDG-каталогах:

* конфиги  — ``~/.config/autoupdate-torrents``
* кэш      — ``~/.cache/autoupdate-torrents``
* данные   — ``~/.local/share/autoupdate-torrents``

Сохраняется совместимость со старой раскладкой: если файл
(``cookies.json``, ``torrent_config.json``, ``user-config.json``) лежит
рядом со скриптами, он будет найден и при первом запуске скопирован
в XDG-каталог. Переменная окружения ``AUTOUPDATE_TORRENTS_HOME``
позволяет задать общий базовый каталог (используется в тестах).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

APP_DIR_NAME = "autoupdate-torrents"

COOKIES_FILE = "cookies.json"
TORRENT_CONFIG_FILE = "torrent_config.json"
USER_CONFIG_FILE = "user-config.json"

_ENV_HOME = "AUTOUPDATE_TORRENTS_HOME"
_ENV_LEGACY = "AUTOUPDATE_TORRENTS_LEGACY_DIR"

_LEGACY_FILES = (COOKIES_FILE, TORRENT_CONFIG_FILE, USER_CONFIG_FILE)


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if not value:
        return None
    return Path(value).expanduser()


def _xdg_dir(env_var: str, fallback: str) -> Path:
    """Каталог приложения внутри XDG-каталога (или AUTOUPDATE_TORRENTS_HOME)."""
    override = _env_path(_ENV_HOME)
    if override is not None:
        return override

    base = _env_path(env_var)
    if base is None:
        base = Path.home() / fallback
    return base / APP_DIR_NAME


def config_dir() -> Path:
    """Каталог конфигурации."""
    return _xdg_dir("XDG_CONFIG_HOME", ".config")


def cache_dir() -> Path:
    """Каталог кэша (в частности, скачанные PAC-скрипты)."""
    return _xdg_dir("XDG_CACHE_HOME", ".cache")


def data_dir() -> Path:
    """Каталог данных (venv, служебные файлы)."""
    return _xdg_dir("XDG_DATA_HOME", ".local/share")


def autostart_dir() -> Path:
    """Каталог XDG-autostart."""
    override = _env_path(_ENV_HOME)
    if override is not None:
        return override / "autostart"
    base = _env_path("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return base / "autostart"


def systemd_user_dir() -> Path:
    """Каталог пользовательских unit-файлов systemd."""
    override = _env_path(_ENV_HOME)
    if override is not None:
        return override / "systemd" / "user"
    base = _env_path("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return base / "systemd" / "user"


def legacy_dirs() -> list[Path]:
    """Каталоги, где могли остаться файлы старой (Windows/портативной) версии.

    Если задан ``AUTOUPDATE_TORRENTS_LEGACY_DIR``, поиск ведётся только в нём
    (используется в тестах и при переносе данных вручную).
    """
    override = _env_path(_ENV_LEGACY)
    if override is not None:
        return [override.resolve()]

    dirs: list[Path] = []
    dirs.append(Path.cwd())
    # Каталог репозитория/установки: <repo>/torrent_manager/paths.py -> <repo>
    dirs.append(Path(__file__).resolve().parent.parent)
    unique: list[Path] = []
    for path in dirs:
        resolved = path.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def ensure_dirs() -> None:
    """Создаёт каталоги конфигов и кэша."""
    for directory in (config_dir(), cache_dir(), data_dir()):
        directory.mkdir(parents=True, exist_ok=True)


def resolve_data_file(name: str, migrate: bool = True) -> Path:
    """Возвращает путь к файлу данных.

    Приоритет: XDG-каталог → старая раскладка (с копированием в XDG) →
    новый файл в XDG-каталоге.
    """
    target = config_dir() / name
    if target.exists():
        return target

    for directory in legacy_dirs():
        legacy = directory / name
        if legacy.is_file():
            if migrate:
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(legacy, target)
                    return target
                except OSError:
                    return legacy
            return legacy

    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def migrate_legacy_files() -> list[tuple[Path, Path]]:
    """Копирует все найденные файлы старой версии в XDG-каталог.

    Возвращает список пар (откуда, куда) для успешных копирований.
    """
    moved: list[tuple[Path, Path]] = []
    config_dir().mkdir(parents=True, exist_ok=True)
    for name in _LEGACY_FILES:
        target = config_dir() / name
        if target.exists():
            continue
        for directory in legacy_dirs():
            legacy = directory / name
            if legacy.is_file():
                try:
                    shutil.copy2(legacy, target)
                except OSError:
                    continue
                moved.append((legacy, target))
                break
    return moved
