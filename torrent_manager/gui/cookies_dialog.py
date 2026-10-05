"""Диалоговое окно импорта куки rutracker."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
)


class CookiesDialog(QDialog):
    """Окно для ввода / вставки куки rutracker.org."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Импорт куки rutracker.org")
        self.setMinimumSize(620, 420)
        self._result_text: str | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        help_label = QLabel(
            "<b>Как получить куки:</b><br>"
            "1. Войдите на <a href='https://rutracker.org'>rutracker.org</a> в браузере.<br>"
            "2. <code>F12</code> → вкладка <b>Network</b> (Сеть) → <code>F5</code>.<br>"
            "3. Кликните на любой запрос к <code>rutracker.org</code>.<br>"
            "4. В <b>Request Headers</b> найдите строку <code>Cookie:</code> "
            "и скопируйте её значение.<br>"
            "5. Вставьте сюда и нажмите <b>«Сохранить»</b>."
        )
        help_label.setWordWrap(True)
        help_label.setOpenExternalLinks(True)
        help_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(help_label)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "bb_session=abcdef1234567890; bb_ssl=1; bb_guid=XXXX..."
        )
        self.text_edit.setFont(QFont("Monospace", 9))
        layout.addWidget(self.text_edit)

        btn_row = QHBoxLayout()
        paste_btn = QPushButton("📋 Вставить из буфера")
        paste_btn.setToolTip("Вставить содержимое буфера обмена в поле выше")
        paste_btn.clicked.connect(self._paste_from_clipboard)
        btn_row.addWidget(paste_btn)

        clear_btn = QPushButton("Очистить")
        clear_btn.clicked.connect(self.text_edit.clear)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        button_box.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        button_box.accepted.connect(self._on_save)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _paste_from_clipboard(self) -> None:
        clipboard_text = QGuiApplication.clipboard().text().strip()
        if clipboard_text:
            self.text_edit.setPlainText(clipboard_text)
        else:
            QMessageBox.warning(self, "Буфер пуст", "В буфере обмена нет текста.")

    def _on_save(self) -> None:
        text = self.text_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(
                self, "Пустое поле",
                "Введите или вставьте строку Cookie из браузера.",
            )
            return
        self._result_text = text
        self.accept()

    def cookie_text(self) -> str | None:
        """Возвращает введённый текст после accept(), иначе None."""
        return self._result_text
