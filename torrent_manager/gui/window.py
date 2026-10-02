"""Главное окно приложения."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QEvent, Qt, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QDesktopServices, QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QMessageBox,
    QPushButton,
    QTreeWidgetItem,
    QMainWindow,
    QLineEdit,
    QMenu,
)

from ..config import ConfigManager
from ..cookies import HELP_TEXT, cookies_path
from ..resources import icon_path, load_stylesheet, stylesheet_path
from ..service import TorrentService
from .settings_dialog import SettingsDialog
from .tray import TrayManager
from .ui_builder import UiBuilder
from .worker import TaskWorker, UpdateWorker


class TorrentApp(QMainWindow):
    """Окно управления отслеживаемыми раздачами."""

    LOG_TRUNCATE_LENGTH = 100
    log_signal = pyqtSignal(str)

    def __init__(self, config: ConfigManager | None = None):
        super().__init__()
        self.config = config or ConfigManager()
        # Сообщения, пришедшие до создания виджетов, складываются в буфер.
        self._log_buffer: list[str] = []
        self.log_signal.connect(self.log_message)
        self.service = TorrentService(self.config, log=self.log_signal.emit)

        self.is_operational = self.service.has_cookies()
        self.selected_path = ""
        self._is_quitting = False
        self._update_thread: UpdateWorker | None = None
        self._task_thread: TaskWorker | None = None

        self.ui = UiBuilder(self)
        self.tray = TrayManager(self)

        self.ui.setup_ui()
        self.apply_theme()
        self._apply_column_widths()
        self._update_bypass_label()
        self._flush_log_buffer()

        if self.is_operational:
            self.load_and_display_torrents()
            self.log_message("Приложение запущено.")
        else:
            self._show_cookies_warning()
            self.log_message("Приложение запущено без куки rutracker.")

        # Обновляем список блокировок в фоне, чтобы не тормозить запуск.
        if self.service.bypass.enabled:
            self.service.bypass.refresh_in_background()

    # --------------------------------------------------------------- интерфейс
    def _setup_main_window(self) -> None:
        self.setWindowTitle("Torrent Manager")
        geometry = self.config.get("window_geometry") or {}
        self.setGeometry(
            int(geometry.get("x", 100)),
            int(geometry.get("y", 100)),
            int(geometry.get("width", 900)),
            int(geometry.get("height", 700)),
        )
        path = icon_path()
        if path:
            from PyQt6.QtGui import QIcon

            self.setWindowIcon(QIcon(path))

    def _create_button(
        self,
        text: str,
        tooltip: str | None = None,
        on_click: callable | None = None,
        fixed_width: int | None = None,
        enabled: bool = True,
    ) -> QPushButton:
        button = QPushButton(text)
        if tooltip:
            button.setToolTip(tooltip)
        if on_click:
            button.clicked.connect(on_click)
        if fixed_width:
            button.setFixedWidth(fixed_width)
        button.setEnabled(enabled)
        return button

    def _create_line_edit(self, text: str = "", placeholder: str | None = None, read_only: bool = False) -> QLineEdit:
        entry = QLineEdit(text)
        if placeholder:
            entry.setPlaceholderText(placeholder)
        entry.setReadOnly(read_only)
        return entry

    def _apply_column_widths(self) -> None:
        widths = self.config.get("torrent_columns_width") or [300, 100, 400]
        header = self.torrent_list_widget.header()
        if len(widths) == 3:
            for index, width in enumerate(widths):
                header.resizeSection(index, int(width))

    # -------------------------------------------------------------------- тема
    def apply_theme(self) -> None:
        is_dark = self.config.get("theme") == "dark"
        separator_color = "#555" if is_dark else "#cccccc"
        theme_text = "🌞 Светлая тема" if is_dark else "🌙 Тёмная тема"
        theme_tooltip = "Переключиться на светлую тему" if is_dark else "Переключиться на тёмную тему"

        stylesheet = load_stylesheet(stylesheet_path(is_dark))
        stylesheet += f"\nQWidget#separatorLine {{ background-color: {separator_color}; }}"
        self.setStyleSheet(stylesheet)
        self.theme_btn.setText(theme_text)
        self.theme_btn.setToolTip(theme_tooltip)

    @pyqtSlot()
    def toggle_theme(self) -> None:
        self.config.set("theme", "light" if self.config.get("theme") == "dark" else "dark")
        self.apply_theme()

    # ------------------------------------------------------------------- логи
    def _flush_log_buffer(self) -> None:
        """Показывает сообщения, накопившиеся до создания виджетов."""
        buffered, self._log_buffer = self._log_buffer, []
        for message in buffered:
            self.log_message(message)

    @pyqtSlot(str)
    def log_message(self, message: str) -> None:
        if not hasattr(self, "log_widget"):
            self._log_buffer.append(message)
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        if len(message) > self.LOG_TRUNCATE_LENGTH:
            short_message = message[: self.LOG_TRUNCATE_LENGTH] + "... (нажмите, чтобы развернуть)"
            parent_item = QTreeWidgetItem(self.log_widget, [timestamp, short_message])
            child_item = QTreeWidgetItem(parent_item, ["", message])
            child_item.setFont(1, QFont("Monospace", 9))
        else:
            QTreeWidgetItem(self.log_widget, [timestamp, message])
        self.log_widget.scrollToBottom()

    @pyqtSlot()
    def toggle_log_visibility(self) -> None:
        is_visible = self.log_toggle_btn.isChecked()
        self.log_widget.setVisible(is_visible)
        self.update_log_toggle_button()
        self.config.set("logs_expanded", is_visible)

    def update_log_toggle_button(self) -> None:
        arrow = Qt.ArrowType.DownArrow if self.log_toggle_btn.isChecked() else Qt.ArrowType.RightArrow
        tooltip = "Свернуть логи" if self.log_toggle_btn.isChecked() else "Развернуть логи"
        self.log_toggle_btn.setArrowType(arrow)
        self.log_toggle_btn.setToolTip(tooltip)

    # ------------------------------------------------------------ предупреждения
    def _show_cookies_warning(self) -> None:
        self.error_label.setText(
            "<b>Куки rutracker.org не найдены.</b> Функции добавления и обновления недоступны.<br>"
            f"Ожидаемый файл: <code>{cookies_path()}</code><br>"
            "Скопируйте строку Cookie из браузера и нажмите «Импорт куки из буфера»."
        )
        self.error_label.setVisible(True)

    def _hide_cookies_warning(self) -> None:
        self.error_label.setVisible(False)

    # ---------------------------------------------------------------- действия
    @pyqtSlot()
    def paste_from_clipboard(self) -> None:
        self.url_entry.setText(QGuiApplication.clipboard().text().strip())

    @pyqtSlot()
    def pick_folder(self) -> None:
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите папку")
        if folder_path:
            self.selected_path = folder_path
            self.path_label.setText(folder_path)
            self.log_message(f"Выбрана папка: {folder_path}")

    @pyqtSlot()
    def add_action(self) -> None:
        url = self.url_entry.text().strip()
        if not url or not self.selected_path:
            QMessageBox.warning(self, "Ошибка", "Необходимо указать ссылку и папку для сохранения.")
            return
        try:
            self.service.add_torrent(url, self.selected_path)
        except Exception as error:  # noqa: BLE001 - показываем текст пользователю
            self.log_message(f"Ошибка при добавлении раздачи: {error}")
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка: {error}")
            return
        QMessageBox.information(self, "Успех", "Раздача добавлена в список отслеживания!")
        self.url_entry.clear()
        self.load_and_display_torrents()

    @pyqtSlot()
    def load_and_display_torrents(self) -> None:
        self.log_message("Загрузка списка отслеживаемых торрентов...")
        self.torrent_list_widget.clear()
        try:
            for entry in self.service.list_tracked():
                item = QTreeWidgetItem([entry["name"], entry["topic_id"], entry["save_path"]])
                item.setData(1, Qt.ItemDataRole.UserRole, entry["topic_id"])
                item.setToolTip(2, entry["save_path"])
                self.torrent_list_widget.addTopLevelItem(item)
            self.log_message(f"Загружено {self.torrent_list_widget.topLevelItemCount()} раздач.")
        except Exception as error:  # noqa: BLE001
            self.log_message(f"Ошибка при загрузке списка раздач: {error}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить список: {error}")

    @pyqtSlot()
    def on_torrent_selection_change(self) -> None:
        is_enabled = self.is_operational and bool(self.torrent_list_widget.selectedItems())
        self.delete_btn.setEnabled(is_enabled)

    @pyqtSlot()
    def delete_selected_torrent(self) -> None:
        selected_item = self.torrent_list_widget.currentItem()
        if not selected_item:
            return
        topic_id = selected_item.data(1, Qt.ItemDataRole.UserRole)
        torrent_name = selected_item.text(0)
        confirmed, delete_files = self._ask_delete_confirmation(torrent_name, topic_id)
        if not confirmed:
            return
        self.log_message(f"Удаление раздачи {topic_id} (удалять файлы: {delete_files})")
        try:
            self.service.remove_torrent(topic_id, delete_files=delete_files)
        except Exception as error:  # noqa: BLE001
            self.log_message(f"Ошибка при удалении раздачи {topic_id}: {error}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось удалить раздачу: {error}")
        self.load_and_display_torrents()

    def _ask_delete_confirmation(self, name: str, topic_id: str) -> tuple[bool, bool]:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Подтверждение удаления")
        box.setText(f"Удалить раздачу «{name}» (ID: {topic_id}) из qBittorrent и списка?")
        checkbox = QCheckBox("Удалить также скачанные файлы")
        box.setCheckBox(checkbox)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        result = box.exec()
        return result == QMessageBox.StandardButton.Yes, checkbox.isChecked()

    # ------------------------------------------------------------- обновление
    @pyqtSlot()
    def update_action(self) -> None:
        if not self.is_operational:
            QMessageBox.warning(
                self, "Нет доступа", "Сначала укажите куки rutracker (кнопка «Импорт куки из буфера»)."
            )
            return
        if self._update_thread and self._update_thread.isRunning():
            self.log_message("Обновление уже выполняется.")
            return

        self.update_btn.setEnabled(False)
        self.log_message("Запуск обновления всех раздач...")
        worker = UpdateWorker(lambda progress: self.service.update_all(progress=None), self)
        worker.finished_ok.connect(self._on_update_finished)
        worker.failed.connect(self._on_update_failed)
        worker.finished.connect(lambda: self.update_btn.setEnabled(True))
        self._update_thread = worker
        worker.start()

    @pyqtSlot(object)
    def _on_update_finished(self, result) -> None:
        summary = result.summary()
        self.log_message(summary)
        self.load_and_display_torrents()
        if result.failed:
            QMessageBox.warning(self, "Обновление завершено с ошибками", summary)
        else:
            QMessageBox.information(self, "Обновление завершено", summary)

    @pyqtSlot(str)
    def _on_update_failed(self, message: str) -> None:
        self.log_message(f"Обновление не выполнено: {message}")
        QMessageBox.critical(self, "Ошибка обновления", message)

    @pyqtSlot()
    def refresh_pac(self) -> None:
        if self._task_thread and self._task_thread.isRunning():
            return
        self.pac_btn.setEnabled(False)
        self.log_message("Обновление списка блокировок (PAC-скрипт)...")

        def action():
            self.service.refresh_pac(force=True)
            return self.service.bypass_status()

        def done(status: dict) -> None:
            self._update_bypass_label(status)

        worker = TaskWorker(action, self)
        worker.finished_ok.connect(done)
        worker.failed.connect(lambda error: self.log_message(f"Не удалось обновить PAC: {error}"))
        worker.finished.connect(lambda: self.pac_btn.setEnabled(True))
        self._task_thread = worker
        worker.start()

    # ------------------------------------------------------------------ статус
    def _update_bypass_label(self, status: dict | None = None) -> None:
        status = status or self.service.bypass_status()
        if not status.get("enabled"):
            text = "Обход блокировок: выключен"
        elif status.get("loaded"):
            proxy = status.get("proxy") or status.get("manual_proxy") or "—"
            text = (
                f"Обход блокировок: PAC загружен ({status.get('domains', 0)} доменов), "
                f"прокси {proxy}"
            )
        elif status.get("manual_proxy"):
            text = f"Обход блокировок: PAC недоступен, резервный прокси {status['manual_proxy']}"
        else:
            text = "Обход блокировок: PAC не загружен (запросы идут напрямую)"
        if status.get("error"):
            text += f" — {status['error']}"
        self.bypass_label.setText(text)

    # -------------------------------------------------------------------- куки
    @pyqtSlot()
    def import_cookies_from_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text().strip()
        if not text:
            QMessageBox.warning(self, "Куки", "Буфер обмена пуст.\n\n" + HELP_TEXT)
            return
        try:
            self.service.import_cookies(text)
        except ValueError as error:
            QMessageBox.critical(self, "Куки", f"{error}\n\n{HELP_TEXT}")
            return
        self.is_operational = True
        self._hide_cookies_warning()
        self.update_btn.setEnabled(True)
        QMessageBox.information(self, "Куки", "Куки сохранены. Можно обновлять раздачи.")

    # -------------------------------------------------------------- настройки
    @pyqtSlot()
    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.exec()

    def on_settings_saved(self) -> None:
        self.is_operational = self.service.has_cookies()
        self.update_btn.setEnabled(self.is_operational)
        if self.is_operational:
            self._hide_cookies_warning()
        else:
            self._show_cookies_warning()
        self.apply_theme()
        self._update_bypass_label()
        self.log_message("Настройки сохранены.")

    # ------------------------------------------------------- контекстное меню
    def show_list_context_menu(self, position) -> None:
        item = self.torrent_list_widget.itemAt(position)
        if item is None:
            return
        topic_id = item.data(1, Qt.ItemDataRole.UserRole)
        url = f"https://rutracker.org/forum/viewtopic.php?t={topic_id}"
        menu = QMenu(self)
        menu.addAction("Открыть раздачу в браузере", lambda: QDesktopServices.openUrl(QUrl(url)))
        menu.addAction("Копировать ссылку", lambda: QGuiApplication.clipboard().setText(url))
        menu.addAction("Копировать ID", lambda: QGuiApplication.clipboard().setText(str(topic_id)))
        menu.addAction(
            "Открыть папку",
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(item.text(2))),
        )
        menu.exec(self.torrent_list_widget.viewport().mapToGlobal(position))

    # ------------------------------------------------------------------ выход
    def _save_state(self) -> None:
        geometry = self.geometry()
        self.config.set(
            "window_geometry",
            {
                "x": geometry.x(),
                "y": geometry.y(),
                "width": geometry.width(),
                "height": geometry.height(),
            },
        )
        header = self.torrent_list_widget.header()
        self.config.set("torrent_columns_width", [header.sectionSize(i) for i in range(3)])
        self.config.save()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt
        self._save_state()
        if self._is_quitting or not self.tray.is_enabled or not self.config.get("close_to_tray"):
            event.accept()
            return
        event.ignore()
        self.tray.hide_to_tray("Приложение продолжает работу в трее")

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self.tray.is_enabled
            and self.config.get("minimize_to_tray")
        ):
            QTimer.singleShot(0, lambda: self.tray.hide_to_tray("Приложение свернуто в трей"))

    @pyqtSlot()
    def exit_app(self) -> None:
        self._is_quitting = True
        self.tray.hide()
        self.close()
