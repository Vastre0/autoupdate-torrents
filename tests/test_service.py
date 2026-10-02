"""Тесты прикладного слоя (TorrentService)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from torrent_manager.config import ConfigManager
from torrent_manager.service import TorrentService
from torrent_manager.torrents import QBittorrentError, RutrackerError


class FakeRutracker:
    def __init__(self, fail: set[str] | None = None):
        self.fail = fail or set()
        self.requests: list[str] = []

    def download_torrent(self, topic_id: str):
        self.requests.append(topic_id)
        if topic_id in self.fail:
            raise RutrackerError("не удалось скачать .torrent")
        return b"d4:infodata", f"https://rutracker.org/forum/viewtopic.php?t={topic_id}"

    def check_connection(self):
        return True, "Соединение с rutracker работает, куки действительны."


class FakeQBittorrent:
    def __init__(self):
        self.added: list[tuple[str, str]] = []
        self.deleted: list[tuple[str, bool]] = []

    def test(self):
        return True, "Подключено к qBittorrent 5.0 (http://localhost:8080)"

    def add_torrent(self, content: bytes, save_path: str, comment: str) -> bool:
        self.added.append((save_path, comment))
        return True

    def find_hash_by_topic(self, topic_id: str):
        return "deadbeef" if topic_id == "111" else None

    def delete_torrent(self, torrent_hash: str, delete_files: bool) -> bool:
        self.deleted.append((torrent_hash, delete_files))
        return True


class ServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="autoupdate-test-"))
        self._env = os.environ.get("AUTOUPDATE_TORRENTS_HOME")
        os.environ["AUTOUPDATE_TORRENTS_HOME"] = str(self.tmp)
        self.messages: list[str] = []
        self.config = ConfigManager()
        self.service = TorrentService(config=self.config, log=self.messages.append)
        self.service.import_cookies("bb_session=secret; bb_ssl=1")

    def tearDown(self) -> None:
        if self._env is None:
            os.environ.pop("AUTOUPDATE_TORRENTS_HOME", None)
        else:
            os.environ["AUTOUPDATE_TORRENTS_HOME"] = self._env
        shutil.rmtree(self.tmp, ignore_errors=True)


class ServiceTests(ServiceTestCase):
    def test_import_cookies(self) -> None:
        self.assertTrue(self.service.has_cookies())
        self.assertTrue((self.tmp / "cookies.json").is_file())

    def test_add_and_list(self) -> None:
        result = self.service.add_torrent("https://rutracker.org/forum/viewtopic.php?t=111", "/data/one")
        self.assertEqual(result["topic_id"], "111")
        self.assertTrue(result["is_new"])

        self.service.add_torrent("222", "/data/two")
        tracked = self.service.list_tracked()
        self.assertEqual(len(tracked), 2)
        names = {item["topic_id"]: item["name"] for item in tracked}
        self.assertEqual(names["111"], "one")
        self.assertEqual(names["222"], "two")

    def test_add_requires_url_and_path(self) -> None:
        with self.assertRaises(ValueError):
            self.service.add_torrent("", "/data")
        with self.assertRaises(ValueError):
            self.service.add_torrent("https://rutracker.org/forum/viewtopic.php?t=1", "")

    def test_update_all(self) -> None:
        self.service.add_torrent("111", "/data/one")
        self.service.add_torrent("222", "/data/two")
        rutracker = FakeRutracker()
        qbittorrent = FakeQBittorrent()

        with mock.patch.object(self.service, "_rutracker", return_value=rutracker), \
             mock.patch.object(self.service, "qbittorrent", return_value=qbittorrent):
            result = self.service.update_all()

        self.assertEqual(sorted(result.updated), ["111", "222"])
        self.assertFalse(result.failed)
        self.assertTrue(result.ok())
        self.assertEqual(len(qbittorrent.added), 2)
        self.assertEqual(qbittorrent.added[0][1], "https://rutracker.org/forum/viewtopic.php?t=111")
        self.assertIn("Обновлено: 2", result.summary())

    def test_update_all_with_failure(self) -> None:
        self.service.add_torrent("111", "/data/one")
        self.service.add_torrent("222", "/data/two")
        rutracker = FakeRutracker(fail={"222"})
        qbittorrent = FakeQBittorrent()

        with mock.patch.object(self.service, "_rutracker", return_value=rutracker), \
             mock.patch.object(self.service, "qbittorrent", return_value=qbittorrent):
            result = self.service.update_all()

        self.assertEqual(result.updated, ["111"])
        self.assertEqual(result.failed[0][0], "222")
        self.assertFalse(result.ok())

    def test_update_without_torrents(self) -> None:
        result = self.service.update_all()
        self.assertEqual(result.total, 0)
        self.assertTrue(any("пуст" in message for message in self.messages))

    def test_update_without_qbittorrent(self) -> None:
        self.service.add_torrent("111", "/data/one")
        with mock.patch.object(self.service, "_rutracker", return_value=FakeRutracker()), \
             mock.patch.object(self.service, "qbittorrent",
                               return_value=mock.Mock(test=lambda: (False, "нет связи"))):
            with self.assertRaises(QBittorrentError):
                self.service.update_all()

    def test_remove_torrent(self) -> None:
        self.service.add_torrent("111", "/data/one")
        qbittorrent = FakeQBittorrent()
        with mock.patch.object(self.service, "qbittorrent", return_value=qbittorrent):
            self.assertTrue(self.service.remove_torrent("111", delete_files=True))
        self.assertEqual(qbittorrent.deleted, [("deadbeef", True)])
        self.assertEqual(self.service.list_tracked(), [])

    def test_remove_missing_torrent_from_store(self) -> None:
        qbittorrent = FakeQBittorrent()
        with mock.patch.object(self.service, "qbittorrent", return_value=qbittorrent):
            self.assertFalse(self.service.remove_torrent("999"))
        self.assertTrue(any("не найден" in message for message in self.messages))

    def test_diagnostics(self) -> None:
        with mock.patch.object(self.service, "qbittorrent_test", return_value=(True, "ок")), \
             mock.patch("torrent_manager.service.RutrackerClient.check_connection",
                        return_value=(True, "ок")), \
             mock.patch.object(self.service.bypass, "ensure_loaded", return_value=False):
            report = self.service.diagnostics()

        self.assertTrue(report["cookies"]["ok"])
        self.assertTrue(report["qbittorrent"]["ok"])
        self.assertTrue(report["rutracker"]["ok"])
        self.assertIn("config", report["paths"])

    def test_bypass_status_keys(self) -> None:
        status = self.service.bypass_status()
        for key in ("enabled", "loaded", "proxy", "domains", "manual_proxy", "error"):
            self.assertIn(key, status)


if __name__ == "__main__":
    unittest.main()
