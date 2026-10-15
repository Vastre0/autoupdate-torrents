"""Работа с rutracker.org и qBittorrent.

Загрузка .torrent-файлов идёт с учётом обхода блокировок: если PAC-скрипт
считает хост заблокированным, запрос уходит через прокси Антизапрета,
иначе — напрямую (с автоматическим повторным запросом через прокси, если
прямое соединение оборвано провайдером).
"""

from __future__ import annotations

import re
from typing import Any, Callable

import requests
from bs4 import BeautifulSoup

try:  # qbittorrent-api — единственная зависимость не из официальных репозиториев Arch
    from qbittorrentapi import APIConnectionError, Client, LoginFailed
    from qbittorrentapi import NotFound404Error
except ImportError:  # pragma: no cover - проверяется в тестах через mock
    Client = None  # type: ignore[assignment]
    APIConnectionError = LoginFailed = NotFound404Error = Exception  # type: ignore[misc,assignment]

from .bypass import BypassManager

LogFunc = Callable[[str], None]

RUTRACKER_BASE = "https://rutracker.org/forum/"
RUTRACKER_HOST = "rutracker.org"

TOPIC_ID_RE = re.compile(r"[?&]t=(\d+)")

# Признаки страницы-заглушки провайдера/Роскомнадзора.
BLOCK_MARKERS = (
    "доступ ограничен",
    "доступ к информационному ресурсу",
    "единый реестр",
    "роскомнадзор",
    "blocked by",
    "zapret-info",
)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:157.0) Gecko/20100101 Firefox/157.0"
)

DEFAULT_BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
}

QBITTORRENT_IMPORT_HINT = (
    "Не установлен модуль qbittorrent-api.\n"
    "CachyOS/Arch: paru -S python-qbittorrent-api\n"
    "либо: python -m pip install --user qbittorrent-api"
)


class RutrackerError(RuntimeError):
    """Ошибка при работе с rutracker.org."""


class QBittorrentError(RuntimeError):
    """Ошибка при работе с qBittorrent."""


def extract_torrent_id(url: str) -> str:
    """Извлекает ID раздачи из ссылки rutracker."""
    match = TOPIC_ID_RE.search(url or "")
    if match:
        return match.group(1)
    digits = (url or "").strip()
    if digits.isdigit():
        return digits
    raise ValueError(f"Не удалось извлечь ID раздачи из ссылки: {url!r}")


def topic_url(topic_id: str) -> str:
    return f"{RUTRACKER_BASE}viewtopic.php?t={topic_id}"


def looks_blocked(text: str) -> bool:
    """Похоже ли содержимое ответа на заглушку о блокировке."""
    lowered = (text or "")[:20000].lower()
    return any(marker in lowered for marker in BLOCK_MARKERS)


class RutrackerClient:
    """Клиент rutracker.org с поддержкой обхода блокировок."""

    def __init__(
        self,
        cookies: dict[str, str],
        bypass: BypassManager | None = None,
        log: LogFunc | None = None,
        timeout: float = 25.0,
    ):
        self.cookies = dict(cookies or {})
        self.bypass = bypass
        self._log_func = log
        self.timeout = timeout
        self.session = requests.Session()
        # Не используем proxy-переменные окружения неявно: маршрут выбирает
        # BypassManager, а системный proxy включается отдельной настройкой.
        self.session.trust_env = False
        self.session.headers.update(DEFAULT_BROWSER_HEADERS)
        for name, value in self.cookies.items():
            self.session.cookies.set(name, value, domain=".rutracker.org")

    def _log(self, message: str) -> None:
        if self._log_func:
            self._log_func(message)

    # ------------------------------------------------------------------ маршруты
    def _routes(self, url: str) -> list[tuple[dict[str, str] | None, str]]:
        """Порядок попыток: настроенные proxy, PAC, напрямую, fallback."""
        routes: list[tuple[dict[str, str] | None, str]] = []
        bypass = self.bypass
        configured: list[dict[str, str]] = []
        # Если задан ручной прокси (например, официальный прокси плагина rutracker),
        # пробуем его первым делом.
        if bypass and getattr(bypass, "manual_proxy", ""):
            manual = {"http": bypass.manual_proxy, "https": bypass.manual_proxy}
            routes.append((manual, f"через ручной прокси {bypass.manual_proxy}"))
        if bypass and bypass.enabled:
            getter = getattr(bypass, "proxy_routes_for_url", None)
            if getter:
                try:
                    configured = getter(url) or []
                except Exception:  # noqa: BLE001 - proxy не должен ломать запрос
                    configured = []
            else:
                getter = getattr(bypass, "proxies_for_url", None)
                proxy = getter(url) if getter else None
                if proxy:
                    configured = [proxy]
        for index, route in enumerate(configured):
            if any(existing == route for existing, _ in routes):
                continue
            label = route.get("https") or route.get("http") or "proxy"
            suffix = "" if index == 0 and not routes else " (резервный proxy)"
            routes.append((route, f"через прокси {label}{suffix}"))
        routes.append((None, "напрямую"))
        if bypass and bypass.enabled:
            host = bypass.host_from_url(url)
            route_getter = getattr(bypass, "fallback_routes", None)
            if route_getter:
                fallbacks = route_getter(host) or []
            else:
                fallback_getter = getattr(bypass, "fallback_proxies", None)
                fallback = fallback_getter(host) if fallback_getter else None
                fallbacks = [fallback] if fallback else []
            for fallback in fallbacks:
                if any(existing == fallback for existing, _ in routes):
                    continue
                label = fallback.get("https") or fallback.get("http") or "proxy"
                routes.append((fallback, f"через прокси {label} (резервный маршрут)"))
        return routes

    def _request(self, url: str, binary: bool = False, params: dict[str, Any] | None = None) -> requests.Response:
        """GET с перебором маршрутов (напрямую/через прокси)."""
        errors: list[str] = []
        for proxies, label in self._routes(url):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    proxies=proxies,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.RequestException as error:
                message = f"{label}: {type(error).__name__}: {error}"
                errors.append(message)
                self._log(f"Не удалось получить {url} ({message})")
                continue

            if response.status_code in (451, 403) and looks_blocked(response.text):
                errors.append(f"{label}: заглушка о блокировке (HTTP {response.status_code})")
                self._log(f"{url}: получена заглушка о блокировке ({label})")
                continue
            if response.status_code in (403, 503) and (
                "cf-mitigated" in response.headers
                or "challenges.cloudflare.com" in response.text
                or "just a moment..." in response.text.lower()
            ):
                msg = f"{label}: Cloudflare требует проверку браузера (капча / WAF)"
                errors.append(msg)
                self._log(f"{url}: {msg}")
                continue
            if not binary and looks_blocked(response.text):
                errors.append(f"{label}: заглушка о блокировке")
                self._log(f"{url}: похоже на страницу-заглушку ({label})")
                continue

            try:
                response.raise_for_status()
            except requests.RequestException as error:
                errors.append(f"{label}: HTTP {response.status_code}")
                self._log(f"{url}: ошибка HTTP ({label}): {error}")
                continue
            return response

        details = "; ".join(errors) if errors else "нет доступных маршрутов"
        raise RutrackerError(f"Не удалось загрузить {url}: {details}")

    # ------------------------------------------------------------------ проверка
    def check_connection(self) -> tuple[bool, str]:
        """Проверяет доступ к rutracker и валидность куки."""
        try:
            response = self._request(RUTRACKER_BASE + "index.php")
        except RutrackerError as error:
            return False, str(error)
        text = response.text.lower()
        if "logout" in text or "личный раздел" in text or "выход" in text:
            return True, "Соединение с rutracker работает, куки действительны."
        return False, (
            "Страница rutracker загружена, но авторизация не подтверждена — "
            "скорее всего куки устарели."
        )

    # ------------------------------------------------------------------ загрузка
    def download_torrent(self, topic_id: str) -> tuple[bytes, str]:
        """Скачивает .torrent для раздачи.

        :returns: ``(содержимое файла, ссылка на раздачу)``
        """
        url = topic_url(topic_id)
        self._log(f"Загрузка страницы раздачи {topic_id}...")
        page = self._request(url)
        soup = BeautifulSoup(page.text, "html.parser")

        link = soup.find("a", class_="dl-link")
        if link is None:
            link = soup.find("a", href=re.compile(r"dl\.php\?t="))
        if link is None or not link.get("href"):
            lowered = page.text.lower()
            needs_login = any(
                marker in lowered or marker in page.url.lower()
                for marker in ("войти", "вход", "login", "авторизац", "bb_session")
            )
            if needs_login:
                raise RutrackerError(
                    "Похоже, куки недействительны — rutracker просит авторизацию. "
                    "Обновите cookies.json (кнопка «Импорт куки»)."
                )
            raise RutrackerError(
                f"На странице раздачи {topic_id} не найдена ссылка на скачивание .torrent"
            )

        download_url = link["href"]
        if not download_url.startswith("http"):
            download_url = RUTRACKER_BASE + download_url.lstrip("/")

        self._log(f"Скачивание .torrent файла: {download_url}")
        response = self._request(download_url, binary=True)
        if not response.content:
            raise RutrackerError("Сервер вернул пустой .torrent файл")
        return response.content, url


class QBittorrentClient:
    """Минимальная обёртка над qbittorrent-api."""

    def __init__(self, settings: dict[str, Any], log: LogFunc | None = None):
        self.settings = dict(settings or {})
        self._log_func = log
        self._client: Any = None

    def _log(self, message: str) -> None:
        if self._log_func:
            self._log_func(message)

    @property
    def host(self) -> str:
        host = str(self.settings.get("host") or "localhost:8080")
        if "://" in host:
            return host
        return f"{'https' if self.settings.get('use_https') else 'http'}://{host}"

    def _connect(self) -> Any:
        if Client is None:
            raise QBittorrentError(QBITTORRENT_IMPORT_HINT)
        if self._client is not None:
            return self._client
        client = Client(
            host=self.host,
            username=str(self.settings.get("username") or ""),
            password=str(self.settings.get("password") or ""),
            REQUESTS_ARGS={"timeout": 20},
        )
        try:
            client.auth_log_in()
        except LoginFailed as error:
            raise QBittorrentError(
                f"qBittorrent отклонил логин/пароль ({error}). Проверьте настройки веб-интерфейса."
            ) from error
        except APIConnectionError as error:
            raise QBittorrentError(
                f"Не удалось подключиться к qBittorrent по адресу {self.host}: {error}"
            ) from error
        self._client = client
        return client

    def test(self) -> tuple[bool, str]:
        """Проверка подключения; возвращает ``(успех, сообщение)``."""
        try:
            client = self._connect()
            version = getattr(client.app, "version", "?")
            return True, f"Подключено к qBittorrent {version} ({self.host})"
        except QBittorrentError as error:
            return False, str(error)
        except Exception as error:  # noqa: BLE001 - сеть/библиотека могут кидать разное
            return False, f"Ошибка qBittorrent: {error}"

    def add_torrent(self, torrent_content: bytes, save_path: str, comment: str) -> bool:
        """Добавляет торрент, сохраняя исходную ссылку в комментарии."""
        client = self._connect()
        try:
            result = client.torrents_add(
                torrent_files=torrent_content,
                save_path=save_path or None,
                comment=comment,
            )
        except Exception as error:  # noqa: BLE001
            err_msg = str(error).lower()
            if "conflict" in err_msg or "409" in err_msg:
                self._log("Торрент уже загружен в qBittorrent (раздача не менялась).")
                return True
            raise QBittorrentError(f"Не удалось добавить торрент в qBittorrent: {error}") from error
        if str(result).lower().startswith("fail"):
            raise QBittorrentError(f"qBittorrent отказался добавить торрент: {result}")
        return True

    def find_hash_by_topic(self, topic_id: str) -> str | None:
        """Ищет хэш торрента, у которого в комментарии есть ID раздачи."""
        client = self._connect()
        for torrent in client.torrents_info():
            comment = getattr(torrent, "comment", "") or ""
            if topic_id in comment:
                self._log(f"Найден торрент в qBittorrent: {torrent.name} (hash {torrent.hash})")
                return torrent.hash
        return None

    def delete_torrent(self, torrent_hash: str, delete_files: bool) -> bool:
        client = self._connect()
        try:
            client.torrents_delete(torrent_hashes=torrent_hash, delete_files=delete_files)
            return True
        except NotFound404Error:
            return False
        except Exception as error:  # noqa: BLE001
            raise QBittorrentError(f"Не удалось удалить торрент из qBittorrent: {error}") from error

    def version(self) -> str:
        """Версия qBittorrent или ``"?"``, если подключиться не удалось."""
        try:
            return str(getattr(self._connect().app, "version", "?"))
        except Exception:  # noqa: BLE001 - версия нужна только для логов
            return "?"
