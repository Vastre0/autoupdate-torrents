"""Тесты приложения. Запуск: ``python -m unittest discover -v``."""

from __future__ import annotations

import os
import sys

# Чтобы тесты видели пакет torrent_manager при запуске из любого каталога.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
