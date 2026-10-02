"""Генератор синтетического PAC-скрипта в формате Антизапрета.

Используется тестами, чтобы проверить разбор PAC без обращения к сети
(настоящий PAC-скрипт отдаётся только на IP из России).

Реализация повторяет формат, который создают:

* ``scripts/lzp.py`` — LZP-сжатие и подстановка частых последовательностей маски;
* ``scripts/generate-pac-domains.awk`` — структура ``domains = {...}``;
* ``scripts/generate-pac-ipaddrs.awk`` — ``var d_ipaddr`` в base36-дельтах;
* ``generate-pac.sh`` — итоговый текст PAC-скрипта.
"""

from __future__ import annotations

import base64
import textwrap
from collections import Counter

from torrent_manager.antizapret import (
    HASH_MASK,
    TABLE_LEN_BITS,
    pattern_replace,
    pattern_restore,
)

BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"

DEFAULT_THREE_PART_SUFFIXES = r"\.(ru|co|com|net|org)\.[^.]+$"


def lzp_encode(data: bytes) -> tuple[bytes, bytes]:
    """LZP-сжатие (побитово совместимо с ``lzp.py`` Антизапрета)."""
    table = bytearray(1 << TABLE_LEN_BITS)
    hashed = 0
    payload = bytearray()
    mask = bytearray()

    index = 0
    while index < len(data):
        bits = 0
        buffer = bytearray()
        for bit in range(8):
            if index >= len(data):
                break
            char = data[index]
            index += 1
            if char == table[hashed]:
                bits |= 1 << bit
            else:
                table[hashed] = char
                buffer.append(char)
            hashed = ((hashed << 7) ^ char) & HASH_MASK
        mask.append(bits)
        payload += buffer
    return bytes(payload), bytes(mask)


def _wrap(text: str, width: int = 8192) -> str:
    """Разбивка длинной строки переносами вида ``\\`` + перевод строки."""
    return "\\\n".join(
        textwrap.wrap(
            text,
            width,
            expand_tabs=False,
            replace_whitespace=False,
            drop_whitespace=False,
            break_long_words=True,
            break_on_hyphens=False,
        )
    )


def _base36(value: int) -> str:
    if value == 0:
        return "0"
    digits = ""
    while value:
        value, remainder = divmod(value, 36)
        digits = BASE36[remainder] + digits
    return digits


def _ip_to_int(address: str) -> int:
    parts = [int(part) for part in address.split(".")]
    return parts[3] + parts[2] * 256 + parts[1] * 65536 + parts[0] * 16777216


def _d_ipaddr_block(addresses: list[str]) -> str:
    tokens: list[str] = []
    previous = 0
    for address in sorted(addresses, key=_ip_to_int):
        current = _ip_to_int(address)
        tokens.append(_base36(current - previous))
        previous = current
    payload = " ".join(tokens) + " "
    return 'var d_ipaddr = "\\\n' + _wrap(payload) + ' \\\n".split(" ");'


def build_pac(
    domains: dict[str, list[str]],
    blocked_ips: list[str] | None = None,
    special: list[tuple[str, int]] | None = None,
    patterns_domains: dict[str, str] | None = None,
    patterns_mask: dict[str, str] | None = None,
    proxy_https: str = "proxy.antizapret.test:8443",
    proxy_http: str = "proxy.antizapret.test:8080",
    three_part_suffixes: str = DEFAULT_THREE_PART_SUFFIXES,
    auto_mask_pattern: bool = True,
    width: int = 8192,
) -> str:
    """Собирает текст PAC-скрипта.

    :param domains: ``{"com": ["example", "aaa"]}`` — префиксы доменов
        (без зоны) по зонам.
    :param patterns_domains: словарь замен в формате PAC (``{"!": "mega"}``).
    :param patterns_mask: словарь замен маски (``{"AAB": "~"}``).
    """
    patterns_domains = patterns_domains or {}
    structure: dict[str, dict[int, list[str]]] = {}

    for zone, prefixes in domains.items():
        by_length: dict[int, list[str]] = {}
        for prefix in prefixes:
            shortened = pattern_replace(prefix, patterns_domains)
            by_length.setdefault(len(shortened), []).append(shortened)
        structure[zone] = by_length

    # Данные LZP — конкатенация фрагментов в том же порядке, в каком их
    # перебирает PAC-скрипт (зона → длина фрагмента → фрагмент).
    stream_parts: list[str] = []
    for zone in structure:
        for length in sorted(structure[zone]):
            stream_parts.extend(structure[zone][length])
    stream = "".join(stream_parts).encode("utf-8")

    data_bytes, mask_bytes = lzp_encode(stream)
    mask_b64 = base64.b64encode(mask_bytes).decode("ascii")

    if patterns_mask is None and auto_mask_pattern:
        # Берём самую частую пару символов в base64-маске и заменяем её —
        # ровно так делает findsequence() из lzp.py.
        pairs = Counter(mask_b64[i:i + 2] for i in range(len(mask_b64) - 1))
        candidates = [pair for pair, count in pairs.most_common(10) if pair.isalnum()]
        if candidates:
            patterns_mask = {candidates[0]: "~"}
    patterns_mask = patterns_mask or {}

    # В отличие от доменов, у маски длинная последовательность — это ключ,
    # а короткая замена — значение, поэтому применяем pattern_restore.
    mask_sequenced = pattern_restore(mask_b64, patterns_mask)

    # Структура domains = {...}
    zone_entries: list[str] = []
    for zone, by_length in structure.items():
        items = ",".join(
            f"{length}:{sum(len(item) for item in by_length[length])}"
            for length in sorted(by_length)
        )
        zone_entries.append(f'"{zone}":{{{items}}}')
    domains_block = "domains = {\n" + ",\n".join(zone_entries) + "\n};"

    special = special or []
    special_block = "var special = [" + ",".join(
        f'["{address}", {prefix}]' for address, prefix in special
    ) + "];"

    domains_lzp = _wrap(data_bytes.decode("latin-1"), width)
    mask_lzp = _wrap(mask_sequenced, width)

    patterns_domains_block = "{" + ", ".join(
        f"'{key}': '{value}'" for key, value in patterns_domains.items()
    ) + "}"
    patterns_mask_block = "{" + ", ".join(
        f"'{key}': '{value}'" for key, value in patterns_mask.items()
    ) + "}"

    return f"""// ProstoVPN.AntiZapret PAC-host File (тестовый образец)
// Сгенерирован generate-pac.sh-совместимым генератором из тестов.

{domains_block}

{special_block}

// domain name data encoded with LZP, without mask data
var domains_lzp = "{domains_lzp}";

// LZP mask data, b64+patternreplace
var mask_lzp = "{mask_lzp}";

{_d_ipaddr_block(blocked_ips or [])}

var az_initialized = 0;
function nmfc(b) {{var m=[];for(var i=0;i<4;i++) {{var n=Math.min(b,8); m.push(256-Math.pow(2, 8-n)); b-=n;}} return m.join('.');}}
function patternreplace(s, lzpmask) {{
  var patterns = {patterns_domains_block};
  if (lzpmask)
   var patterns = {patterns_mask_block};
  for (pattern in patterns) {{
    s = s.split(patterns[pattern]).join(pattern);
  }}
  return s;
}}
var TABLE_LEN_BITS = 18;
var HASH_MASK = (1 << TABLE_LEN_BITS) - 1;
var table = Array(1 << TABLE_LEN_BITS);
var hash = 0;
function unlzp(d, m, lim) {{
  var mask = 0, maskpos = 0, dpos = 0, out = Array(8), outpos = 0, outfinal = '';
  for (;;) {{
    mask = m.charAt(maskpos++);
    if (!mask)
      break
    mask = mask.charCodeAt(0);
    outpos = 0;
    for (var i = 0; i < 8; i++) {{
      if (mask & (1 << i)) {{
        c = table[hash];
      }} else {{
        c = d.charAt(dpos++);
        if (!c)
          break
        c = c.charCodeAt(0);
        table[hash] = c;
      }}
      out[outpos++] = String.fromCharCode(c);
      hash = ( (hash << 7) ^ c ) & HASH_MASK
    }}
    if (outpos == 8)
      outfinal += out.join('');
    if (outfinal.length >= lim) break;
  }}
  if (outpos < 8)
    outfinal += out.slice(0, outpos).join('');
  return [outfinal, dpos, maskpos];
}}

function a2b(a) {{ return atob(a); }}

function FindProxyForURL(url, host) {{
  if (domains.length < 10) return "DIRECT"; // list is broken

  if (!az_initialized) {{
    var prev_ipval = 0;
    for (var i = 0; i < d_ipaddr.length; i++) {{
     cur_ipval = parseInt(d_ipaddr[i], 36) + prev_ipval;
     d_ipaddr[i] = cur_ipval;
     prev_ipval = cur_ipval;
    }}
    for (var i = 0; i < special.length; i++) {{
     special[i][1] = nmfc(special[i][1]);
    }}
    mask_lzp = a2b(patternreplace(mask_lzp, true));
    az_initialized = 1;
  }}

  var shost;
  if (/{three_part_suffixes}/.test(host))
    shost = host.replace(/(.+)\\.([^.]+\\.[^.]+\\.[^.]+$)/, "$2");
  else
    shost = host.replace(/(.+)\\.([^.]+\\.[^.]+$)/, "$2");

  shost = shost.replace(/^www\\.(.+)/, "$1");

  var curdomain = shost.match(/(.*)\\.([^.]+$)/);
  if (!curdomain || !curdomain[1]) {{return "DIRECT";}}
  var curhost = patternreplace(curdomain[1], false);
  var curzone = curdomain[2];

  return "HTTPS {proxy_https}; PROXY {proxy_http}; DIRECT";
}}
"""
