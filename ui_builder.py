from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTreeWidget, QHeaderView, QToolButton
)
from PyQt6.QtCore import Qt

class UiBuilder:
    def __init__(self, window):
        self.window = window

    def setup_ui(self):
        """Инициализирует и собирает пользовательский интерфейс из секций."""
        self.window._setup_main_window()
        main_layout = QVBoxLayout()

        self.window.error_label = QLabel(visible=False, objectName="errorLabel")
        main_layout.addWidget(self.window.error_label)

        main_layout.addLayout(self._create_add_torrent_section())
        main_layout.addWidget(self._create_separator())
        main_layout.addLayout(self._create_torrent_list_section())
        main_layout.addLayout(self._create_log_section())
        main_layout.addLayout(self._create_status_bar())
        main_layout.setStretchFactor(main_layout.itemAt(3).layout(), 1)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.window.setCentralWidget(central_widget)

    # --- ДОБАВЛЕН НЕДОСТАЮЩИЙ МЕТОД ---
    def _create_input_row(self, label_text: str, entry: QLineEdit, button_text: str, button_tooltip: str, button_click: callable, button_width: int) -> QHBoxLayout:
        """Создает горизонтальную строку с меткой, полем ввода и кнопкой."""
        layout = QHBoxLayout()
        layout.addWidget(QLabel(label_text))
        layout.addWidget(entry)
        # Этот вызов теперь будет работать, т.к. _create_button есть ниже
        layout.addWidget(self._create_button(button_text, button_tooltip, button_click, button_width))
        return layout

    def _create_add_torrent_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.addWidget(QLabel("<b>Добавить новый торрент для отслеживания:</b>"))

        self.window.url_entry = self._create_line_edit(placeholder="https://rutracker.org/forum/viewtopic.php?t=...")
        layout.addLayout(self._create_input_row("Ссылка:", self.window.url_entry, "📋", "Вставить из буфера обмена", self.window.paste_from_clipboard, 40))

        self.window.path_label = self._create_line_edit("Папка не выбрана", read_only=True)
        layout.addLayout(self._create_input_row("Папка:", self.window.path_label, "...", "Выбрать папку для сохранения", self.window.pick_folder, 40))

        layout.addWidget(self._create_button("Добавить в отслеживание", on_click=self.window.add_action, enabled=self.window.is_operational))
        return layout

    def _create_torrent_list_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.addWidget(QLabel("<b>Отслеживаемые торренты:</b>"))
        self.window.torrent_list_widget = QTreeWidget()
        self.window.torrent_list_widget.setColumnCount(3)
        self.window.torrent_list_widget.setHeaderLabels(["Название", "ID", "Путь сохранения"])
        header = self.window.torrent_list_widget.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.window.torrent_list_widget.itemSelectionChanged.connect(self.window.on_torrent_selection_change)
        layout.addWidget(self.window.torrent_list_widget)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self._create_button("Обновить список", on_click=self.window.load_and_display_torrents))
        btn_layout.addWidget(self._create_button("Обновить все торренты", on_click=self.window.update_action, enabled=self.window.is_operational))
        self.window.delete_btn = self._create_button("Удалить выбранный", on_click=self.window.delete_selected_torrent, enabled=False)
        btn_layout.addWidget(self.window.delete_btn)
        layout.addLayout(btn_layout)
        return layout

    def _create_log_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 5, 0, 5)
        is_expanded = self.window.config.get('logs_expanded', True)
        self.window.log_toggle_btn = QToolButton(checkable=True, checked=is_expanded)
        self.window.log_toggle_btn.setStyleSheet("QToolButton { border: none; }")
        self.window.log_toggle_btn.clicked.connect(self.window.toggle_log_visibility)
        header_layout.addWidget(self.window.log_toggle_btn)
        header_layout.addWidget(QLabel("<b>Логи</b>"))
        header_layout.addStretch()
        layout.addLayout(header_layout)

        self.window.log_widget = QTreeWidget(visible=is_expanded)
        self.window.log_widget.setColumnCount(2)
        self.window.log_widget.setHeaderLabels(["Время", "Сообщение"])
        self.window.log_widget.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.window.log_widget)
        self.window.update_log_toggle_button()
        return layout

    def _create_status_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self.window.theme_btn = self._create_button("", on_click=self.window.toggle_theme)
        layout.addStretch()
        layout.addWidget(self.window.theme_btn)
        return layout

    def _create_separator(self) -> QWidget:
        separator = QWidget(objectName="separatorLine")
        separator.setFixedHeight(1)
        return separator

    # Эти методы-делегаты перенаправляют вызовы к главному окну, где находятся "фабрики" виджетов.
    # Это позволяет UiBuilder-у использовать их.
    def _create_button(self, *args, **kwargs) -> QPushButton:
        return self.window._create_button(*args, **kwargs)

    def _create_line_edit(self, *args, **kwargs) -> QLineEdit:
        return self.window._create_line_edit(*args, **kwargs)
