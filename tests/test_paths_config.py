"""Тесты XDG-путей, конфигов, куки и хранилища раздач."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from torrent_manager import paths
from torrent_manager.config import ConfigManager
from torrent_manager.cookies import (
    load_cookies,
    parse_cookie_string,
    save_cookies,
    validate_cookies,
)
from torrent_manager.torrent_store import TorrentStore


class TempHomeTestCase(unittest.TestCase):
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


class PathsTests(TempHomeTestCase):
    def test_directories_follow_env(self) -> None:
        self.assertEqual(paths.config_dir(), self.tmp)
        self.assertEqual(paths.cache_dir(), self.tmp)
        paths.ensure_dirs()
        self.assertTrue(paths.config_dir().is_dir())

    def test_legacy_file_is_copied(self) -> None:
        (self.legacy / "cookies.json").write_text('{"bb_session": "1"}', encoding="utf-8")
        resolved = paths.resolve_data_file("cookies.json")
        self.assertEqual(resolved.parent, self.tmp)
        self.assertTrue(resolved.is_file())
        self.assertEqual(json.loads(resolved.read_text(encoding="utf-8")), {"bb_session": "1"})

    def test_migrate_legacy_files(self) -> None:
        (self.legacy / "cookies.json").write_text("{}", encoding="utf-8")
        (self.legacy / "user-config.json").write_text("{}", encoding="utf-8")
        moved = paths.migrate_legacy_files()
        self.assertEqual(len(moved), 2)
        self.assertTrue((self.tmp / "cookies.json").is_file())
        self.assertTrue((self.tmp / "user-config.json").is_file())


class ConfigTests(TempHomeTestCase):
    def test_defaults_and_merge(self) -> None:
        ConfigManager().save()
        raw = json.loads((self.tmp / "user-config.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["theme"], "light")
        self.assertIn("bypass", raw)

        (self.tmp / "user-config.json").write_text(
            json.dumps({"theme": "dark", "bypass": {"enabled": False}}), encoding="utf-8"
        )
        config = ConfigManager()
        self.assertEqual(config.get("theme"), "dark")
        self.assertFalse(config.get_section("bypass")["enabled"])
        # Недостающие ключи добавляются из значений по умолчанию
        self.assertIn("pac_urls", config.get_section("bypass"))

    def test_corrupted_config_is_replaced(self) -> None:
        (self.tmp / "user-config.json").write_text("{это не json", encoding="utf-8")
        config = ConfigManager()
        self.assertEqual(config.get("theme"), "light")

    def test_config_permissions(self) -> None:
        config = ConfigManager()
        config.set("theme", "dark")
        config.save()
        mode = stat.S_IMODE((self.tmp / "user-config.json").stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_set_section_persists(self) -> None:
        config = ConfigManager()
        config.set_section("qbittorrent", {"host": "127.0.0.1:9090"})
        config.save()
        again = ConfigManager()
        self.assertEqual(again.get_section("qbittorrent")["host"], "127.0.0.1:9090")


class CookiesTests(TempHomeTestCase):
    def test_parse_devtools_string(self) -> None:
        text = "bb_session=abc; bb_ssl=1; opt_js=xyz; bb_guid=deadbeef"
        parsed = parse_cookie_string(text)
        self.assertEqual(parsed["bb_session"], "abc")
        self.assertEqual(parsed["bb_guid"], "deadbeef")

    def test_parse_json_and_multiline(self) -> None:
        self.assertEqual(parse_cookie_string('{"bb_session": "1"}'), {"bb_session": "1"})
        self.assertEqual(parse_cookie_string("bb_session=1\nbb_ssl=1"), {"bb_session": "1", "bb_ssl": "1"})
        self.assertEqual(parse_cookie_string(""), {})

    def test_validate(self) -> None:
        self.assertEqual(validate_cookies({"bb_session": "1"}), [])
        self.assertTrue(validate_cookies({"bb_ssl": "1"}))
        self.assertTrue(validate_cookies(None))

    def test_save_load_roundtrip(self) -> None:
        save_cookies({"bb_session": "123"})
        self.assertEqual(load_cookies(), {"bb_session": "123"})
        mode = stat.S_IMODE((self.tmp / "cookies.json").stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_missing_cookies(self) -> None:
        messages: list[str] = []
        self.assertIsNone(load_cookies(log=messages.append))
        self.assertTrue(messages)


class TorrentStoreTests(TempHomeTestCase):
    def test_add_update_remove(self) -> None:
        store = TorrentStore()
        self.assertTrue(store.add("111", "/data/a", "https://rutracker.org/forum/viewtopic.php?t=111"))
        self.assertFalse(store.add("111", "/data/b", "https://rutracker.org/forum/viewtopic.php?t=111"))
        self.assertEqual(store.get("111")["save_path"], "/data/b")
        self.assertEqual(len(store), 1)

        reloaded = TorrentStore()
        self.assertEqual(reloaded.get("111")["save_path"], "/data/b")
        self.assertTrue(reloaded.remove("111"))
        self.assertFalse(reloaded.remove("111"))
        self.assertEqual(len(reloaded), 0)

    def test_corrupted_file(self) -> None:
        (self.tmp / "torrent_config.json").write_text("не json", encoding="utf-8")
        store = TorrentStore()
        self.assertEqual(len(store), 0)
        self.assertTrue((self.tmp / "torrent_config.json").is_file())


if __name__ == "__main__":
    unittest.main()
