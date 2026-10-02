"""Тесты встроенного обхода блокировок (PAC-менеджер и кэш)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import requests

from torrent_manager.bypass import BypassManager
from torrent_manager.config import ConfigManager

from tests.pac_fixture import build_pac

PAC_URL = "https://antizapret.prostovpn.org:8443/proxy.pac"
PAC_URL_ALT = "https://antizapret.prostovpn.org:18443/proxy.pac"
PAC_URL_PLAIN = "https://antizapret.prostovpn.org/proxy.pac"
PAC_URL_CEN = "https://e.cen.rodeo:8443/proxy.pac"

RUTRACKER_PAC = build_pac({"org": ["rutracker"], "com": ["example"]})


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


class FakeSession:
    """Подменяет requests.Session: отвечает по заданной карте URL."""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.get(url)
        if result is None:
            raise requests.ConnectionError(f"нет доступа к {url}")
        if isinstance(result, Exception):
            raise result
        if isinstance(result, FakeResponse):
            return result
        return FakeResponse(str(result))


class BypassTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="autoupdate-test-"))
        self._env = os.environ.get("AUTOUPDATE_TORRENTS_HOME")
        os.environ["AUTOUPDATE_TORRENTS_HOME"] = str(self.tmp)
        self.config = ConfigManager()
        self.config.save()

    def tearDown(self) -> None:
        if self._env is None:
            os.environ.pop("AUTOUPDATE_TORRENTS_HOME", None)
        else:
            os.environ["AUTOUPDATE_TORRENTS_HOME"] = self._env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _manager(self, session) -> BypassManager:
        return BypassManager(self.config, log=lambda message: None, session=session)


class BypassTests(BypassTestCase):
    def test_refresh_and_detect(self) -> None:
        session = FakeSession({PAC_URL: RUTRACKER_PAC, PAC_URL_CEN: RUTRACKER_PAC})
        manager = self._manager(session)
        self.assertTrue(manager.refresh(force=True))

        status = manager.status()
        self.assertTrue(status["loaded"])
        self.assertEqual(status["source"], PAC_URL)
        self.assertEqual(status["proxy"], "https://proxy.antizapret.test:8443")
        self.assertGreater(status["domains"], 0)

        proxies = manager.proxies_for_url("https://rutracker.org/forum/index.php")
        self.assertIsNotNone(proxies)
        self.assertEqual(proxies["https"], "https://proxy.antizapret.test:8443")

        self.assertIsNone(manager.proxies_for_url("https://unknown.example/"))

    def test_prefer_plain_proxy(self) -> None:
        self.config.set_section("bypass", {"prefer_https_proxy": False})
        session = FakeSession({PAC_URL: RUTRACKER_PAC})
        manager = self._manager(session)
        manager.refresh(force=True)
        proxies = manager.proxies_for_url("https://rutracker.org/forum/index.php")
        self.assertEqual(proxies["https"], "http://proxy.antizapret.test:8080")

    def test_mirror_fallback(self) -> None:
        session = FakeSession({PAC_URL_PLAIN: RUTRACKER_PAC})
        manager = self._manager(session)
        self.assertTrue(manager.refresh(force=True))
        self.assertEqual(manager.status()["source"], PAC_URL_PLAIN)
        self.assertEqual(len(session.calls), 3)

    def test_cache_is_used(self) -> None:
        session = FakeSession({PAC_URL: RUTRACKER_PAC})
        manager = self._manager(session)
        manager.refresh(force=True)
        self.assertTrue(manager.cache_is_fresh())

        offline = self._manager(FakeSession({}))
        self.assertTrue(offline.ensure_loaded(background_refresh=False))
        self.assertTrue(offline.status()["loaded"])
        self.assertIsNotNone(offline.proxies_for_url("https://rutracker.org/"))

    def test_all_mirrors_fail(self) -> None:
        manager = self._manager(FakeSession({}))
        self.assertFalse(manager.refresh(force=True))
        self.assertIn("Не удалось скачать PAC", manager.status()["error"] or "")

    def test_geoblock_message(self) -> None:
        text = "Your geoip is not RU, contact antizapret@prostovpn.org"
        manager = self._manager(FakeSession({url: text for url in (
            PAC_URL, PAC_URL_ALT, PAC_URL_PLAIN, PAC_URL_CEN)}))
        self.assertFalse(manager.refresh(force=True))
        self.assertIn("России", manager.status()["error"] or "")

    def test_manual_proxy_fallback(self) -> None:
        self.config.set_section("bypass", {"manual_proxy": "socks5://127.0.0.1:9050"})
        manager = self._manager(FakeSession({}))
        fallback = manager.fallback_proxies("rutracker.org")
        self.assertEqual(fallback, {"http": "socks5://127.0.0.1:9050",
                                    "https": "socks5://127.0.0.1:9050"})

    def test_disabled_bypass(self) -> None:
        session = FakeSession({PAC_URL: RUTRACKER_PAC})
        manager = self._manager(session)
        manager.refresh(force=True)
        self.config.set_section("bypass", {"enabled": False})
        self.assertIsNone(manager.proxies_for_url("https://rutracker.org/"))
        self.assertIsNone(manager.fallback_proxies("rutracker.org"))
        self.assertIn("выключен", manager.describe_host("rutracker.org"))

    def test_describe_host(self) -> None:
        session = FakeSession({PAC_URL: RUTRACKER_PAC})
        manager = self._manager(session)
        manager.refresh(force=True)
        self.assertIn("прокси", manager.describe_host("rutracker.org"))

    def test_broken_pac_is_rejected(self) -> None:
        manager = self._manager(FakeSession({url: "<html>не PAC</html>" for url in (
            PAC_URL, PAC_URL_ALT, PAC_URL_PLAIN, PAC_URL_CEN)}))
        self.assertFalse(manager.refresh(force=True))
        self.assertIsNotNone(manager.status()["error"])

    def test_rate_limit_prevents_hammering(self) -> None:
        session = FakeSession({})  # все зеркала недоступны
        manager = self._manager(session)
        self.assertFalse(manager.refresh(force=True))
        calls_after_first = len(session.calls)
        self.assertGreater(calls_after_first, 0)

        # Повторная попытка «раньше, чем через минуту» не должна дёргать зеркала
        self.assertFalse(manager.refresh(force=True, min_interval=60))
        self.assertEqual(len(session.calls), calls_after_first)

        # Явное обновление (кнопка/CLI) интервал игнорирует
        manager.refresh(force=True)
        self.assertGreater(len(session.calls), calls_after_first)

    def test_host_from_url(self) -> None:
        self.assertEqual(BypassManager.host_from_url("https://rutracker.org:443/x?y=1"), "rutracker.org")
        self.assertEqual(BypassManager.host_from_url("http://127.0.0.1:8080/"), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
