"""Дымовые тесты графического интерфейса (нужен PyQt6; работает headless)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:  # pragma: no cover - зависит от окружения
    from PyQt6.QtWidgets import QApplication

    HAS_QT = True
except ImportError:  # pragma: no cover
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class GuiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="autoupdate-test-"))
        self._env = os.environ.get("AUTOUPDATE_TORRENTS_HOME")
        os.environ["AUTOUPDATE_TORRENTS_HOME"] = str(self.tmp)

    def tearDown(self) -> None:
        if self._env is None:
            os.environ.pop("AUTOUPDATE_TORRENTS_HOME", None)
        else:
            os.environ["AUTOUPDATE_TORRENTS_HOME"] = self._env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_window_and_settings(self) -> None:
        from torrent_manager.bypass import BypassManager
        from torrent_manager.config import ConfigManager
        from torrent_manager.gui.settings_dialog import SettingsDialog
        from torrent_manager.gui.window import TorrentApp

        app = QApplication.instance() or QApplication([])
        config = ConfigManager()

        with mock.patch.object(BypassManager, "refresh_in_background", lambda self: None), \
             mock.patch.object(BypassManager, "ensure_loaded", return_value=False):
            window = TorrentApp(config=config)
            self.assertEqual(window.windowTitle(), "Torrent Manager")
            self.assertFalse(window.is_operational)  # куки ещё не импортированы
            self.assertTrue(window.error_label.isVisibleTo(window))

            # Импорт куки как из буфера обмена
            from PyQt6.QtGui import QGuiApplication

            QGuiApplication.clipboard().setText("bb_session=abc; bb_ssl=1")
            with mock.patch("PyQt6.QtWidgets.QMessageBox.information", return_value=None):
                window.import_cookies_from_clipboard()
            self.assertTrue(window.is_operational)

            window.log_message("проверка логирования")
            window.load_and_display_torrents()
            self.assertEqual(window.torrent_list_widget.topLevelItemCount(), 0)

            window.service.add_torrent("111", str(self.tmp / "data"))
            window.load_and_display_torrents()
            self.assertEqual(window.torrent_list_widget.topLevelItemCount(), 1)
            self.assertEqual(window.torrent_list_widget.topLevelItem(0).text(1), "111")

            dialog = SettingsDialog(window)
            dialog.update_pac_status(
                {
                    "loaded": True,
                    "domains": 100,
                    "blocked_ips": 5,
                    "proxy": "https://proxy.test:8443",
                    "source": "test",
                    "age_seconds": 60,
                    "error": None,
                }
            )
            self.assertIn("загружен", dialog.pac_status.text())
            dialog.apply_to_config()
            self.assertEqual(dialog.windowTitle(), "Настройки Torrent Manager")
            self.assertTrue(dialog.bypass_enabled.isChecked())

        window.close()
        app.processEvents()

    def test_theme_toggle(self) -> None:
        from torrent_manager.bypass import BypassManager
        from torrent_manager.config import ConfigManager
        from torrent_manager.gui.window import TorrentApp

        app = QApplication.instance() or QApplication([])
        config = ConfigManager()
        with mock.patch.object(BypassManager, "refresh_in_background", lambda self: None), \
             mock.patch.object(BypassManager, "ensure_loaded", return_value=False):
            window = TorrentApp(config=config)
            theme_before = config.get("theme")
            window.toggle_theme()
            self.assertNotEqual(config.get("theme"), theme_before)
            self.assertTrue(window.theme_btn.text())
        window.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
