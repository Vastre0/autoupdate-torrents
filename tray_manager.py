import sys
import os
from typing import Optional

from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QStyle
from PyQt6.QtGui import QIcon, QAction


class TrayManager:
    def __init__(self, window):
        self.window = window
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self._tray_message_shown = False

        # Трей доступен на Windows и если системный трей вообще доступен
        self.is_enabled = sys.platform.startswith('win') and QSystemTrayIcon.isSystemTrayAvailable()

        if self.is_enabled:
            self._init_tray()

    def _init_tray(self):
        """Инициализация иконки и меню системного трея."""
        if os.path.exists("icon.ico"):
            app_icon = QIcon("icon.ico")
        else:
            app_icon = self.window.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

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

        act_theme = menu.addAction("Переключить тему")
        act_theme.triggered.connect(self.window.toggle_theme)

        menu.addSeparator()
        act_exit = menu.addAction("Выход")
        act_exit.triggered.connect(self.window.exit_app)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def hide_to_tray(self, reason: str = "Приложение свернуто в трей"):
        """Спрятать окно в трей и показать уведомление (если включено)."""
        if not self.is_enabled or not self.tray_icon:
            return
        self.window.hide()
        if self.window.config.get('show_tray_notifications', True) and not self._tray_message_shown:
            try:
                self.tray_icon.showMessage("Torrent Manager", reason,
                                           QSystemTrayIcon.MessageIcon.Information, 2500)
                self._tray_message_shown = True
            except Exception:
                pass

    def restore_from_tray(self):
        """Восстановить окно из трея."""
        self.window.showNormal()
        self.window.activateWindow()
        self.window.raise_()

    def on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """Обработчик клика по иконке трея: левый клик/даблклик — открыть."""
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.restore_from_tray()

    def hide(self):
        if self.tray_icon:
            self.tray_icon.hide()