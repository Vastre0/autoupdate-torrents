import sys
import os
import json
from datetime import datetime
from typing import Optional

import rutt_to_qb

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QMessageBox,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QCheckBox,
    QToolButton
)
from PyQt6.QtGui import QGuiApplication, QFont, QCloseEvent
from PyQt6.QtCore import Qt, pyqtSlot


def load_stylesheet(filename: str) -> str:
    """Загружает файл стилей и возвращает его содержимое."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Warning: Stylesheet file not found: {filename}")
        return ""


class TorrentApp(QMainWindow):
    USER_CONFIG_FILE = 'user-config.json'
    LOG_TRUNCATE_LENGTH = 100
    DEFAULT_USER_CONFIG = {
        'theme': 'light',
        'logs_expanded': True,
        'window_geometry': {'x': 100, 'y': 100, 'width': 800, 'height': 700}
    }

    def __init__(self):
        super().__init__()
        self.selected_path = ""
        self.config = self._load_user_config()
        self.init_ui()
        self.apply_theme()
        self.load_and_display_torrents()
        self.log_message("Приложение запущено.")

    # --- UI Construction ---

    def init_ui(self):
        """Инициализирует и собирает пользовательский интерфейс из секций."""
        self._setup_main_window()
        main_layout = QVBoxLayout()
        main_layout.addLayout(self._create_add_torrent_section())
        main_layout.addWidget(self._create_separator())
        main_layout.addLayout(self._create_torrent_list_section())
        main_layout.addLayout(self._create_log_section())
        main_layout.addLayout(self._create_status_bar())
        main_layout.setStretchFactor(main_layout.itemAt(2).layout(), 1)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

    def _setup_main_window(self):
        """Настраивает основные параметры главного окна."""
        self.setWindowTitle("Torrent Manager")
        geometry = self.config.get('window_geometry')
        self.setGeometry(geometry['x'], geometry['y'], geometry['width'], geometry['height'])

    def _create_add_torrent_section(self) -> QVBoxLayout:
        """Создает верхнюю секцию для добавления торрентов."""
        layout = QVBoxLayout()
        layout.addWidget(QLabel("<b>Добавить новый торрент для отслеживания:</b>"))
        url_layout = QHBoxLayout()
        self.url_entry = self._create_line_edit(placeholder="https://rutracker.org/forum/viewtopic.php?t=...")
        url_layout.addWidget(QLabel("Ссылка:"))
        url_layout.addWidget(self.url_entry)
        url_layout.addWidget(self._create_button("📋", "Вставить из буфера обмена", self.paste_from_clipboard, 40))
        layout.addLayout(url_layout)

        path_layout = QHBoxLayout()
        self.path_label = self._create_line_edit("Папка не выбрана", read_only=True)
        path_layout.addWidget(QLabel("Папка:"))
        path_layout.addWidget(self.path_label)
        path_layout.addWidget(self._create_button("...", "Выбрать папку для сохранения", self.pick_folder, 40))
        layout.addLayout(path_layout)
        layout.addWidget(self._create_button("Добавить в отслеживание", on_click=self.add_action))
        return layout

    def _create_torrent_list_section(self) -> QVBoxLayout:
        """Создает центральную секцию со списком торрентов и кнопками управления."""
        layout = QVBoxLayout()
        layout.addWidget(QLabel("<b>Отслеживаемые торренты:</b>"))
        self.torrent_list_widget = QTreeWidget()
        self.torrent_list_widget.setColumnCount(3)
        self.torrent_list_widget.setHeaderLabels(["Название", "ID", "Путь сохранения"])
        self.torrent_list_widget.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.torrent_list_widget.itemSelectionChanged.connect(self.on_torrent_selection_change)
        layout.addWidget(self.torrent_list_widget)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self._create_button("Обновить список", on_click=self.load_and_display_torrents))
        btn_layout.addWidget(self._create_button("Обновить все торренты", on_click=self.update_action))
        self.delete_btn = self._create_button("Удалить выбранный", on_click=self.delete_selected_torrent, enabled=False)
        btn_layout.addWidget(self.delete_btn)
        layout.addLayout(btn_layout)
        return layout

    def _create_log_section(self) -> QVBoxLayout:
        """Создает нижнюю сворачиваемую секцию для логов."""
        layout = QVBoxLayout()
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 5, 0, 5)
        is_expanded = self.config.get('logs_expanded', True)
        self.log_toggle_btn = QToolButton(checkable=True, checked=is_expanded)
        self.log_toggle_btn.setStyleSheet("QToolButton { border: none; }")
        self.log_toggle_btn.clicked.connect(self.toggle_log_visibility)
        header_layout.addWidget(self.log_toggle_btn)
        header_layout.addWidget(QLabel("<b>Логи</b>"))
        header_layout.addStretch()
        layout.addLayout(header_layout)

        self.log_widget = QTreeWidget(visible=is_expanded)
        self.log_widget.setColumnCount(2)
        self.log_widget.setHeaderLabels(["Время", "Сообщение"])
        self.log_widget.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.log_widget)
        self.update_log_toggle_button()
        return layout

    def _create_status_bar(self) -> QHBoxLayout:
        """Создает нижнюю строку с кнопкой переключения темы."""
        layout = QHBoxLayout()
        self.theme_btn = self._create_button("", on_click=self.toggle_theme)
        layout.addStretch()
        layout.addWidget(self.theme_btn)
        return layout

    def _create_separator(self) -> QWidget:
        """Создает виджет-разделитель."""
        separator = QWidget(objectName="separatorLine")
        separator.setFixedHeight(1)
        return separator

    # --- UI Helpers ---

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

    # --- Configuration and Theming ---

    def apply_theme(self):
        """Применяет выбранную тему, загружая ее из файла."""
        is_dark = self.config.get('theme') == 'dark'
        stylesheet_path = 'styles/dark.qss' if is_dark else 'styles/light.qss'
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
        """Переключает тему и сохраняет выбор."""
        self.config['theme'] = 'light' if self.config.get('theme') == 'dark' else 'dark'
        self._save_user_config()
        self.apply_theme()

    def _load_user_config(self) -> dict:
        """Загружает или создает пользовательский конфиг."""
        if not os.path.exists(self.USER_CONFIG_FILE):
            self._save_user_config(self.DEFAULT_USER_CONFIG)
            return self.DEFAULT_USER_CONFIG.copy()
        try:
            with open(self.USER_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # Дополняем конфиг ключами по умолчанию, если их нет
            for key, value in self.DEFAULT_USER_CONFIG.items():
                config.setdefault(key, value)
            return config
        except (json.JSONDecodeError, TypeError):
            self._save_user_config(self.DEFAULT_USER_CONFIG)
            return self.DEFAULT_USER_CONFIG.copy()

    def _save_user_config(self, config_data: Optional[dict] = None):
        """Сохраняет пользовательский конфиг."""
        data_to_save = config_data if config_data is not None else self.config
        with open(self.USER_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4)

    # --- Event Handlers and Slots ---

    def closeEvent(self, event: QCloseEvent):
        """Перехватывает событие закрытия окна для сохранения настроек."""
        geometry = self.geometry()
        self.config['window_geometry'] = {
            'x': geometry.x(), 'y': geometry.y(),
            'width': geometry.width(), 'height': geometry.height()
        }
        self._save_user_config()
        super().closeEvent(event)

    @pyqtSlot()
    def on_torrent_selection_change(self):
        """Активирует/деактивирует кнопку удаления при выборе элемента в списке."""
        self.delete_btn.setEnabled(bool(self.torrent_list_widget.selectedItems()))

    @pyqtSlot()
    def toggle_log_visibility(self):
        """Скрывает/показывает виджет логов и сохраняет состояние."""
        is_visible = self.log_toggle_btn.isChecked()
        self.log_widget.setVisible(is_visible)
        self.update_log_toggle_button()
        self.config['logs_expanded'] = is_visible
        self._save_user_config()

    def update_log_toggle_button(self):
        """Обновляет иконку и подсказку на кнопке сворачивания логов."""
        arrow = Qt.ArrowType.DownArrow if self.log_toggle_btn.isChecked() else Qt.ArrowType.RightArrow
        tooltip = "Свернуть логи" if self.log_toggle_btn.isChecked() else "Развернуть логи"
        self.log_toggle_btn.setArrowType(arrow)
        self.log_toggle_btn.setToolTip(tooltip)

    @pyqtSlot()
    def paste_from_clipboard(self):
        """Вставляет текст из буфера обмена в поле URL."""
        self.url_entry.setText(QGuiApplication.clipboard().text())

    @pyqtSlot()
    def pick_folder(self):
        """Открывает диалог выбора папки."""
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите папку")
        if folder_path:
            self.selected_path = folder_path
            self.path_label.setText(folder_path)
            self.log_message(f"Выбрана папка: {folder_path}")

    # --- Core Logic Methods ---

    def log_message(self, message: str):
        """Добавляет сообщение в виджет логов, сворачивая длинные сообщения."""
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
        """Загружает торренты из конфига и отображает их в списке."""
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
        """Обрабатывает нажатие кнопки 'Добавить в отслеживание'."""
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
        """Обрабатывает удаление выбранного торрента."""
        selected_item = self.torrent_list_widget.currentItem()
        if not selected_item: return

        torrent_id = selected_item.data(1, Qt.ItemDataRole.UserRole)
        torrent_name = selected_item.text(0)

        confirmed, delete_files = self._show_delete_confirmation_dialog(torrent_name, torrent_id)
        if not confirmed:
            return

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
        """Показывает диалог подтверждения удаления. Возвращает (confirmed, delete_files)."""
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setWindowTitle("Подтверждение удаления")
        msg_box.setText(f"Вы уверены, что хотите удалить торрент '{name}' (ID: {torrent_id})?")
        msg_box.setInformativeText("Это действие удалит торрент из списка отслеживания и из qBittorrent клиента.")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        cb = QCheckBox("Удалить скачанные файлы с диска")
        msg_box.setCheckBox(cb)

        if msg_box.exec() == QMessageBox.StandardButton.Yes:
            return True, cb.isChecked()
        return False, False

    @pyqtSlot()
    def update_action(self):
        """Запускает обновление всех торрентов из конфига."""
        self.log_message("Запуск обновления всех торрентов...")
        try:
            rutt_to_qb.update_torrents(self.log_message)
            QMessageBox.information(self, "Успех", "Обновление торрентов завершено!")
        except Exception as e:
            self.log_message(f"Критическая ошибка при обновлении: {e}")
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    QApplication.setApplicationName("Torrent Manager")
    window = TorrentApp()
    window.show()
    sys.exit(app.exec())