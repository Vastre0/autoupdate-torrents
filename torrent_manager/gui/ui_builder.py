"""Сборка интерфейса главного окна."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)


class UiBuilder:
    """Создаёт и раскладывает виджеты главного окна."""

    def __init__(self, window):
        self.window = window

    def setup_ui(self) -> None:
        self.window._setup_main_window()
        main_layout = QVBoxLayout()

        self.window.error_label = QLabel(visible=False, objectName="errorLabel")
        self.window.error_label.setWordWrap(True)
        main_layout.addWidget(self.window.error_label)

        main_layout.addLayout(self._create_add_torrent_section())
        main_layout.addWidget(self._create_separator())
        main_layout.addLayout(self._create_torrent_list_section())
        main_layout.addLayout(self._create_tools_section())
        main_layout.addLayout(self._create_log_section())
        main_layout.addLayout(self._create_status_bar())
        main_layout.setStretchFactor(main_layout.itemAt(4).layout(), 1)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.window.setCentralWidget(central_widget)

    # ------------------------------------------------------------------ секции
    def _create_input_row(
        self,
        label_text: str,
        entry: QLineEdit,
        button_text: str,
        button_tooltip: str,
        button_click: callable,
        button_width: int,
    ) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(QLabel(label_text))
        layout.addWidget(entry)
        layout.addWidget(self._create_button(button_text, button_tooltip, button_click, button_width))
        return layout

    def _create_add_torrent_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.addWidget(QLabel("<b>Добавить новый торрент для отслеживания:</b>"))

        self.window.url_entry = self._create_line_edit(
            placeholder="https://rutracker.org/forum/viewtopic.php?t=..."
        )
        layout.addLayout(
            self._create_input_row(
                "Ссылка:", self.window.url_entry, "📋", "Вставить из буфера обмена",
                self.window.paste_from_clipboard, 40,
            )
        )

        self.window.path_label = self._create_line_edit("Папка не выбрана", read_only=True)
        layout.addLayout(
            self._create_input_row(
                "Папка:", self.window.path_label, "...", "Выбрать папку для сохранения",
                self.window.pick_folder, 40,
            )
        )

        layout.addWidget(
            self._create_button(
                "Добавить в отслеживание",
                on_click=self.window.add_action,
                enabled=self.window.is_operational,
            )
        )
        return layout

    def _create_torrent_list_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.addWidget(QLabel("<b>Отслеживаемые торренты:</b>"))

        self.window.torrent_list_widget = QTreeWidget()
        self.window.torrent_list_widget.setColumnCount(3)
        self.window.torrent_list_widget.setHeaderLabels(["Название", "ID", "Путь сохранения"])
        header = self.window.torrent_list_widget.header()
        for column in range(3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.window.torrent_list_widget.itemSelectionChanged.connect(
            self.window.on_torrent_selection_change
        )
        self.window.torrent_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.window.torrent_list_widget.customContextMenuRequested.connect(
            self.window.show_list_context_menu
        )
        layout.addWidget(self.window.torrent_list_widget)

        buttons = QHBoxLayout()
        buttons.addWidget(self._create_button("Обновить список", on_click=self.window.load_and_display_torrents))
        self.window.update_btn = self._create_button(
            "Обновить все торренты",
            tooltip="Скачать .torrent со всеми обновлениями и отправить в qBittorrent",
            on_click=self.window.update_action,
            enabled=self.window.is_operational,
        )
        buttons.addWidget(self.window.update_btn)
        self.window.delete_btn = self._create_button(
            "Удалить выбранный", on_click=self.window.delete_selected_torrent, enabled=False
        )
        buttons.addWidget(self.window.delete_btn)
        layout.addLayout(buttons)
        return layout

    def _create_tools_section(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self.window.settings_btn = self._create_button("Настройки", on_click=self.window.open_settings)
        layout.addWidget(self.window.settings_btn)

        self.window.import_cookies_btn = self._create_button(
            "Импорт куки",
            tooltip="Открыть окно импорта куки rutracker.org",
            on_click=self.window.import_cookies_from_clipboard,
        )
        layout.addWidget(self.window.import_cookies_btn)

        self.window.pac_btn = self._create_button(
            "Обновить PAC",
            tooltip="Перекачать список блокировок Антизапрета",
            on_click=self.window.refresh_pac,
        )
        layout.addWidget(self.window.pac_btn)
        layout.addStretch()
        return layout

    def _create_log_section(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 5, 0, 5)
        is_expanded = self.window.config.get("logs_expanded", True)

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
        self.window.bypass_label = QLabel("Обход блокировок: —")
        self.window.bypass_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.window.bypass_label)
        layout.addStretch()

        self.window.theme_btn = self._create_button("", on_click=self.window.toggle_theme)
        layout.addWidget(self.window.theme_btn)
        return layout

    def _create_separator(self) -> QWidget:
        separator = QWidget(objectName="separatorLine")
        separator.setFixedHeight(1)
        return separator

    # --------------------------------------------------------------- делегаты
    def _create_button(self, *args, **kwargs) -> QPushButton:
        return self.window._create_button(*args, **kwargs)

    def _create_line_edit(self, *args, **kwargs) -> QLineEdit:
        return self.window._create_line_edit(*args, **kwargs)
