"""Тесты разбора PAC-скриптов Антизапрета."""

from __future__ import annotations

import random
import unittest

from torrent_manager.antizapret import (
    PacError,
    clear_dns_cache,
    dns_resolve,
    parse_pac,
    pattern_replace,
    pattern_restore,
    unlzp,
)

from tests.pac_fixture import build_pac, lzp_encode

DOMAINS = {
    "com": ["example", "aaa", "rutracker"],
    "org": ["rutracker", "test"],
    "ru": ["megafon"],
    # Для зон вида co.uk в PAC хранится зона «uk» и префикс «shop.co»
    "uk": ["shop.co"],
    "net": ["seedbox"],
}
PATTERNS_DOMAINS = {"!": "mega"}
BLOCKED_IPS = ["203.0.113.5", "198.51.100.7"]
SPECIAL = [("192.0.2.0", 24)]


class LzpTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        payloads = [
            b"abcdefgh" * 4,
            b"aaaaaaaabbbbbbbb" * 8,
            bytes(random.Random(1).randrange(256) for _ in range(64)),
            ("example.com" * 40).encode("ascii"),
        ]
        for payload in payloads:
            with self.subTest(payload=payload[:16]):
                data, mask = lzp_encode(payload)
                decoded, _, _, _ = unlzp(data, mask, limit=1 << 30)
                self.assertEqual(decoded, payload)

    def test_patterns_helpers(self) -> None:
        self.assertEqual(pattern_replace("megafon", {"!": "mega"}), "!fon")
        self.assertEqual(pattern_restore("!fon", {"!": "mega"}), "megafon")
        # Для маски длинная последовательность — ключ.
        self.assertEqual(pattern_restore("AABx", {"AAB": "~"}), "~x")
        self.assertEqual(pattern_replace("~x", {"AAB": "~"}), "AABx")


class PacParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = build_pac(
            DOMAINS,
            blocked_ips=BLOCKED_IPS,
            special=SPECIAL,
            patterns_domains=PATTERNS_DOMAINS,
        )
        cls.pac = parse_pac(cls.text, source="test://pac")

    def setUp(self) -> None:
        clear_dns_cache()

    def test_proxy_urls(self) -> None:
        self.assertEqual(self.pac.proxy_https, "https://proxy.antizapret.test:8443")
        self.assertEqual(self.pac.proxy_http, "http://proxy.antizapret.test:8080")
        self.assertEqual(self.pac.proxy_url(), "https://proxy.antizapret.test:8443")
        self.assertEqual(self.pac.proxy_url(prefer_https=False), "http://proxy.antizapret.test:8080")

    def test_domain_list(self) -> None:
        # 8 фрагментов; «megafon» сжимается до «!fon» (подстановка шаблонов)
        self.assertEqual(self.pac.domain_count, 8)
        self.assertEqual(self.pac.domains["com"][7], {"example"})
        self.assertEqual(self.pac.domains["com"][3], {"aaa"})
        self.assertEqual(self.pac.domains["com"][9], {"rutracker"})
        self.assertEqual(self.pac.domains["uk"][7], {"shop.co"})
        self.assertIn("!fon", self.pac.domains["ru"][4])
        self.assertEqual(self.pac.stats["domains"], 8)
        self.assertFalse(self.pac.stats["truncated"])

    def test_three_part_suffixes_extracted(self) -> None:
        self.assertIsNotNone(self.pac.three_part_suffixes)
        self.assertTrue(self.pac.three_part_suffixes.search("shop.co.uk"))
        self.assertFalse(self.pac.three_part_suffixes.search("example.com"))

    def test_blocked_ips_and_networks(self) -> None:
        self.assertEqual(len(self.pac.blocked_ips), 2)
        self.assertEqual(len(self.pac.special), 1)

    def test_detection_domains(self) -> None:
        for host in ("example.com", "www.example.com", "sub.aaa.com", "rutracker.org"):
            with self.subTest(host=host):
                self.assertTrue(self.pac.needs_proxy(host, resolve=False))
                self.assertEqual(
                    self.pac.proxy_for_host(host, resolve=False),
                    "https://proxy.antizapret.test:8443",
                )

    def test_detection_pattern_substitution(self) -> None:
        self.assertIn("!fon", self.pac.domains["ru"][4])
        self.assertTrue(self.pac.needs_proxy("megafon.ru", resolve=False))

    def test_detection_three_part_zone(self) -> None:
        # Трёхчастные зоны (co.uk) обрабатываются отдельным правилом PAC:
        # хост сводится к «последние три метки», зона — «uk».
        self.assertTrue(self.pac.needs_proxy("shop.co.uk", resolve=False))
        self.assertTrue(self.pac.needs_proxy("www.shop.co.uk", resolve=False))
        self.assertTrue(self.pac.needs_proxy("cdn.shop.co.uk", resolve=False))
        self.assertFalse(self.pac.needs_proxy("other.co.uk", resolve=False))

    def test_detection_ip_and_networks(self) -> None:
        self.assertTrue(self.pac.needs_proxy("203.0.113.5", resolve=False))
        self.assertTrue(self.pac.needs_proxy("198.51.100.7", resolve=False))
        self.assertTrue(self.pac.needs_proxy("192.0.2.42", resolve=False))
        self.assertFalse(self.pac.needs_proxy("203.0.113.6", resolve=False))

    def test_reasons(self) -> None:
        self.assertEqual(self.pac.explain("example.com", resolve=False), (True, "domain"))
        self.assertEqual(self.pac.explain("203.0.113.5", resolve=False), (True, "ip"))
        self.assertTrue(self.pac.explain("192.0.2.42", resolve=False)[1].startswith("net:"))
        self.assertEqual(self.pac.explain("example.net", resolve=False), (False, ""))

    def test_host_with_port_and_www(self) -> None:
        self.assertTrue(self.pac.needs_proxy("example.com:443", resolve=False))
        self.assertTrue(self.pac.needs_proxy("WWW.Example.COM", resolve=False))
        self.assertFalse(self.pac.needs_proxy("example.xyz", resolve=False))

    def test_dns_check_disabled(self) -> None:
        self.assertFalse(self.pac.needs_proxy("unknown-host.invalid", resolve=False))

    def test_dns_resolve_cached(self) -> None:
        clear_dns_cache()
        first = dns_resolve("localhost")
        second = dns_resolve("localhost")
        self.assertEqual(first, second)

    def test_explain_text(self) -> None:
        from torrent_manager.antizapret import describe

        self.assertIn("прокси", describe("example.com", self.pac, resolve=False))
        self.assertIn("не заблокирован", describe("example.net", self.pac, resolve=False))


class PacVariantsTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_dns_cache()

    def test_mask_patterns_are_used(self) -> None:
        text = build_pac({"com": ["example", "aaa"]}, patterns_mask={"AA": "~"})
        self.assertIn("~", text.split('var mask_lzp = "')[1].split('";')[0])
        pac = parse_pac(text)
        self.assertTrue(pac.needs_proxy("example.com", resolve=False))

    def test_extra_tail_bytes(self) -> None:
        # Длина потока не кратна 8: последняя неполная группа маски теряется,
        # но разбор не должен падать.
        text = build_pac({"com": ["exam", "aaa", "bbb", "ccc", "ddd"]})
        pac = parse_pac(text)
        self.assertGreaterEqual(pac.domain_count, 4)
        self.assertTrue(pac.needs_proxy("exam.com", resolve=False))

    def test_named_patterns(self) -> None:
        text = build_pac({"ru": ["megafon"]}, patterns_domains={"!": "mega"}).replace(
            "var patterns = {'!': 'mega'};", "var patterns_domains_lzp = {'!': 'mega'};"
        ).replace("var patterns = {};", "var patterns_mask_lzp = {};")
        pac = parse_pac(text)
        self.assertTrue(pac.needs_proxy("megafon.ru", resolve=False))

    def test_broken_pac(self) -> None:
        with self.assertRaises(PacError):
            parse_pac("здесь нет PAC-скрипта")

    def test_missing_proxy(self) -> None:
        text = build_pac({"com": ["example"]}).replace(
            'return "HTTPS proxy.antizapret.test:8443; PROXY proxy.antizapret.test:8080; DIRECT";',
            'return "DIRECT";',
        )
        with self.assertRaises(PacError):
            parse_pac(text)


if __name__ == "__main__":
    unittest.main()
