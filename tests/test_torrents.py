"""Тесты клиента rutracker: маршруты «напрямую/через прокси» и разбор страниц."""

from __future__ import annotations

import unittest

import requests

from torrent_manager.torrents import (
    QBittorrentClient,
    RutrackerClient,
    RutrackerError,
    extract_torrent_id,
    looks_blocked,
    topic_url,
)

TOPIC_HTML = """
<html><body><a class="dl-link" href="dl.php?t=123">Скачать .torrent</a></body></html>
"""
LOGIN_HTML = "<html><body><form>Вход: введите ваше имя</form></body></html>"
BLOCK_HTML = "<html><body>Доступ ограничен: сайт внесён в единый реестр</body></html>"


class FakeResponse:
    def __init__(self, text: str = "", content: bytes = b"", status_code: int = 200, url: str = ""):
        self.text = text
        self.content = content or text.encode("utf-8")
        self.status_code = status_code
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Сессия, отдающая заранее заданные ответы по порядку вызовов."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.headers: dict[str, str] = {}
        self.cookies = _CookieJar()

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _CookieJar:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []

    def set(self, name: str, value: str, domain: str | None = None) -> None:
        self.items.append((name, value, domain or ""))


class FakeBypass:
    def __init__(self, pac_proxy: str | None = None, fallback: str | None = None, enabled: bool = True):
        self.enabled = enabled
        self.pac_proxy = pac_proxy
        self.fallback = fallback

    def proxies_for_url(self, url: str):
        return {"http": self.pac_proxy, "https": self.pac_proxy} if self.pac_proxy else None

    def fallback_proxies(self, host: str):
        return {"http": self.fallback, "https": self.fallback} if self.fallback else None

    @staticmethod
    def host_from_url(url: str) -> str:
        return url.split("/")[2]


def make_client(session: FakeSession, bypass: FakeBypass | None = None) -> RutrackerClient:
    client = RutrackerClient({"bb_session": "secret"}, bypass=bypass, log=lambda message: None)
    client.session = session
    for name, value in client.cookies.items():
        session.cookies.set(name, value, domain=".rutracker.org")
    return client


class ExtractTorrentIdTests(unittest.TestCase):
    def test_variants(self) -> None:
        self.assertEqual(extract_torrent_id("https://rutracker.org/forum/viewtopic.php?t=123456"), "123456")
        self.assertEqual(extract_torrent_id("https://rutracker.org/forum/viewtopic.php?p=1&t=99"), "99")
        self.assertEqual(extract_torrent_id("654321"), "654321")

    def test_invalid(self) -> None:
        with self.assertRaises(ValueError):
            extract_torrent_id("https://rutracker.org/forum/index.php")

    def test_topic_url(self) -> None:
        self.assertEqual(topic_url("7"), "https://rutracker.org/forum/viewtopic.php?t=7")


class RutrackerClientTests(unittest.TestCase):
    def test_download_direct(self) -> None:
        session = FakeSession([FakeResponse(TOPIC_HTML), FakeResponse(content=b"torrent-bytes")])
        client = make_client(session, FakeBypass())
        content, url = client.download_torrent("123")
        self.assertEqual(content, b"torrent-bytes")
        self.assertEqual(url, topic_url("123"))
        self.assertIsNone(session.calls[0]["proxies"])

    def test_download_via_pac_proxy(self) -> None:
        session = FakeSession([FakeResponse(TOPIC_HTML), FakeResponse(content=b"data")])
        client = make_client(session, FakeBypass(pac_proxy="https://proxy.test:8443"))
        client.download_torrent("123")
        self.assertEqual(session.calls[0]["proxies"]["https"], "https://proxy.test:8443")
        # ссылка на .torrent абсолютная — прокси применяется и ко второму запросу
        self.assertEqual(session.calls[1]["proxies"]["https"], "https://proxy.test:8443")

    def test_retry_through_fallback_proxy(self) -> None:
        session = FakeSession([
            requests.ConnectionError("соединение сброшено"),
            FakeResponse(TOPIC_HTML),
            FakeResponse(content=b"data"),
        ])
        client = make_client(session, FakeBypass(fallback="https://proxy.test:8443"))
        client.download_torrent("123")
        self.assertEqual(len(session.calls), 3)
        self.assertIsNone(session.calls[0]["proxies"])
        self.assertEqual(session.calls[1]["proxies"]["https"], "https://proxy.test:8443")

    def test_blocked_stub_triggers_proxy(self) -> None:
        session = FakeSession([
            FakeResponse(BLOCK_HTML, status_code=451),
            FakeResponse(TOPIC_HTML),
            FakeResponse(content=b"data"),
        ])
        client = make_client(session, FakeBypass(fallback="https://proxy.test:8443"))
        content, _ = client.download_torrent("123")
        self.assertEqual(content, b"data")
        self.assertEqual(session.calls[1]["proxies"]["https"], "https://proxy.test:8443")

    def test_login_page_raises(self) -> None:
        session = FakeSession([FakeResponse(LOGIN_HTML)])
        client = make_client(session, FakeBypass())
        with self.assertRaises(RutrackerError) as context:
            client.download_torrent("123")
        self.assertIn("куки", str(context.exception).lower())

    def test_all_routes_failed(self) -> None:
        session = FakeSession([
            requests.ConnectionError("нет сети"),
            requests.ConnectionError("нет сети"),
        ])
        client = make_client(session, FakeBypass(fallback="https://proxy.test:8443"))
        with self.assertRaises(RutrackerError):
            client.download_torrent("123")

    def test_cookies_are_set_for_domain(self) -> None:
        session = FakeSession([])
        make_client(session, None)
        self.assertIn(("bb_session", "secret", ".rutracker.org"), session.cookies.items)

    def test_check_connection(self) -> None:
        session = FakeSession([FakeResponse("<html>Личный раздел</html>")])
        client = make_client(session, None)
        ok, message = client.check_connection()
        self.assertTrue(ok)
        self.assertIn("работает", message)

    def test_looks_blocked(self) -> None:
        self.assertTrue(looks_blocked(BLOCK_HTML))
        self.assertFalse(looks_blocked(TOPIC_HTML))


class QBittorrentClientTests(unittest.TestCase):
    def test_host_building(self) -> None:
        client = QBittorrentClient({"host": "localhost:8080"})
        self.assertEqual(client.host, "http://localhost:8080")
        client = QBittorrentClient({"host": "localhost:8080", "use_https": True})
        self.assertEqual(client.host, "https://localhost:8080")
        client = QBittorrentClient({"host": "https://box:8080"})
        self.assertEqual(client.host, "https://box:8080")


if __name__ == "__main__":
    unittest.main()
