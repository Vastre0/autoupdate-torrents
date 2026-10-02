"""Тесты командного интерфейса."""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from torrent_manager.bypass import BypassManager
from torrent_manager.cli import main
from torrent_manager.service import TorrentService
from torrent_manager.torrents import RutrackerClient

from tests.test_service import FakeQBittorrent, FakeRutracker


class CliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="autoupdate-test-"))
        self.legacy = Path(tempfile.mkdtemp(prefix="autoupdate-legacy-"))
        self._saved = {name: os.environ.get(name) for name in (
            "AUTOUPDATE_TORRENTS_HOME", "AUTOUPDATE_TORRENTS_LEGACY_DIR")}
        os.environ["AUTOUPDATE_TORRENTS_HOME"] = str(self.tmp)
        os.environ["AUTOUPDATE_TORRENTS_LEGACY_DIR"] = str(self.legacy)

    def tearDown(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.legacy, ignore_errors=True)

    def run_cli(self, *args) -> tuple[int, str]:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue() + err.getvalue()

    def config(self) -> dict:
        return json.loads((self.tmp / "user-config.json").read_text(encoding="utf-8"))


class CliTests(CliTestCase):
    def test_version_and_help(self) -> None:
        with self.assertRaises(SystemExit) as context:
            self.run_cli("--help")
        self.assertEqual(context.exception.code, 0)

    def test_print_paths(self) -> None:
        code, output = self.run_cli("--print-paths")
        self.assertEqual(code, 0)
        self.assertIn(str(self.tmp), output)

    def test_import_cookies(self) -> None:
        code, output = self.run_cli("--import-cookies", "bb_session=abc; bb_ssl=1")
        self.assertEqual(code, 0)
        data = json.loads((self.tmp / "cookies.json").read_text(encoding="utf-8"))
        self.assertEqual(data["bb_session"], "abc")
        self.assertIn("Куки сохранены", output)

    def test_import_broken_cookies(self) -> None:
        code, _ = self.run_cli("--import-cookies", "просто текст без куки")
        self.assertEqual(code, 1)

    def test_set_qbittorrent(self) -> None:
        code, _ = self.run_cli("--set-qbittorrent", "10.0.0.5:8080", "user", "pass")
        self.assertEqual(code, 0)
        self.assertEqual(self.config()["qbittorrent"]["host"], "10.0.0.5:8080")

    def test_bypass_toggles(self) -> None:
        self.assertEqual(self.run_cli("--no-bypass")[0], 0)
        self.assertFalse(self.config()["bypass"]["enabled"])
        self.assertEqual(self.run_cli("--enable-bypass")[0], 0)
        self.assertTrue(self.config()["bypass"]["enabled"])

    def test_set_proxy(self) -> None:
        code, _ = self.run_cli("--set-proxy", "socks5://127.0.0.1:9050")
        self.assertEqual(code, 0)
        self.assertEqual(self.config()["bypass"]["manual_proxy"], "socks5://127.0.0.1:9050")

    def test_list_torrents(self) -> None:
        service = TorrentService(log=lambda message: None)
        service.add_torrent("111", "/data/one")
        code, output = self.run_cli("--list")
        self.assertEqual(code, 0)
        self.assertIn("111", output)
        self.assertIn("/data/one", output)

    def test_check_host_without_network(self) -> None:
        with mock.patch.object(BypassManager, "ensure_loaded", return_value=False):
            code, output = self.run_cli("--check-host", "rutracker.org")
        self.assertEqual(code, 0)
        self.assertIn("rutracker.org", output)
        self.assertIn("PAC-скрипт", output)

    def test_refresh_pac_failure_is_reported(self) -> None:
        with mock.patch.object(BypassManager, "refresh", return_value=False):
            code, _ = self.run_cli("--refresh-pac")
        self.assertEqual(code, 1)

    def test_check_command(self) -> None:
        self.run_cli("--import-cookies", "bb_session=abc")
        with mock.patch.object(TorrentService, "qbittorrent_test", return_value=(True, "ок")), \
             mock.patch.object(RutrackerClient, "check_connection", return_value=(True, "ок")), \
             mock.patch.object(BypassManager, "ensure_loaded", return_value=True):
            code, output = self.run_cli("--check")
        self.assertEqual(code, 0)
        self.assertIn("qBittorrent: OK", output)

    def test_update_command(self) -> None:
        self.run_cli("--import-cookies", "bb_session=abc")
        service = TorrentService(log=lambda message: None)
        service.add_torrent("111", "/data/one")

        with mock.patch.object(TorrentService, "_rutracker", return_value=FakeRutracker()), \
             mock.patch.object(TorrentService, "qbittorrent", return_value=FakeQBittorrent()):
            code, output = self.run_cli("--update")
        self.assertEqual(code, 0)
        self.assertIn("Обновлено: 1", output)

    def test_update_command_failure_exit_code(self) -> None:
        self.run_cli("--import-cookies", "bb_session=abc")
        service = TorrentService(log=lambda message: None)
        service.add_torrent("111", "/data/one")

        with mock.patch.object(TorrentService, "_rutracker", return_value=FakeRutracker(fail={"111"})), \
             mock.patch.object(TorrentService, "qbittorrent", return_value=FakeQBittorrent()):
            code, _ = self.run_cli("--update")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
