"""Атомарная запись JSON/текстовых файлов с ограниченными правами доступа."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: str | os.PathLike[str], text: str, mode: int = 0o600) -> None:
    """Записывает текст через временный файл, чтобы не потерять данные при сбое."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_json(path: str | os.PathLike[str], data: Any, mode: int = 0o600) -> None:
    """Записывает JSON (UTF-8, с отступами) атомарно."""
    text = json.dumps(data, indent=4, ensure_ascii=False)
    atomic_write_text(path, text, mode=mode)


def read_json(path: str | os.PathLike[str], default: Any = None) -> Any:
    """Читает JSON; возвращает *default*, если файла нет или он повреждён."""
    target = Path(path)
    if not target.is_file():
        return default
    try:
        with open(target, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
        if not content:
            return default
        return json.loads(content)
    except (json.JSONDecodeError, OSError, ValueError):
        return default
