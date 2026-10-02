"""Разбор PAC-скриптов Антизапрета (antizapret).

Модуль реализует тот же принцип обхода блокировок, что и расширение
«Обход блокировок Рунета» (ilyaigpetrov, GPL-3.0): PAC-скрипт содержит
списки заблокированных доменов и IP-адресов, а также адрес прокси, через
который нужно ходить только на заблокированные ресурсы.

Формат PAC-файла (и LZP-сжатие списков доменов) описан в проектах:

* https://github.com/anticensority/runet-censorship-bypass
* https://bitbucket.org/anticensority/antizapret-pac-generator-light

Реализация здесь независимая, но совместимая по формату — это позволяет
приложению самому скачивать PAC-скрипт и определять, какие запросы нужно
пускать через прокси, без участия браузера.
"""

from __future__ import annotations

import base64
import ipaddress
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Mapping

# Параметры LZP (PPP compression / LZ Prediction by Charles Bloom).
TABLE_LEN_BITS = 18
HASH_MASK = (1 << TABLE_LEN_BITS) - 1

_DOMAINS_RE = re.compile(r"(?s)domains\s*=\s*\{(.*?)\}\s*;")
_SPECIAL_RE = re.compile(r"(?s)var\s+special\s*=\s*\[(.*?)\]\s*;")
_PATTERNS_BLOCK_RE = re.compile(r"(?s)var\s+patterns(?:_(\w+))?\s*=\s*\{(.*?)\}\s*;")
_PROXY_RETURN_RE = re.compile(r'return\s+"([^"]*)"')
_TLD_ENTRY_RE = re.compile(r'"([^"]+)"\s*:\s*\{([^}]*)\}')
_PATTERN_PAIR_RE = re.compile(r"""['"]([^'"]*)['"]\s*:\s*['"]([^'"]*)['"]""")
_SPECIAL_ENTRY_RE = re.compile(r"""\[\s*['"]([0-9.]+)['"]\s*,\s*(\d+)\s*\]""")
_TEST_HOST_RE = re.compile(r"\.test\(\s*host\s*\)")


class PacError(ValueError):
    """PAC-скрипт не удалось разобрать."""


# --------------------------------------------------------------------------- LZP


def unlzp(
    data: bytes,
    mask: bytes,
    limit: int,
    table: bytearray | None = None,
    hash_value: int = 0,
) -> tuple[bytes, int, int, int]:
    """Распаковка LZP-потока (совместима с ``lzp.py`` Антизапрета).

    Возвращает ``(данные, позиция в data, позиция в mask, hash)``, чтобы
    распаковку можно было продолжать по частям.
    """
    out = bytearray()
    if table is None:
        table = bytearray(1 << TABLE_LEN_BITS)

    data_pos = 0
    mask_pos = 0
    data_len = len(data)
    mask_len = len(mask)
    pending = b""

    while mask_pos < mask_len:
        mask_value = mask[mask_pos]
        mask_pos += 1
        group = bytearray()
        for bit in range(8):
            if mask_value & (1 << bit):
                char = table[hash_value]
            else:
                if data_pos >= data_len:
                    break
                char = data[data_pos]
                data_pos += 1
                table[hash_value] = char
            group.append(char)
            hash_value = ((hash_value << 7) ^ char) & HASH_MASK
        if len(group) == 8:
            out += group
            pending = b""
        else:
            # Неполная группа сохраняется до конца потока — так же ведёт себя
            # эталонная реализация.
            pending = bytes(group)
        if len(out) >= limit:
            break

    out += pending
    return bytes(out), data_pos, mask_pos, hash_value


def pattern_replace(text: str, patterns: Mapping[str, str]) -> str:
    """Заменяет длинные последовательности на короткие (сжатие доменов)."""
    for key, value in patterns.items():
        if value:
            text = text.replace(value, key)
    return text


def pattern_restore(text: str, patterns: Mapping[str, str]) -> str:
    """Обратная к :func:`pattern_replace` операция (для отладки)."""
    for key, value in patterns.items():
        text = text.replace(key, value)
    return text


# ------------------------------------------------------------------------ разбор


_ESCAPE_MAP = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "\\": "\\", "\n": "", "\r": ""}


def unescape_js_string(raw: str) -> str:
    """Раскрывает escape-последовательности JS-строки (включая перенос строки)."""
    if "\\" not in raw:
        return raw

    # Быстрый путь: только продолжения строк, экранированные кавычки и бэкслеши.
    if not re.search(r"\\[^\\\n\r\"']", raw):
        protected = raw.replace("\\\\", "\x00")
        protected = protected.replace('\\"', '"').replace("\\'", "'")
        protected = protected.replace("\\\r\n", "").replace("\\\n", "").replace("\\\r", "")
        return protected.replace("\x00", "\\")

    out: list[str] = []
    index = 0
    length = len(raw)
    while index < length:
        char = raw[index]
        if char != "\\" or index + 1 >= length:
            out.append(char)
            index += 1
            continue
        nxt = raw[index + 1]
        if nxt == "x" and index + 3 < length:
            out.append(chr(int(raw[index + 2:index + 4], 16)))
            index += 4
        elif nxt == "u" and index + 5 < length:
            out.append(chr(int(raw[index + 2:index + 6], 16)))
            index += 6
        else:
            out.append(_ESCAPE_MAP.get(nxt, nxt))
            index += 2
    return "".join(out)


def extract_js_string(text: str, var_name: str) -> str | None:
    """Возвращает значение ``var <var_name> = "...";`` (с раскрытием escape-кодов)."""
    pattern = re.compile(r"var\s+" + re.escape(var_name) + r"\s*=\s*\"")
    match = pattern.search(text)
    if not match:
        return None

    index = match.end()
    chunks: list[str] = []
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            chunks.append(text[index:index + 2])
            index += 2
            continue
        if char == '"':
            break
        chunks.append(char)
        index += 1
    return unescape_js_string("".join(chunks))


def _extract_object_body(text: str, markup: str) -> str | None:
    """Тело объекта ``{...}`` для ``<markup> = { ... };``."""
    pattern = re.compile(r"(?s)(?:var\s+)?" + re.escape(markup) + r"\s*=\s*\{")
    match = pattern.search(text)
    if not match:
        return None
    start = match.end() - 1
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    return None


def _is_escaped(text: str, index: int) -> bool:
    """Экранирован ли символ ``text[index]`` обратной косой чертой."""
    backslashes = 0
    position = index - 1
    while position >= 0 and text[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 1


def _extract_three_part_suffixes(text: str) -> str | None:
    """Регулярное выражение из ``if (/.../.test(host))`` (зоны вида co.uk)."""
    for match in _TEST_HOST_RE.finditer(text):
        closing = match.start()
        # Перед ".test(host)" должна стоять закрывающая косая черта.
        if closing == 0 or text[closing - 1] != "/":
            continue
        closing -= 1
        index = closing - 1
        while index >= 0:
            if text[index] == "/" and not _is_escaped(text, index):
                candidate = text[index + 1:closing]
                if candidate:
                    return candidate
                break
            index -= 1
    return None


def _parse_proxy_urls(text: str) -> tuple[str | None, str | None]:
    """Ищет адреса прокси в ``return "HTTPS host:port; PROXY host:port";``."""
    https_proxy: str | None = None
    http_proxy: str | None = None
    for match in _PROXY_RETURN_RE.finditer(text):
        for token in match.group(1).split(";"):
            token = token.strip()
            if not token:
                continue
            parts = token.split(None, 1)
            if len(parts) != 2:
                continue
            kind, value = parts[0].upper(), parts[1].strip()
            if kind == "HTTPS" and https_proxy is None:
                https_proxy = value if "://" in value else f"https://{value}"
            elif kind == "PROXY" and http_proxy is None:
                http_proxy = value if "://" in value else f"http://{value}"
    return https_proxy, http_proxy


def _parse_patterns(text: str) -> tuple[dict[str, str], dict[str, str]]:
    """Возвращает пару «словарь замен для доменов, словарь замен для маски».

    В PAC-скрипте Антизапрета встречаются два варианта записи:

    * именованные объекты ``var patterns_domains_lzp`` / ``var patterns_mask_lzp``;
    * два безымянных ``var patterns = {...}`` (сначала домены, затем маска) —
      именно так их пишет генератор из ``topsequences.py`` и ``lzp.py``.
    """
    named_domains: dict[str, str] = {}
    named_mask: dict[str, str] = {}
    positional: list[dict[str, str]] = []

    for match in _PATTERNS_BLOCK_RE.finditer(text):
        name = (match.group(1) or "").lower()
        pairs = {key: value for key, value in _PATTERN_PAIR_RE.findall(match.group(2))}
        if name == "domains_lzp":
            named_domains = pairs
        elif name == "mask_lzp":
            named_mask = pairs
        else:
            positional.append(pairs)

    domains = named_domains
    mask = named_mask
    if not domains and positional:
        domains = positional.pop(0)
    if not mask and positional:
        mask = positional.pop(0)
    return domains, mask


def _parse_domains_structure(body: str) -> list[tuple[str, list[tuple[int, int]]]]:
    """Разбирает ``"tld":{длина_фрагмента:длина_данных, ...}`` с сохранением порядка."""
    entries: list[tuple[str, list[tuple[int, int]]]] = []
    for tld, lengths_body in _TLD_ENTRY_RE.findall(body):
        lengths: list[tuple[int, int]] = []
        for item in lengths_body.split(","):
            item = item.strip()
            if not item or ":" not in item:
                continue
            key, _, value = item.partition(":")
            try:
                lengths.append((int(key.strip()), int(value.strip())))
            except ValueError:
                continue
        if lengths:
            entries.append((tld, lengths))
    return entries


def _parse_blocked_ips(raw: str) -> frozenset[int]:
    """base36-дельты IP-адресов → множество адресов (uint32)."""
    result: set[int] = set()
    previous = 0
    for token in re.split(r"\s+", raw.replace("\\", "")):
        token = token.strip()
        if not token:
            continue
        try:
            value = int(token, 36)
        except ValueError:
            continue
        current = (previous + value) & 0xFFFFFFFF
        result.add(current)
        previous = current
    return frozenset(result)


def _parse_special(raw: str) -> tuple[tuple[ipaddress.IPv4Network, str], ...]:
    networks = []
    for address, prefix in _SPECIAL_ENTRY_RE.findall(raw):
        try:
            network = ipaddress.ip_network(f"{address}/{prefix}", strict=False)
        except ValueError:
            continue
        networks.append((network, f"{address}/{prefix}"))
    return tuple(networks)


# ---------------------------------------------------------------------- результат


@dataclass
class PacList:
    """Разобранный PAC-скрипт: списки блокировок + адреса прокси."""

    domains: dict[str, dict[int, set[str]]] = field(default_factory=dict)
    blocked_ips: frozenset[int] = frozenset()
    special: tuple[tuple[ipaddress.IPv4Network, str], ...] = ()
    patterns_domains: dict[str, str] = field(default_factory=dict)
    patterns_mask: dict[str, str] = field(default_factory=dict)
    three_part_suffixes: re.Pattern[str] | None = None
    three_part_suffixes_source: str = ""
    proxy_https: str | None = None
    proxy_http: str | None = None
    source: str = ""
    created_at: float = field(default_factory=time.time)
    domain_count: int = 0
    stats: dict[str, object] = field(default_factory=dict)

    # ------------------------------------------------------------------ прокси
    def proxy_url(self, prefer_https: bool = True) -> str | None:
        """Адрес прокси Антизапрета (в порядке предпочтения)."""
        if prefer_https:
            return self.proxy_https or self.proxy_http
        return self.proxy_http or self.proxy_https

    # ---------------------------------------------------------------- проверка
    def _suffix_match(self, host: str) -> bool:
        if self.three_part_suffixes is None:
            return False
        try:
            return bool(self.three_part_suffixes.search(host))
        except re.error:
            return False

    def explain(self, host: str, resolve: bool = True) -> tuple[bool, str]:
        """Проверяет хост. Возвращает ``(нужен_прокси, причина)``.

        Причины: ``domain`` — домен в списке, ``ip`` — IP в списке,
        ``net`` — IP входит в заблокированную подсеть, ``""`` — не заблокирован.
        """
        host = _strip_port(host).strip().lower().rstrip(".")
        if not host:
            return False, ""

        is_ip = False
        ip_value = 0
        try:
            address = ipaddress.ip_address(host)
            is_ip = True
            if isinstance(address, ipaddress.IPv4Address):
                ip_value = int(address)
            else:
                # Списки Антизапрета содержат только IPv4.
                return False, ""
        except ValueError:
            is_ip = False

        if not is_ip:
            labels = host.split(".")
            if len(labels) < 2:
                return False, ""
            if self._suffix_match(host) and len(labels) >= 3:
                shost = ".".join(labels[-3:])
            else:
                shost = ".".join(labels[-2:])
            shost = shost.removeprefix("www.")
            curhost, _, curzone = shost.rpartition(".")
            if curhost:
                curhost = pattern_replace(curhost, self.patterns_domains)
                fragments = self.domains.get(curzone, {}).get(len(curhost))
                if fragments and curhost in fragments:
                    return True, "domain"

        if ip_value:
            resolved = ip_value
        elif resolve:
            resolved_ip = dns_resolve(host)
            if not resolved_ip:
                return False, ""
            resolved = int(resolved_ip)
        else:
            return False, ""

        if resolved in self.blocked_ips:
            return True, "ip"
        address = ipaddress.IPv4Address(resolved)
        for network, source in self.special:
            if address in network:
                return True, f"net:{source}"
        return False, ""

    def needs_proxy(self, host: str, resolve: bool = True) -> bool:
        return self.explain(host, resolve=resolve)[0]

    def proxy_for_host(self, host: str, prefer_https: bool = True, resolve: bool = True) -> str | None:
        """Прокси для хоста или ``None``, если хост не заблокирован."""
        needed, reason = self.explain(host, resolve=resolve)
        if not needed:
            return None
        proxy = self.proxy_url(prefer_https=prefer_https)
        if proxy is None:
            raise PacError("В PAC-скрипте не найден адрес прокси")
        return proxy


def _strip_port(host: str) -> str:
    host = host.strip()
    if host.startswith("["):  # IPv6: [::1]:8080
        end = host.find("]")
        return host[1:end] if end != -1 else host
    if host.count(":") == 1:
        name, _, port = host.partition(":")
        if port.isdigit():
            return name
    return host


# ------------------------------------------------------------------------- DNS кэш

_DNS_CACHE: dict[str, tuple[float, int | None]] = {}
_DNS_TTL = 600.0


def dns_resolve(host: str, ttl: float = _DNS_TTL) -> int | None:
    """IPv4-адрес хоста (int) с кэшированием; ``None`` при ошибке."""
    now = time.monotonic()
    cached = _DNS_CACHE.get(host)
    if cached and now - cached[0] < ttl:
        return cached[1]
    try:
        value = int(ipaddress.IPv4Address(socket.gethostbyname(host)))
    except (OSError, ValueError):
        value = None
    _DNS_CACHE[host] = (now, value)
    return value


def clear_dns_cache() -> None:
    _DNS_CACHE.clear()


# ---------------------------------------------------------------------- парсинг


def parse_pac(text: str, source: str = "") -> PacList:
    """Разбирает PAC-скрипт Антизапрета.

    :raises PacError: если обязательные секции отсутствуют или повреждены.
    """
    domains_match = _DOMAINS_RE.search(text)
    if not domains_match:
        raise PacError("В PAC-скрипте не найден список доменов (domains = {...})")

    domains_raw = _parse_domains_structure(domains_match.group(1))
    if not domains_raw:
        raise PacError("Список доменов в PAC-скрипте пуст")

    d_ipaddr = extract_js_string(text, "d_ipaddr")
    if d_ipaddr is None:
        raise PacError("В PAC-скрипте не найден список IP-адресов (d_ipaddr)")

    special_match = _SPECIAL_RE.search(text)
    special = _parse_special(special_match.group(1)) if special_match else ()

    domains_lzp = extract_js_string(text, "domains_lzp")
    mask_lzp = extract_js_string(text, "mask_lzp")
    if not domains_lzp or mask_lzp is None:
        raise PacError("В PAC-скрипте не найдены сжатые списки доменов (domains_lzp/mask_lzp)")

    patterns_domains, patterns_mask = _parse_patterns(text)

    mask_bytes = base64.b64decode(pattern_replace(mask_lzp, patterns_mask) + "==")
    data_bytes = domains_lzp.encode("utf-8", errors="surrogateescape")

    decoded, _, _, _ = unlzp(data_bytes, mask_bytes, limit=1 << 30)

    domains: dict[str, dict[int, set[str]]] = {}
    offset = 0
    total = 0
    truncated = False
    for tld, lengths in domains_raw:
        zone = domains.setdefault(tld, {})
        for fragment_length, data_length in lengths:
            if fragment_length <= 0:
                continue
            chunk = decoded[offset:offset + data_length]
            offset += data_length
            if len(chunk) < data_length:
                # Данных меньше, чем ожидалось: PAC-скрипт обрезан или
                # нестандартный — работаем с тем, что удалось распаковать.
                truncated = True
            fragment_count = len(chunk) // fragment_length
            for index in range(fragment_count):
                start = index * fragment_length
                zone.setdefault(fragment_length, set()).add(
                    chunk[start:start + fragment_length].decode("utf-8", errors="replace")
                )
            total += fragment_count

    three_part_source = _extract_three_part_suffixes(text) or ""
    three_part: re.Pattern[str] | None = None
    if three_part_source:
        try:
            three_part = re.compile(three_part_source)
        except re.error:
            three_part = None

    proxy_https, proxy_http = _parse_proxy_urls(text)
    if not proxy_https and not proxy_http:
        raise PacError("В PAC-скрипте не найден адрес прокси")

    result = PacList(
        domains=domains,
        blocked_ips=_parse_blocked_ips(d_ipaddr),
        special=special,
        patterns_domains=patterns_domains,
        patterns_mask=patterns_mask,
        three_part_suffixes=three_part,
        three_part_suffixes_source=three_part_source,
        proxy_https=proxy_https,
        proxy_http=proxy_http,
        source=source,
        domain_count=total,
    )
    result.stats = {
        "domains": total,
        "zones": len(domains),
        "blocked_ips": len(result.blocked_ips),
        "special_networks": len(special),
        "proxy": result.proxy_https or result.proxy_http,
        "truncated": truncated,
    }
    return result


def describe(host: str, pac: PacList, resolve: bool = True) -> str:
    """Человекочитаемое объяснение решения по хосту (для логов)."""
    needed, reason = pac.explain(host, resolve=resolve)
    if not needed:
        return f"{host}: не заблокирован, прокси не нужен"
    if reason == "domain":
        return f"{host}: домен в списке блокировок → прокси"
    if reason == "ip":
        return f"{host}: IP в списке блокировок → прокси"
    if reason.startswith("net:"):
        return f"{host}: IP входит в заблокированную подсеть {reason[4:]} → прокси"
    return f"{host}: нужен прокси ({reason})"
