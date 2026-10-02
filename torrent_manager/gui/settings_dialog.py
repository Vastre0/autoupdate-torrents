"""Диалог настроек: qBittorrent, обход блокировок, интеграция с системой."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import integration
from ..cookies import HELP_TEXT
from ..paths import config_dir
from .worker import TaskWorker


class SettingsDialog(QDialog):
    """Настройки приложения с проверкой соединений."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.service = window.service
        self.config = window.config
        self._workers: list[TaskWorker] = []

        self.setWindowTitle("Настройки Torrent Manager")
        self.setMinimumWidth(560)

        tabs = QTabWidget()
        tabs.addTab(self._build_qbittorrent_tab(), "qBittorrent")
        tabs.addTab(self._build_bypass_tab(), "Обход блокировок")
        tabs.addTab(self._build_system_tab(), "Система")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(tabs)
        layout.addWidget(buttons)
        self.setLayout(layout)

    # ------------------------------------------------------------------ вкладки
    def _build_qbittorrent_tab(self) -> QWidget:
        settings = self.config.get_section("qbittorrent")
        widget = QWidget()
        layout = QVBoxLayout(widget)

        form = QFormLayout()
        self.qb_host = QLineEdit(str(settings.get("host", "localhost:8080")))
        self.qb_host.setPlaceholderText("localhost:8080")
        form.addRow("Адрес веб-интерфейса:", self.qb_host)

        self.qb_username = QLineEdit(str(settings.get("username", "admin")))
        form.addRow("Имя пользователя:", self.qb_username)

        self.qb_password = QLineEdit(str(settings.get("password", "")))
        self.qb_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Пароль:", self.qb_password)

        self.qb_https = QCheckBox("Использовать HTTPS")
        self.qb_https.setChecked(bool(settings.get("use_https", False)))
        form.addRow("", self.qb_https)
        layout.addLayout(form)

        row = QHBoxLayout()
        test_btn = QPushButton("Проверить подключение")
        test_btn.clicked.connect(self.test_qbittorrent)
        row.addWidget(test_btn)
        self.qb_status = QLabel("")
        self.qb_status.setWordWrap(True)
        row.addWidget(self.qb_status, 1)
        layout.addLayout(row)

        hint = QLabel(
            "Включите веб-интерфейс в qBittorrent: Настройки → Веб-интерфейс "
            "(по умолчанию http://localhost:8080, admin/adminadmin)."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        return widget

    def _build_bypass_tab(self) -> QWidget:
        settings = self.config.get_section("bypass")
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.bypass_enabled = QCheckBox("Включить обход блокировок (PAC-скрипт Антизапрета)")
        self.bypass_enabled.setChecked(bool(settings.get("enabled", True)))
        layout.addWidget(self.bypass_enabled)

        explanation = QLabel(
            "Тот же список блокировок, что использует расширение «Обход блокировок Рунета» "
            "для Firefox: через прокси идут только заблокированные сайты. Браузер не нужен."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()
        self.prefer_https_proxy = QCheckBox("Предпочитать HTTPS-прокси (если доступен)")
        self.prefer_https_proxy.setChecked(bool(settings.get("prefer_https_proxy", True)))
        form.addRow("", self.prefer_https_proxy)

        self.dns_check = QCheckBox("Проверять IP-адреса хостов по спискам PAC")
        self.dns_check.setChecked(bool(settings.get("dns_check", True)))
        form.addRow("", self.dns_check)

        self.manual_proxy = QLineEdit(str(settings.get("manual_proxy", "")))
        self.manual_proxy.setPlaceholderText("например socks5://127.0.0.1:9050 (Tor) или http://127.0.0.1:8118")
        form.addRow("Резервный прокси:", self.manual_proxy)

        self.pac_ttl = QDoubleSpinBox()
        self.pac_ttl.setRange(1.0, 168.0)
        self.pac_ttl.setSuffix(" ч")
        self.pac_ttl.setValue(float(settings.get("pac_cache_ttl_hours", 12)))
        form.addRow("Обновлять список каждые:", self.pac_ttl)
        layout.addLayout(form)

        pac_box = QGroupBox("PAC-скрипт")
        pac_layout = QVBoxLayout(pac_box)
        self.pac_status = QLabel("")
        self.pac_status.setWordWrap(True)
        pac_layout.addWidget(self.pac_status)

        row = QHBoxLayout()
        refresh_btn = QPushButton("Обновить сейчас")
        refresh_btn.clicked.connect(self.refresh_pac)
        row.addWidget(refresh_btn)
        row.addStretch()
        pac_layout.addLayout(row)
        layout.addWidget(pac_box)

        check_box = QGroupBox("Проверить хост")
        check_layout = QHBoxLayout(check_box)
        self.check_host_edit = QLineEdit("rutracker.org")
        check_layout.addWidget(self.check_host_edit)
        check_btn = QPushButton("Проверить")
        check_btn.clicked.connect(self.check_host)
        check_layout.addWidget(check_btn)
        layout.addWidget(check_box)
        self.check_host_result = QLabel("")
        self.check_host_result.setWordWrap(True)
        layout.addWidget(self.check_host_result)

        layout.addStretch()
        self.update_pac_status()
        return widget

    def _build_system_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.autostart_checkbox = QCheckBox("Запускать при входе в систему")
        self.autostart_checkbox.setChecked(integration.is_autostart_enabled())
        layout.addWidget(self.autostart_checkbox)

        timer_box = QGroupBox("Периодическое обновление (systemd --user)")
        timer_layout = QVBoxLayout(timer_box)
        self.timer_status = QLabel(integration.timer_status())
        self.timer_status.setWordWrap(True)
        timer_layout.addWidget(self.timer_status)

        row = QHBoxLayout()
        install_btn = QPushButton("Установить таймер")
        install_btn.clicked.connect(self.install_timer)
        row.addWidget(install_btn)
        remove_btn = QPushButton("Выключить таймер")
        remove_btn.clicked.connect(self.remove_timer)
        row.addWidget(remove_btn)
        row.addStretch()
        timer_layout.addLayout(row)
        layout.addWidget(timer_box)

        paths_box = QGroupBox("Файлы и каталоги")
        paths_layout = QVBoxLayout(paths_box)
        paths_layout.addWidget(QLabel(f"Конфиги и куки: {config_dir()}"))
        open_btn = QPushButton("Открыть каталог конфигов")
        open_btn.clicked.connect(self.open_config_dir)
        paths_layout.addWidget(open_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        help_label = QLabel(HELP_TEXT)
        help_label.setWordWrap(True)
        paths_layout.addWidget(help_label)
        layout.addWidget(paths_box)

        layout.addStretch()
        return widget

    # ------------------------------------------------------------------ действия
    def _run_task(self, action, on_success, on_error=None) -> None:
        worker = TaskWorker(action, self)
        worker.finished_ok.connect(on_success)
        if on_error is not None:
            worker.failed.connect(on_error)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        self._workers.append(worker)
        worker.start()

    def test_qbittorrent(self) -> None:
        self.qb_status.setText("Проверяем…")

        def action():
            from ..torrents import QBittorrentClient

            client = QBittorrentClient(
                {
                    "host": self.qb_host.text().strip(),
                    "username": self.qb_username.text(),
                    "password": self.qb_password.text(),
                    "use_https": self.qb_https.isChecked(),
                }
            )
            return client.test()

        def done(result):
            ok, message = result
            self.qb_status.setText(("✅ " if ok else "❌ ") + message)

        self._run_task(action, done, lambda error: self.qb_status.setText(f"❌ {error}"))

    def refresh_pac(self) -> None:
        self.pac_status.setText("Загружаем PAC-скрипт…")
        self.apply_to_config()

        def action():
            self.service.refresh_pac(force=True)
            return self.service.bypass_status()

        def done(status):
            self.update_pac_status(status)

        self._run_task(action, done, lambda error: self.pac_status.setText(f"❌ {error}"))

    def check_host(self) -> None:
        host = self.check_host_edit.text().strip()
        if not host:
            return
        self.check_host_result.setText("Проверяем…")

        def action():
            return self.service.check_host(host)

        self._run_task(action, lambda text: self.check_host_result.setText(text))

    def install_timer(self) -> None:
        service_path, timer_path = integration.install_systemd_units()
        ok, message = integration.enable_systemd_timer()
        self.timer_status.setText(
            f"{message}\nUnit-файлы: {service_path.name}, {timer_path.name}"
        )
        if not ok:
            QMessageBox.warning(self, "systemd", message)

    def remove_timer(self) -> None:
        ok, message = integration.disable_systemd_timer()
        self.timer_status.setText(message)
        if not ok:
            QMessageBox.warning(self, "systemd", message)

    def open_config_dir(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_dir())))

    def update_pac_status(self, status: dict | None = None) -> None:
        status = status or self.service.bypass_status()
        age = status.get("age_seconds")
        if age is None:
            age_text = "кэш отсутствует"
        elif age < 3600:
            age_text = f"обновлён {int(age // 60)} мин назад"
        else:
            age_text = f"обновлён {age / 3600:.1f} ч назад"
        lines = [
            f"Состояние: {'загружен' if status.get('loaded') else 'не загружен'} ({age_text})",
            f"Источник: {status.get('source') or '—'}",
            f"Прокси: {status.get('proxy') or status.get('manual_proxy') or '—'}",
            f"Доменов в списке: {status.get('domains', 0)}, IP: {status.get('blocked_ips', 0)}",
        ]
        if status.get("error"):
            lines.append(f"Ошибка: {status['error']}")
        self.pac_status.setText("\n".join(lines))

    # -------------------------------------------------------------------- прим.
    def apply_to_config(self) -> None:
        self.config.set_section(
            "qbittorrent",
            {
                "host": self.qb_host.text().strip(),
                "username": self.qb_username.text(),
                "password": self.qb_password.text(),
                "use_https": self.qb_https.isChecked(),
            },
        )
        self.config.set_section(
            "bypass",
            {
                "enabled": self.bypass_enabled.isChecked(),
                "prefer_https_proxy": self.prefer_https_proxy.isChecked(),
                "dns_check": self.dns_check.isChecked(),
                "manual_proxy": self.manual_proxy.text().strip(),
                "pac_cache_ttl_hours": float(self.pac_ttl.value()),
            },
        )

    def accept(self) -> None:  # noqa: D102 - Qt
        self.apply_to_config()
        try:
            integration.set_autostart(self.autostart_checkbox.isChecked())
        except OSError as error:
            QMessageBox.warning(self, "Автозапуск", f"Не удалось изменить автозапуск: {error}")
        self.config.set("autostart", self.autostart_checkbox.isChecked())
        self.config.save()
        self.window.on_settings_saved()
        super().accept()
