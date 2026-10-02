"""Интеграция с рабочим столом CachyOS/Arch: автозапуск и systemd-таймер."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths

DESKTOP_FILE_NAME = "autoupdate-torrents.desktop"
SERVICE_NAME = "autoupdate-torrents.service"
TIMER_NAME = "autoupdate-torrents.timer"

DESKTOP_TEMPLATE = """[Desktop Entry]
Type=Application
Name=Torrent Manager
Comment=Автообновление торрентов с rutracker (с обходом блокировок)
Exec={exec_cmd}
Icon={icon}
Terminal=false
Categories=Network;FileTransfer;Qt;
Keywords=torrent;rutracker;qBittorrent;
StartupWMClass=Torrent Manager
"""

SERVICE_TEMPLATE = """[Unit]
Description=Обновление раздач rutracker в qBittorrent
Documentation=file://{config_dir}
After=network-online.target

[Service]
Type=oneshot
ExecStart={exec_cmd} --update
# Работает и без графической сессии:
Environment=QT_QPA_PLATFORM=offscreen
Nice=10
"""

TIMER_TEMPLATE = """[Unit]
Description=Периодическое обновление раздач rutracker

[Timer]
OnBootSec=5min
OnCalendar={calendar}
Persistent=true
RandomizedDelaySec=30min

[Install]
WantedBy=timers.target
"""


def _default_exec_cmd() -> str:
    """Команда запуска приложения (venv/ launcher или python -m)."""
    launcher = Path.home() / ".local/bin/autoupdate-torrents"
    if launcher.is_file():
        return str(launcher)
    if shutil.which("autoupdate-torrents"):
        return shutil.which("autoupdate-torrents")  # type: ignore[return-value]
    return f"{sys.executable} -m torrent_manager"


def icon_name() -> str:
    return "autoupdate-torrents"


# ------------------------------------------------------------------ XDG autostart


def autostart_path() -> Path:
    return paths.autostart_dir() / DESKTOP_FILE_NAME


def is_autostart_enabled() -> bool:
    return autostart_path().is_file()


def set_autostart(enabled: bool, exec_cmd: str | None = None) -> Path | None:
    """Включает/выключает автозапуск при входе в сессию (XDG autostart)."""
    target = autostart_path()
    if not enabled:
        target.unlink(missing_ok=True)
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    content = DESKTOP_TEMPLATE.format(
        exec_cmd=exec_cmd or _default_exec_cmd(),
        icon=icon_name(),
    )
    target.write_text(content, encoding="utf-8")
    target.chmod(0o644)
    return target


# ----------------------------------------------------------------- systemd timer


def systemd_user_dir() -> Path:
    return paths.systemd_user_dir()


def install_systemd_units(exec_cmd: str | None = None, calendar: str = "*-*-* 04:30:00") -> tuple[Path, Path]:
    """Создаёт unit-файлы пользовательского таймера systemd."""
    directory = systemd_user_dir()
    directory.mkdir(parents=True, exist_ok=True)
    command = exec_cmd or _default_exec_cmd()

    service_path = directory / SERVICE_NAME
    timer_path = directory / TIMER_NAME
    service_path.write_text(
        SERVICE_TEMPLATE.format(exec_cmd=command, config_dir=paths.config_dir()),
        encoding="utf-8",
    )
    timer_path.write_text(TIMER_TEMPLATE.format(calendar=calendar), encoding="utf-8")
    return service_path, timer_path


def systemd_available() -> bool:
    return shutil.which("systemctl") is not None


def _systemctl(*args: str) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            env={**os.environ, "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")},
        )
    except (OSError, subprocess.SubprocessError) as error:
        return 1, str(error)
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode, output


def enable_systemd_timer() -> tuple[bool, str]:
    """Включает и запускает таймер; возвращает ``(успех, сообщение)``."""
    if not systemd_available():
        return False, "systemd не найден — таймер можно включить вручную."
    code, output = _systemctl("daemon-reload")
    if code != 0:
        return False, f"systemctl daemon-reload: {output}"
    code, output = _systemctl("enable", "--now", TIMER_NAME)
    if code != 0:
        return False, f"systemctl enable --now {TIMER_NAME}: {output}"
    return True, "Таймер systemd включён (systemctl --user list-timers)."


def disable_systemd_timer() -> tuple[bool, str]:
    if not systemd_available():
        return False, "systemd не найден."
    _systemctl("disable", "--now", TIMER_NAME)
    return True, "Таймер systemd выключен."


def timer_status() -> str:
    """Краткий статус таймера для интерфейса."""
    if not systemd_available():
        return "systemd недоступен"
    if not (systemd_user_dir() / TIMER_NAME).is_file():
        return "таймер не установлен"
    code, output = _systemctl("is-active", TIMER_NAME)
    return "активен" if code == 0 and output.strip() == "active" else f"не активен ({output.strip()})"
