"""Уведомления рабочего стола (libnotify/notify-send)."""

from __future__ import annotations

import shutil
import subprocess

DEFAULT_TITLE = "Torrent Manager"


def notify(message: str, title: str = DEFAULT_TITLE, timeout_ms: int = 6000) -> bool:
    """Показывает уведомление; возвращает ``False``, если notifier недоступен."""
    if not shutil.which("notify-send"):
        return False
    try:
        subprocess.run(
            ["notify-send", "--app-name", title, "--expire-time", str(timeout_ms), title, message],
            check=False,
            timeout=10,
            capture_output=True,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
