"""Интеграционный тест: PAC → прокси → rutracker → qBittorrent (без внешней сети).

Поднимается локальный HTTP-сервер, который одновременно играет роль
зеркала PAC-скрипта и прокси Антизапрета, и проверяется, что запросы к
«заблокированному» хосту действительно уходят через прокси.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from torrent_manager.bypass import BypassManager
from torrent_manager.config import ConfigManager
from torrent_manager.torrents import RutrackerClient

from tests.pac_fixture import build_pac

TOPIC_HTML = """
<html><body><a class="dl-link" href="dl.php?t=123">Скачать .torrent</a></body></html>
"""
TORRENT_BYTES = b"d8:announce20:http://tracker/announce4:infod4:name4:testee"


class Handler(BaseHTTPRequestHandler):
    """Отвечает на PAC-запросы, на «прокси»-запросы и на обычные страницы."""

    server_version = "TestHTTP/1.0"

    def log_message(self, *args):  # noqa: D102 - отключаем шум в тестах
        pass

    def do_GET(self) -> None:  # noqa: N802 - HTTP-метод
        server = self.server
        path = self.path
        if path.endswith("proxy.pac"):
            server.requests.append(("pac", path))  # type: ignore[attr-defined]
            body = server.pac_text.encode("utf-8")  # type: ignore[attr-defined]
            self._respond(body, "application/x-ns-proxy-autoconfig")
            return

        # Прокси получает абсолютный URL, прямое соединение — путь вида /forum/...
        through_proxy = path.startswith("http://")
        server.requests.append(("proxy" if through_proxy else "direct", path))  # type: ignore[attr-defined]

        if "viewtopic.php" in path:
            self._respond(TOPIC_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif "dl.php" in path:
            self._respond(TORRENT_BYTES, "application/x-bittorrent")
        else:
            self._respond(b"not found", "text/plain", status=404)

    def _respond(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class IntegrationBypassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.server.requests = []  # type: ignore[attr-defined]
        cls.server.pac_text = build_pac(  # type: ignore[attr-defined]
            {"org": ["rutracker"]},
            blocked_ips=["127.0.0.1"],
            proxy_https=f"127.0.0.1:{cls.port}",
            proxy_http=f"127.0.0.1:{cls.port}",
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="autoupdate-test-"))
        self._env = os.environ.get("AUTOUPDATE_TORRENTS_HOME")
        os.environ["AUTOUPDATE_TORRENTS_HOME"] = str(self.tmp)
        self.config = ConfigManager()
        self.config.set_section(
            "bypass",
            {
                "enabled": True,
                "prefer_https_proxy": False,
                "pac_urls": [f"http://127.0.0.1:{self.port}/proxy.pac"],
            },
        )
        self.server.requests.clear()  # type: ignore[attr-defined]
        self.base = f"http://127.0.0.1:{self.port}/forum/"

    def tearDown(self) -> None:
        if self._env is None:
            os.environ.pop("AUTOUPDATE_TORRENTS_HOME", None)
        else:
            os.environ["AUTOUPDATE_TORRENTS_HOME"] = self._env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_traffic_goes_through_proxy(self) -> None:
        bypass = BypassManager(self.config, log=lambda message: None)
        self.assertTrue(bypass.refresh(force=True))
        self.assertTrue(bypass.proxies_for_url(self.base + "viewtopic.php?t=123"))

        client = RutrackerClient({"bb_session": "secret"}, bypass=bypass, log=lambda message: None)
        with mock.patch("torrent_manager.torrents.RUTRACKER_BASE", self.base):
            content, url = client.download_torrent("123")

        self.assertEqual(content, TORRENT_BYTES)
        self.assertTrue(url.startswith(self.base))

        kinds = [kind for kind, _ in self.server.requests]  # type: ignore[attr-defined]
        self.assertIn("proxy", kinds)
        self.assertNotIn("direct", kinds)

    def test_direct_when_bypass_disabled(self) -> None:
        self.config.set_section("bypass", {"enabled": False})
        bypass = BypassManager(self.config, log=lambda message: None)

        client = RutrackerClient({"bb_session": "secret"}, bypass=bypass, log=lambda message: None)
        with mock.patch("torrent_manager.torrents.RUTRACKER_BASE", self.base):
            client.download_torrent("123")

        kinds = [kind for kind, _ in self.server.requests]  # type: ignore[attr-defined]
        self.assertIn("direct", kinds)
        self.assertNotIn("proxy", kinds)

    def test_fallback_proxy_when_direct_fails(self) -> None:
        # PAC не загружен, но задан резервный прокси: первый запрос идёт
        # напрямую и падает, второй — через прокси.
        self.config.set_section("bypass", {"pac_urls": ["http://127.0.0.1:1/proxy.pac"]})
        self.config.set_section("bypass", {"manual_proxy": f"http://127.0.0.1:{self.port}"})
        bypass = BypassManager(self.config, log=lambda message: None)

        client = RutrackerClient({"bb_session": "secret"}, bypass=bypass, log=lambda message: None)
        real_get = client.session.get

        def flaky_get(url, **kwargs):
            if not kwargs.get("proxies"):
                raise __import__("requests").ConnectionError("имитация блокировки провайдером")
            return real_get(url, **kwargs)

        with mock.patch.object(client.session, "get", side_effect=flaky_get), \
             mock.patch("torrent_manager.torrents.RUTRACKER_BASE", self.base):
            content, _ = client.download_torrent("123")

        self.assertEqual(content, TORRENT_BYTES)
        kinds = [kind for kind, _ in self.server.requests]  # type: ignore[attr-defined]
        self.assertIn("proxy", kinds)


if __name__ == "__main__":
    unittest.main()
