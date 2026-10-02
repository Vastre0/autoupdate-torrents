"""Системный трей (работает и на Linux: KDE/GNOME/AppIndicator)."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QStyle, QSystemTrayIcon

from ..resources import icon_path


class TrayManager:
    """Иконка в трее с меню управления.

    На CachyOS работает в KDE Plasma (StatusNotifierItem) и в других
    окружениях при установленном libappindicator/поддержке трея.
    """

    def __init__(self, window):
        self.window = window
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self._message_shown = False
        self.is_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.is_enabled = self.is_available
        if self.is_enabled:
            self._init_tray()

    # ------------------------------------------------------------------ создание
    def _app_icon(self) -> QIcon:
        path = icon_path()
        if path:
            icon = QIcon(path)
            if not icon.isNull():
                return icon
        return self.window.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

    def _init_tray(self) -> None:
        app_icon = self._app_icon()
        self.window.setWindowIcon(app_icon)

        self.tray_icon = QSystemTrayIcon(app_icon, self.window)
        self.tray_icon.setToolTip("Torrent Manager")

        menu = QMenu()
        act_open = menu.addAction("Открыть окно")
        act_open.triggered.connect(self.restore_from_tray)

        act_update = QAction("Обновить все торренты", self.window)
        act_update.setEnabled(self.window.is_operational)
        act_update.triggered.connect(self.window.update_action)
        menu.addAction(act_update)

        act_settings = menu.addAction("Настройки…")
        act_settings.triggered.connect(self.window.open_settings)

        act_theme = menu.addAction("Переключить тему")
        act_theme.triggered.connect(self.window.toggle_theme)

        menu.addSeparator()
        act_exit = menu.addAction("Выход")
        act_exit.triggered.connect(self.window.exit_app)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    # -------------------------------------------------------------------- методы
    def hide_to_tray(self, reason: str = "Приложение свернуто в трей") -> None:
        if not self.is_enabled or not self.tray_icon:
            return
        self.window.hide()
        if self.window.config.get("show_tray_notifications", True) and not self._message_shown:
            try:
                self.tray_icon.showMessage(
                    "Torrent Manager", reason, QSystemTrayIcon.MessageIcon.Information, 2500
                )
                self._message_shown = True
            except Exception:  # noqa: BLE001 - уведомления трея не критичны
                pass

    def restore_from_tray(self) -> None:
        self.window.showNormal()
        self.window.activateWindow()
        self.window.raise_()

    def on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.restore_from_tray()

    def hide(self) -> None:
        if self.tray_icon:
            self.tray_icon.hide()
