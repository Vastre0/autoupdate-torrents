
import os

from datetime import datetime

from utils import load_stylesheet, resource_path

import rutt_to_qb
from utils import load_stylesheet
from config_manager import ConfigManager
from ui_builder import UiBuilder
from tray_manager import TrayManager

from PyQt6.QtWidgets import (
    QMainWindow, QFileDialog, QMessageBox, QTreeWidgetItem,
    QCheckBox, QPushButton, QLineEdit
)
from PyQt6.QtGui import QGuiApplication, QFont, QCloseEvent
from PyQt6.QtCore import Qt, pyqtSlot, QEvent, QTimer


class TorrentApp(QMainWindow):
    LOG_TRUNCATE_LENGTH = 100

    def __init__(self):
        super().__init__()
        self.is_operational = True
        self._check_critical_dependencies()

        self.selected_path = ""
        self._is_quitting = False

        # --- Инициализация компонентов ---
        self.config = ConfigManager()
        self.ui = UiBuilder(self)
        self.tray = TrayManager(self)

        self.ui.setup_ui()
        self.apply_theme()
        self._apply_column_widths()

        if self.is_operational:
            self.load_and_display_torrents()
            self.log_message("Приложение запущено.")
        else:
            error_text = (
                f"<b>КРИТИЧЕСКАЯ ОШИБКА:</b> Файл '{rutt_to_qb.COOKIES_FILE}' не найден.\n"
                "Поместите его в папку с программой. Функционал отключен."
            )
            self.error_label.setText(error_text)
            self.error_label.setVisible(True)
            self.log_message("Приложение запущено с критической ошибкой.")

    def _check_critical_dependencies(self):
        if not os.path.exists(rutt_to_qb.COOKIES_FILE):
            self.is_operational = False

    def _apply_column_widths(self):
        header = self.torrent_list_widget.header()
        widths = self.config.get('torrent_columns_width')
        if len(widths) == 3:
            for i, width in enumerate(widths):
                header.resizeSection(i, width)

    def _setup_main_window(self):
        self.setWindowTitle("Torrent Manager")
        geometry = self.config.get('window_geometry')
        self.setGeometry(geometry['x'], geometry['y'], geometry['width'], geometry['height'])

    # --- Фабричные методы для UI Builder ---
    def _create_button(self, text: str, tooltip: str = None, on_click: callable = None,
                       fixed_width: int = None, enabled: bool = True) -> QPushButton:
        btn = QPushButton(text)
        if tooltip: btn.setToolTip(tooltip)
        if on_click: btn.clicked.connect(on_click)
        if fixed_width: btn.setFixedWidth(fixed_width)
        btn.setEnabled(enabled)
        return btn

    def _create_line_edit(self, text: str = "", placeholder: str = None, read_only: bool = False) -> QLineEdit:
        le = QLineEdit(text)
        if placeholder: le.setPlaceholderText(placeholder)
        le.setReadOnly(read_only)
        return le

    # --- Theming ---
    def apply_theme(self):
        is_dark = self.config.get('theme') == 'dark'
        # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
        stylesheet_path = resource_path('styles/dark.qss' if is_dark else 'styles/light.qss')

        separator_color = "#555" if is_dark else "#cccccc"
        theme_text = "🌞 Светлая тема" if is_dark else "🌙 Тёмная тема"
        theme_tooltip = "Переключиться на светлую тему" if is_dark else "Переключиться на тёмную тему"

        stylesheet = load_stylesheet(stylesheet_path)
        stylesheet += f"\nQWidget#separatorLine {{ background-color: {separator_color}; }}"
        self.setStyleSheet(stylesheet)
        self.theme_btn.setText(theme_text)
        self.theme_btn.setToolTip(theme_tooltip)

    @pyqtSlot()
    def toggle_theme(self):
        self.config.set('theme', 'light' if self.config.get('theme') == 'dark' else 'dark')
        self.apply_theme()
        # Сохранять немедленно не обязательно, сохранится при закрытии

    # --- Event Handlers and Slots ---
    def closeEvent(self, event: QCloseEvent):
        geometry = self.geometry()
        self.config.set('window_geometry', {
            'x': geometry.x(), 'y': geometry.y(),
            'width': geometry.width(), 'height': geometry.height()
        })
        header = self.torrent_list_widget.header()
        self.config.set('torrent_columns_width', [header.sectionSize(i) for i in range(3)])
        self.config.save()

        if self._is_quitting or not self.tray.is_enabled or not self.config.get('close_to_tray'):
            super().closeEvent(event)
            return

        event.ignore()
        self.tray.hide_to_tray("Приложение продолжает работу в трее")

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() == QEvent.Type.WindowStateChange and self.isMinimized() and
                self.tray.is_enabled and self.config.get('minimize_to_tray')):
            QTimer.singleShot(0, lambda: self.tray.hide_to_tray("Приложение свернуто в трей"))

    def exit_app(self):
        self._is_quitting = True
        self.tray.hide()
        self.close()

    @pyqtSlot()
    def on_torrent_selection_change(self):
        is_enabled = self.is_operational and bool(self.torrent_list_widget.selectedItems())
        self.delete_btn.setEnabled(is_enabled)

    @pyqtSlot()
    def toggle_log_visibility(self):
        is_visible = self.log_toggle_btn.isChecked()
        self.log_widget.setVisible(is_visible)
        self.update_log_toggle_button()
        self.config.set('logs_expanded', is_visible)

    def update_log_toggle_button(self):
        arrow = Qt.ArrowType.DownArrow if self.log_toggle_btn.isChecked() else Qt.ArrowType.RightArrow
        tooltip = "Свернуть логи" if self.log_toggle_btn.isChecked() else "Развернуть логи"
        self.log_toggle_btn.setArrowType(arrow)
        self.log_toggle_btn.setToolTip(tooltip)

    @pyqtSlot()
    def paste_from_clipboard(self):
        self.url_entry.setText(QGuiApplication.clipboard().text())

    @pyqtSlot()
    def pick_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите папку")
        if folder_path:
            self.selected_path = folder_path
            self.path_label.setText(folder_path)
            self.log_message(f"Выбрана папка: {folder_path}")

    # --- Core Logic Methods ---
    def log_message(self, message: str):
        timestamp = datetime.now().strftime('%H:%M:%S')
        if len(message) > self.LOG_TRUNCATE_LENGTH:
            short_message = message[:self.LOG_TRUNCATE_LENGTH] + "... (нажмите, чтобы развернуть)"
            parent_item = QTreeWidgetItem(self.log_widget, [timestamp, short_message])
            child_item = QTreeWidgetItem(parent_item, ["", message])
            child_item.setFont(1, QFont("Courier New", 9))
        else:
            QTreeWidgetItem(self.log_widget, [timestamp, message])
        self.log_widget.scrollToBottom()

    @pyqtSlot()
    def load_and_display_torrents(self):
        if not self.is_operational: return
        self.log_message("Загрузка списка отслеживаемых торрентов...")
        self.torrent_list_widget.clear()
        try:
            config = rutt_to_qb.load_config(self.log_message)
            for torrent_id, data in config.get('torrents', {}).items():
                path = data.get('save_path', 'N/A')
                name = os.path.basename(os.path.normpath(path))
                item = QTreeWidgetItem([name, torrent_id, path])
                item.setData(1, Qt.ItemDataRole.UserRole, torrent_id)
                self.torrent_list_widget.addTopLevelItem(item)
            self.log_message(f"Загружено {self.torrent_list_widget.topLevelItemCount()} торрентов.")
        except Exception as e:
            self.log_message(f"Ошибка при загрузке списка торрентов: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить список торрентов: {e}")

    @pyqtSlot()
    def add_action(self):
        url = self.url_entry.text()
        if not url or not self.selected_path:
            QMessageBox.warning(self, "Ошибка", "Необходимо указать ссылку и папку для сохранения.")
            return
        try:
            rutt_to_qb.add_torrent_from_url(url, self.selected_path, self.log_message)
            QMessageBox.information(self, "Успех", "Торрент добавлен в список отслеживания!")
            self.url_entry.clear()
            self.load_and_display_torrents()
        except Exception as e:
            self.log_message(f"Критическая ошибка при добавлении: {e}")
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка: {e}")

    @pyqtSlot()
    def delete_selected_torrent(self):
        selected_item = self.torrent_list_widget.currentItem()
        if not selected_item: return
        torrent_id = selected_item.data(1, Qt.ItemDataRole.UserRole)
        torrent_name = selected_item.text(0)
        confirmed, delete_files = self._show_delete_confirmation_dialog(torrent_name, torrent_id)
        if not confirmed: return
        self.log_message(f"Удаление торрента ID: {torrent_id}. Удаление файлов: {delete_files}")
        try:
            if rutt_to_qb.delete_torrent(torrent_id, delete_files, self.log_message):
                self.log_message(f"Торрент ID: {torrent_id} успешно удален.")
                self.load_and_display_torrents()
            else:
                QMessageBox.warning(self, "Ошибка",
                                    f"Не удалось полностью удалить торрент ID: {torrent_id}. Проверьте логи.")
        except Exception as e:
            self.log_message(f"Критическая ошибка при удалении торрента ID {torrent_id}: {e}")
            QMessageBox.critical(self, "Критическая ошибка", f"Произошла ошибка при удалении: {e}")

    def _show_delete_confirmation_dialog(self, name: str, torrent_id: str) -> tuple[bool, bool]:
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle("Подтверждение удаления")
        msg_box.setText(f"Вы уверены, что хотите удалить торрент '{name}' (ID: {torrent_id})?")
        msg_box.setInformativeText("Это действие удалит торрент из списка отслеживания и из qBittorrent клиента.")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        cb = QCheckBox("Удалить скачанные файлы с диска")
        msg_box.setCheckBox(cb)
        return msg_box.exec() == QMessageBox.StandardButton.Yes, cb.isChecked()

    @pyqtSlot()
    def update_action(self):
        self.log_message("Запуск обновления всех торрентов...")
        try:
            rutt_to_qb.update_torrents(self.log_message)
            QMessageBox.information(self, "Успех", "Обновление торрентов завершено!")
        except Exception as e:
            self.log_message(f"Критическая ошибка при обновлении: {e}")
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка: {e}")