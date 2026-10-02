"""Куки rutracker.org: хранение, импорт из строки браузера, проверка."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

from . import paths
from .jsonstore import atomic_write_json, read_json

REQUIRED_COOKIE = "bb_session"

HELP_TEXT = """Как получить куки:

1. Войдите в аккаунт на https://rutracker.org в браузере.
2. Откройте инструменты разработчика (F12) → вкладка «Сеть» (Network).
3. Обновите страницу (F5), найдите запрос к rutracker.org (viewtopic.php или index.php).
4. В разделе Request Headers найдите строку Cookie: и скопируйте её целиком.
5. Вставьте строку в приложение кнопкой «Импорт куки» — она сохранится в
   ~/.config/autoupdate-torrents/cookies.json.

Куки со временем истекают: если обновление перестало работать — повторите шаги.
"""


def cookies_path() -> Path:
    """Путь к файлу куки (XDG-каталог, с учётом старой раскладки)."""
    return paths.resolve_data_file(paths.COOKIES_FILE)


def parse_cookie_string(text: str) -> dict[str, str]:
    """Разбирает строку ``name=value; name2=value2`` (или JSON) в словарь.

    Понимает формат строки Cookie из DevTools, JSON-объект и многострочный
    список ``name=value``.
    """
    text = (text or "").strip()
    if not text:
        return {}

    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if v is not None}

    cookies: dict[str, str] = {}
    for chunk in text.replace("\n", ";").split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        name, value = name.strip(), value.strip()
        if name:
            cookies[name] = value
    return cookies


def validate_cookies(cookies: dict[str, str] | None) -> list[str]:
    """Возвращает список замечаний к набору куки (пустой — всё в порядке)."""
    problems: list[str] = []
    if not cookies or not isinstance(cookies, dict):
        return ["Файл куки пуст или имеет неверный формат."]
    if REQUIRED_COOKIE not in cookies:
        problems.append(
            f"В куки нет обязательной пары «{REQUIRED_COOKIE}» — авторизация не сработает."
        )
    for name, value in cookies.items():
        if not str(value).strip():
            problems.append(f"Пустое значение у куки «{name}».")
    return problems


def save_cookies(cookies: dict[str, str], path: str | Path | None = None) -> Path:
    """Сохраняет куки в файл (права 600)."""
    target = Path(path) if path else cookies_path()
    atomic_write_json(target, dict(cookies))
    return target


def load_cookies(
    path: str | Path | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, str] | None:
    """Читает куки из файла; ``None`` — если файл отсутствует или повреждён."""

    def _log(message: str) -> None:
        if log:
            log(message)

    target = Path(path) if path else cookies_path()
    if not target.is_file():
        _log(f"Файл куки не найден: {target}")
        return None

    data = read_json(target, default=None)
    if not isinstance(data, dict):
        _log(f"Файл куки повреждён или пуст: {target}")
        return None

    cookies = {str(k): str(v) for k, v in data.items()}
    for problem in validate_cookies(cookies):
        _log(f"Куки: {problem}")
    return cookies


def has_cookies(path: str | Path | None = None) -> bool:
    """Есть ли на диске непустой файл куки."""
    target = Path(path) if path else cookies_path()
    data = read_json(target, default=None)
    return isinstance(data, dict) and bool(data)


def cookies_from_legacy_sources(candidates: Iterable[Path]) -> dict[str, str] | None:
    """Пытается найти куки в переданных файлах (совместимость со старой версией)."""
    for candidate in candidates:
        data = read_json(candidate, default=None)
        if isinstance(data, dict) and data:
            return {str(k): str(v) for k, v in data.items()}
    return None
