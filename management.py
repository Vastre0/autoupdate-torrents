import sys
import os
import json
from datetime import datetime
import rutt_to_qb

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog, QMessageBox,
    QTreeWidget, QTreeWidgetItem, QHeaderView
)
from PyQt6.QtGui import QGuiApplication, QFont

# --- Стили для тем ---
DARK_STYLESHEET = """
QWidget {
    background-color: #2b2b2b;
    color: #f0f0f0;
    font-family: Arial;
    font-size: 10pt;
}
QMainWindow {
    background-color: #3c3f41;
}
QLineEdit, QTreeWidget {
    background-color: #3c3f41;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 5px;
}
QPushButton {
    background-color: #555;
    border: 1px solid #666;
    border-radius: 4px;
    padding: 5px 10px;
}
QPushButton:hover {
    background-color: #666;
}
QPushButton:pressed {
    background-color: #777;
}
QHeaderView::section {
    background-color: #444;
    color: #f0f0f0;
    padding: 4px;
    border: 1px solid #555;
}
QMessageBox {
    background-color: #3c3f41;
}
"""

LIGHT_STYLESHEET = """
QWidget {
    background-color: #f0f0f0;
    color: #000000;
    font-family: Arial;
    font-size: 10pt;
}
QMainWindow {
    background-color: #e0e0e0;
}
QLineEdit, QTreeWidget {
    background-color: #ffffff;
    border: 1px solid #ccc;
    border-radius: 4px;
    padding: 5px;
}
QPushButton {
    background-color: #e0e0e0;
    border: 1px solid #bbb;
    border-radius: 4px;
    padding: 5px 10px;
}
QPushButton:hover {
    background-color: #d0d0d0;
}
QPushButton:pressed {
    background-color: #c0c0c0;
}
QHeaderView::section {
    background-color: #e0e0e0;
    padding: 4px;
    border: 1px solid #ccc;
}
"""


class TorrentApp(QMainWindow):
    USER_CONFIG_FILE = 'user-config.json'
    LOG_TRUNCATE_LENGTH = 100  # Длина, после которой лог будет сворачиваться

    def __init__(self):
        super().__init__()
        self.selected_path = ""
        self.config = self.load_user_config()
        self.init_ui()
        self.apply_theme()

    def load_user_config(self):
        """Загружает или создает пользовательский конфиг."""
        if os.path.exists(self.USER_CONFIG_FILE):
            try:
                with open(self.USER_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, TypeError):
                # Если файл пуст или поврежден, создаем дефолтный
                pass

        default_config = {'theme': 'light'}
        with open(self.USER_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=4)
        return default_config

    def save_user_config(self):
        """Сохраняет пользовательский конфиг."""
        with open(self.USER_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4)

    def init_ui(self):
        """Создает элементы интерфейса."""
        self.setWindowTitle("Torrent Manager")
        self.setGeometry(100, 100, 600, 500)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Секция ввода URL ---
        url_layout = QHBoxLayout()
        main_layout.addWidget(QLabel("Введите ссылку:"))
        self.url_entry = QLineEdit()
        self.url_entry.setPlaceholderText("https://rutracker.org/forum/viewtopic.php?t=...")
        url_layout.addWidget(self.url_entry)

        paste_btn = QPushButton("📋")
        paste_btn.setToolTip("Вставить из буфера обмена")
        paste_btn.setFixedWidth(40)
        paste_btn.clicked.connect(self.paste_from_clipboard)
        url_layout.addWidget(paste_btn)
        main_layout.addLayout(url_layout)

        # --- Секция выбора папки ---
        path_layout = QHBoxLayout()
        main_layout.addWidget(QLabel("Выберите папку:"))
        self.path_label = QLineEdit("Папка не выбрана")
        self.path_label.setReadOnly(True)
        path_layout.addWidget(self.path_label)

        browse_btn = QPushButton("...")
        browse_btn.setToolTip("Выбрать папку для сохранения")
        browse_btn.setFixedWidth(40)
        browse_btn.clicked.connect(self.pick_folder)
        path_layout.addWidget(browse_btn)
        main_layout.addLayout(path_layout)

        # --- Секция кнопок действий ---
        action_layout = QHBoxLayout()
        add_btn = QPushButton("Добавить")
        add_btn.clicked.connect(self.add_action)
        action_layout.addWidget(add_btn)

        update_btn = QPushButton("Обновить")
        update_btn.clicked.connect(self.update_action)
        action_layout.addWidget(update_btn)
        main_layout.addLayout(action_layout)

        # --- Секция логов ---
        main_layout.addWidget(QLabel("Логи:"))
        self.log_widget = QTreeWidget()
        self.log_widget.setColumnCount(2)
        self.log_widget.setHeaderLabels(["Время", "Сообщение"])
        self.log_widget.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.log_widget.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        main_layout.addWidget(self.log_widget)

        # --- Переключатель темы ---
        theme_layout = QHBoxLayout()
        self.theme_btn = QPushButton()
        self.theme_btn.clicked.connect(self.toggle_theme)
        theme_layout.addStretch()
        theme_layout.addWidget(self.theme_btn)
        main_layout.addLayout(theme_layout)

        self.log_message("Приложение запущено.")

    def apply_theme(self):
        """Применяет выбранную тему."""
        if self.config.get('theme') == 'dark':
            self.setStyleSheet(DARK_STYLESHEET)
            self.theme_btn.setText("🌞 Светлая тема")
            self.theme_btn.setToolTip("Переключиться на светлую тему")
        else:
            self.setStyleSheet(LIGHT_STYLESHEET)
            self.theme_btn.setText("🌙 Тёмная тема")
            self.theme_btn.setToolTip("Переключиться на тёмную тему")

    def toggle_theme(self):
        """Переключает тему."""
        if self.config.get('theme') == 'dark':
            self.config['theme'] = 'light'
        else:
            self.config['theme'] = 'dark'
        self.save_user_config()
        self.apply_theme()

    def log_message(self, message):
        """Добавляет сообщение в виджет логов."""
        timestamp = datetime.now().strftime('%H:%M:%S')

        # Если сообщение очень длинное, делаем его сворачиваемым
        if len(message) > self.LOG_TRUNCATE_LENGTH:
            short_message = message[:self.LOG_TRUNCATE_LENGTH] + "... (нажмите, чтобы развернуть)"
            parent_item = QTreeWidgetItem(self.log_widget, [timestamp, short_message])
            # Добавляем полное сообщение как дочерний элемент
            child_item = QTreeWidgetItem(parent_item, ["", message])
            child_item.setFont(1, QFont("Courier New", 9))
        else:
            QTreeWidgetItem(self.log_widget, [timestamp, message])

        self.log_widget.scrollToBottom()

    def pick_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите папку")
        if folder_path:
            self.selected_path = folder_path
            self.path_label.setText(folder_path)
            self.log_message(f"Выбрана папка: {folder_path}")

    def add_action(self):
        url = self.url_entry.text()
        if not url:
            QMessageBox.critical(self, "Ошибка", "Введите ссылку!")
            return

        if not self.selected_path:
            QMessageBox.critical(self, "Ошибка", "Выберите папку!")
            return

        try:
            rutt_to_qb.add_torrent_from_url(url, self.selected_path, log_func=self.log_message)
            QMessageBox.information(self, "Успех", "Задание на добавление торрента создано!")
            self.url_entry.clear()
        except Exception as e:
            self.log_message(f"Критическая ошибка при добавлении: {e}")
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка: {e}")

    def update_action(self):
        try:
            # Передаем нашу функцию логирования в бэкенд
            self.log_message("Запускаю обновление всех торрентов...")
            rutt_to_qb.update_torrents(log_func=self.log_message)
            QMessageBox.information(self, "Успех", "Обновление торрентов завершено!")
        except Exception as e:
            self.log_message(f"Критическая ошибка при обновлении: {e}")
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка: {e}")

    def paste_from_clipboard(self):
        clipboard = QGuiApplication.clipboard()
        self.url_entry.setText(clipboard.text())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    QApplication.setApplicationName("Torrent Manager")
    window = TorrentApp()
    window.show()
    sys.exit(app.exec())