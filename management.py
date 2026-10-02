#!/usr/bin/env python3
"""Точка входа приложения (совместимость со старой версией).

Запускает графический интерфейс, а с ключами — режимы CLI::

    ./management.py                 # графический интерфейс
    ./management.py --update        # разовое обновление (для systemd-таймера)
    ./management.py --check         # диагностика
    ./management.py --help          # все возможности
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from torrent_manager.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
