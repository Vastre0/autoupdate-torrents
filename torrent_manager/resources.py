"""Доступ к ресурсам пакета (иконки, стили)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def resource_path(relative: str) -> str:
    """Абсолютный путь к ресурсу (работает и из PyInstaller-сборки)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, relative)
    package_dir = Path(__file__).resolve().parent
    candidate = package_dir / relative
    if candidate.exists():
        return str(candidate)
    # Ресурсы в корне репозитория (совместимость со старой раскладкой).
    return str(package_dir.parent / relative)


def icon_path() -> str:
    for name in ("data/icon.png", "data/icon.ico", "icon.png", "icon.ico"):
        path = resource_path(name)
        if os.path.exists(path):
            return path
    return ""


def stylesheet_path(dark: bool) -> str:
    name = "data/styles/dark.qss" if dark else "data/styles/light.qss"
    path = resource_path(name)
    if os.path.exists(path):
        return path
    return resource_path("styles/dark.qss" if dark else "styles/light.qss")


def load_stylesheet(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""
