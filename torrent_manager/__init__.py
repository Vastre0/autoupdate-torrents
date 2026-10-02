"""autoupdate-torrents — автообновление торрентов с rutracker.

Порт под Linux (CachyOS/Arch) с встроенным обходом блокировок
(PAC-скрипты Антизапрета, тот же принцип, что и в расширении
«Обход блокировок Рунета» для Firefox).
"""

from __future__ import annotations

__all__ = ["__version__", "APP_NAME", "APP_TITLE"]

APP_NAME = "autoupdate-torrents"
APP_TITLE = "Torrent Manager"
__version__ = "2.0.0"
