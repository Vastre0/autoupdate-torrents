"""Встроенный обход блокировок на основе PAC-скриптов Антизапрета.

Скачивает PAC-скрипт (те же зеркала, что использует расширение
«Обход блокировок Рунета» для Firefox), кэширует его в
``~/.cache/autoupdate-torrents/pac`` и решает, какие хосты нужно пускать
через прокси. Браузер для обхода не нужен — прокси применяется прямо в
HTTP-запросах приложения.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import requests

from . import paths
from .antizapret import PacError, PacList, describe, parse_pac
from .config import ConfigManager

LogFunc = Callable[[str], None]

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
)

DEFAULT_PAC_URLS = [
    "https://antizapret.prostovpn.org:8443/proxy.pac",
    "https://antizapret.prostovpn.org:18443/proxy.pac",
    "https://antizapret.prostovpn.org/proxy.pac",
    "https://e.cen.rodeo:8443/proxy.pac",
]

STATE_FILE = "state.json"

# Сервис отдаёт список только для российских IP.
GEOBLOCK_MARKERS = ("your geoip is not ru", "geoip is not ru")

# Антизапрет просит не запрашивать PAC-файл чаще раза в минуту.
MIN_RETRY_INTERVAL = 60.0


class BypassError(RuntimeError):
    """Не удалось получить или разобрать PAC-скрипт."""


class BypassManager:
    """Загрузка, кэширование и применение PAC-скрипта Антизапрета."""

    def __init__(
        self,
        config: ConfigManager,
        log: LogFunc | None = None,
        session: requests.Session | None = None,
    ):
        self.config = config
        self._log_func = log
        self._lock = threading.RLock()
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._pac: PacList | None = None
        self._state: dict[str, Any] = {}
        self._last_error: str | None = None
        self._refreshing = False
        self._last_attempt = 0.0
        self._refresh_thread: threading.Thread | None = None
        self._cache_dir = paths.cache_dir() / "pac"

    # ------------------------------------------------------------------ логирование
    def _log(self, message: str) -> None:
        if self._log_func:
            self._log_func(message)

    # -------------------------------------------------------------------- настройки
    @property
    def enabled(self) -> bool:
        return bool(self.config.get_section("bypass").get("enabled", True))

    @property
    def settings(self) -> dict[str, Any]:
        return self.config.get_section("bypass")

    @property
    def manual_proxy(self) -> str:
        return str(self.settings.get("manual_proxy") or "").strip()

    @property
    def pac_urls(self) -> list[str]:
        urls = self.settings.get("pac_urls") or DEFAULT_PAC_URLS
        return [str(url) for url in urls if url]

    @property
    def prefer_https_proxy(self) -> bool:
        return bool(self.settings.get("prefer_https_proxy", True))

    @property
    def ttl_seconds(self) -> float:
        try:
            hours = float(self.settings.get("pac_cache_ttl_hours", 12))
        except (TypeError, ValueError):
            hours = 12.0
        return max(1.0, hours) * 3600.0

    @property
    def dns_check(self) -> bool:
        return bool(self.settings.get("dns_check", True))

    # -------------------------------------------------------------------- состояние
    @property
    def pac(self) -> PacList | None:
        with self._lock:
            return self._pac

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def status(self) -> dict[str, Any]:
        """Краткое состояние обхода (для GUI/CLI)."""
        with self._lock:
            pac = self._pac
            state = dict(self._state)
            error = self._last_error
            refreshing = self._refreshing
        fetched_at = float(state.get("fetched_at") or 0)
        return {
            "enabled": self.enabled,
            "loaded": pac is not None,
            "refreshing": refreshing,
            "source": pac.source if pac else state.get("url", ""),
            "proxy": (pac.proxy_url(self.prefer_https_proxy) if pac else "") or "",
            "manual_proxy": self.manual_proxy,
            "domains": pac.domain_count if pac else 0,
            "blocked_ips": len(pac.blocked_ips) if pac else 0,
            "age_seconds": max(0.0, time.time() - fetched_at) if fetched_at else None,
            "error": error,
        }

    def describe_host(self, host: str) -> str:
        """Текстовое объяснение решения по хосту."""
        pac = self.pac
        if not self.enabled:
            return f"{host}: обход блокировок выключен, запрос идёт напрямую."
        if pac is None:
            extra = f" Резервный прокси: {self.manual_proxy}." if self.manual_proxy else ""
            return (
                f"{host}: PAC-скрипт ещё не загружен, решение неизвестно.{extra}"
            )
        return describe(host, pac, resolve=self.dns_check)

    # ----------------------------------------------------------------------- кэш
    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        return self._cache_dir / f"{digest}.pac.gz"

    def _read_state(self) -> dict[str, Any]:
        try:
            with open(self._cache_dir / STATE_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_state(self, state: dict[str, Any]) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._cache_dir / (STATE_FILE + ".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=False)
        tmp.replace(self._cache_dir / STATE_FILE)

    def _save_pac(self, url: str, text: str, stats: dict[str, Any] | None = None) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        with gzip.open(self._cache_path(url), "wt", encoding="utf-8") as handle:
            handle.write(text)
        self._write_state(
            {
                "url": url,
                "fetched_at": time.time(),
                "size": len(text),
                "stats": stats or {},
            }
        )

    def _load_from_cache(self) -> str | None:
        self._state = self._read_state()
        url = str(self._state.get("url") or "")
        candidates = [url] + [u for u in self.pac_urls if u != url]
        for candidate in candidates:
            if not candidate:
                continue
            path = self._cache_path(candidate)
            if not path.is_file():
                continue
            try:
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    return handle.read()
            except (OSError, EOFError):
                continue
        return None

    @property
    def cache_age(self) -> float | None:
        """Возраст кэша PAC в секундах (``None``, если кэша нет)."""
        with self._lock:
            fetched_at = float(self._state.get("fetched_at") or 0)
        return time.time() - fetched_at if fetched_at else None

    def cache_is_fresh(self) -> bool:
        age = self.cache_age
        return age is not None and age < self.ttl_seconds

    # --------------------------------------------------------------------- загрузка
    def _fetch_pac_text(self, proxy: str | None = None) -> tuple[str, str]:
        """Скачивает PAC-скрипт с первого доступного зеркала."""
        proxies = {"http": proxy, "https": proxy} if proxy else None
        errors: list[str] = []
        for url in self.pac_urls:
            try:
                response = self._session.get(
                    url,
                    timeout=30,
                    proxies=proxies,
                    headers={"Accept": "*/*", "Referer": url, "Origin": urlsplit(url).scheme + "://" + urlsplit(url).netloc},
                )
            except requests.RequestException as error:
                errors.append(f"{url}: {error}")
                continue
            if response.status_code != 200:
                errors.append(f"{url}: HTTP {response.status_code}")
                continue
            text = response.text
            lowered = text.lower()
            if any(marker in lowered for marker in GEOBLOCK_MARKERS):
                errors.append(
                    f"{url}: сервис отдаёт список только для IP из России "
                    "(geoblocking) — включите VPN/прокси или укажите свой прокси"
                )
                continue
            try:
                parse_pac(text, source=url)
            except PacError as error:
                errors.append(f"{url}: {error}")
                continue
            return text, url
        raise BypassError("Не удалось скачать PAC-скрипт. " + "; ".join(errors))

    def refresh(
        self,
        force: bool = True,
        proxy: str | None = None,
        min_interval: float = 0.0,
    ) -> bool:
        """Скачивает и разбирает свежий PAC-скрипт.

        :param force: перезагрузить, даже если кэш ещё свежий.
        :param proxy: прокси для самой загрузки (если прямое соединение закрыто).
        :param min_interval: не обращаться к зеркалам чаще, чем раз в N секунд
            (сервис Антизапрета ограничивает частоту запросов PAC-файла).
        """
        now = time.monotonic()
        with self._lock:
            if self._refreshing:
                self._log("Обновление PAC уже выполняется.")
                return False
            if not force and self.cache_is_fresh() and self._pac is not None:
                return True
            last_attempt = getattr(self, "_last_attempt", 0.0)
            if min_interval and last_attempt and now - last_attempt < min_interval:
                self._log(
                    "PAC-скрипт запрашивался меньше минуты назад — "
                    "пропускаем обращение к зеркалам (ограничение сервиса)."
                )
                return self._pac is not None
            self._last_attempt = now
            self._refreshing = True
        try:
            self._log("Загрузка PAC-скрипта Антизапрета...")
            candidates = [proxy] if proxy else ([self.manual_proxy] if self.manual_proxy else [None])
            text: str | None = None
            source = ""
            last_error: Exception | None = None
            for candidate in candidates:
                try:
                    text, source = self._fetch_pac_text(candidate)
                    break
                except BypassError as error:
                    last_error = error
            if text is None:
                raise last_error or BypassError("PAC-скрипт недоступен")

            pac = parse_pac(text, source=source)
            self._save_pac(source, text, pac.stats)
            with self._lock:
                self._pac = pac
                self._state = self._read_state()
                self._last_error = None
            self._log(
                f"PAC-скрипт загружен: доменов {pac.domain_count}, "
                f"IP {len(pac.blocked_ips)}, прокси {pac.proxy_url(self.prefer_https_proxy)}"
            )
            return True
        except (BypassError, PacError, OSError) as error:
            with self._lock:
                self._last_error = str(error)
            self._log(f"Ошибка обхода блокировок: {error}")
            return False
        finally:
            with self._lock:
                self._refreshing = False

    def ensure_loaded(self, background_refresh: bool = True) -> bool:
        """Гарантирует, что PAC-скрипт разобран (из кэша или из сети)."""
        with self._lock:
            if self._pac is not None:
                return True
        text = self._load_from_cache()
        if text:
            try:
                pac = parse_pac(text, source=str(self._state.get("url") or "cache"))
            except PacError as error:
                self._log(f"Кэш PAC повреждён ({error}), скачиваем заново.")
                pac = None
            if pac is not None:
                with self._lock:
                    self._pac = pac
                if not self.cache_is_fresh() and background_refresh:
                    self.refresh_in_background()
                    self._log("Кэш PAC устарел, обновляем в фоне.")
                return True
        if not background_refresh:
            return self.refresh(force=True, min_interval=MIN_RETRY_INTERVAL)
        self.refresh_in_background()
        return False

    def refresh_in_background(self) -> None:
        """Запускает обновление PAC в отдельном потоке (не блокирует UI)."""
        with self._lock:
            if self._refreshing or (self._refresh_thread and self._refresh_thread.is_alive()):
                return
            thread = threading.Thread(
                target=self.refresh,
                kwargs={"force": True, "min_interval": MIN_RETRY_INTERVAL},
                daemon=True,
            )
            self._refresh_thread = thread
        thread.start()

    # ------------------------------------------------------------------ применение
    @staticmethod
    def host_from_url(url: str) -> str:
        parsed = urlsplit(url)
        return parsed.hostname or parsed.netloc or url

    def proxies_for_host(self, host: str) -> dict[str, str] | None:
        """Прокси для хоста или ``None``, если прокси не требуется."""
        if not self.enabled:
            return None
        pac = self.pac
        if pac is None:
            return None
        try:
            proxy = pac.proxy_for_host(host, prefer_https=self.prefer_https_proxy, resolve=self.dns_check)
        except PacError as error:
            self._log(f"Ошибка PAC: {error}")
            return None
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}

    def proxies_for_url(self, url: str) -> dict[str, str] | None:
        return self.proxies_for_host(self.host_from_url(url))

    def fallback_proxies(self, host: str) -> dict[str, str] | None:
        """Прокси «на всякий случай»: ручной или адрес из PAC-скрипта.

        Используется, когда прямое соединение не удалось (типичный признак
        блокировки со стороны провайдера).
        """
        if not self.enabled:
            return None
        if self.manual_proxy:
            return {"http": self.manual_proxy, "https": self.manual_proxy}
        pac = self.pac
        if pac is None:
            self.ensure_loaded(background_refresh=False)
            pac = self.pac
        if pac is None:
            return None
        proxy = pac.proxy_url(prefer_https=self.prefer_https_proxy)
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}
