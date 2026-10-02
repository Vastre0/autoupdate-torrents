"""Командный интерфейс приложения.

Примеры:

* ``autoupdate-torrents`` — графический интерфейс;
* ``autoupdate-torrents --update`` — разово обновить все раздачи (systemd-таймер);
* ``autoupdate-torrents --check`` — проверить куки, qBittorrent и обход блокировок;
* ``autoupdate-torrents --import-cookies "bb_session=...; ..."`` — сохранить куки;
* ``autoupdate-torrents --install-service`` — поставить пользовательский таймер systemd.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from . import __version__
from . import paths
from .config import ConfigManager
from .cookies import HELP_TEXT

EXIT_OK = 0
EXIT_FAILURE = 1


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autoupdate-torrents",
        description="Автообновление торрентов с rutracker (CachyOS/Arch) с встроенным обходом блокировок.",
        epilog=HELP_TEXT,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"autoupdate-torrents {__version__}")

    mode = parser.add_argument_group("режимы работы")
    mode.add_argument("--update", action="store_true", help="обновить все раздачи и выйти")
    mode.add_argument("--check", action="store_true", help="проверить куки, qBittorrent и PAC-скрипт")
    mode.add_argument("--list", action="store_true", help="показать отслеживаемые раздачи")
    mode.add_argument("--refresh-pac", action="store_true", help="перекачать PAC-скрипт Антизапрета")
    mode.add_argument("--check-host", metavar="HOST", help="объяснить, нужен ли прокси для хоста")
    mode.add_argument("--notify", action="store_true", help="показать уведомление рабочего стола по итогам")

    settings = parser.add_argument_group("настройки")
    settings.add_argument(
        "--import-cookies",
        metavar="СТРОКА",
        help="сохранить куки из строки браузера (значение «-» — прочитать из stdin)",
    )
    settings.add_argument("--set-qbittorrent", nargs=3, metavar=("HOST", "USER", "PASSWORD"),
                          help="задать параметры веб-интерфейса qBittorrent")
    settings.add_argument("--set-proxy", metavar="URL",
                          help="задать резервный прокси, например socks5://127.0.0.1:9050")
    settings.add_argument("--no-bypass", action="store_true", help="отключить обход блокировок")
    settings.add_argument("--enable-bypass", action="store_true", help="включить обход блокировок")

    system = parser.add_argument_group("интеграция с системой")
    system.add_argument("--install-service", action="store_true",
                        help="установить и включить пользовательский таймер systemd")
    system.add_argument("--uninstall-service", action="store_true", help="выключить таймер systemd")
    system.add_argument("--enable-autostart", action="store_true", help="добавить приложение в автозапуск")
    system.add_argument("--disable-autostart", action="store_true", help="убрать приложение из автозапуска")
    system.add_argument("--print-paths", action="store_true", help="показать используемые каталоги")

    parser.add_argument("--quiet", action="store_true", help="минимум вывода (для таймера)")
    parser.add_argument("--verbose", action="store_true", help="подробный вывод")
    return parser


class _Logger:
    def __init__(self, quiet: bool = False):
        self.quiet = quiet

    def __call__(self, message: str) -> None:
        if self.quiet:
            return
        print(f"[{_timestamp()}] {message}", flush=True)


def _build_service(log, config: ConfigManager):
    from .service import TorrentService

    return TorrentService(config=config, log=log)


def _run_update(args, log, config: ConfigManager) -> int:
    from .notify import notify
    from .torrents import QBittorrentError, RutrackerError

    service = _build_service(log, config)
    try:
        result = service.update_all(progress=None)
    except (QBittorrentError, RutrackerError) as error:
        log(f"Обновление не выполнено: {error}")
        if args.notify:
            notify(f"Обновление не выполнено: {error}")
        return EXIT_FAILURE
    if args.notify:
        notify(result.summary())
    return EXIT_OK if result.ok() else EXIT_FAILURE


def _run_check(log, config: ConfigManager) -> int:
    service = _build_service(log, config)
    report = service.diagnostics()
    log("Проверка окружения:")
    log(f"  Каталог конфигов: {report['paths']['config']}")
    log(f"  Каталог кэша:     {report['paths']['cache']}")

    cookies_info = report["cookies"]
    log(f"  Куки: {'OK' if cookies_info['ok'] else 'НЕТ'} ({cookies_info['path']})")
    for problem in cookies_info["problems"]:
        log(f"    ! {problem}")

    qb_info = report["qbittorrent"]
    log(f"  qBittorrent: {'OK' if qb_info['ok'] else 'ОШИБКА'} — {qb_info['message']}")

    bypass = report["bypass"]
    proxy = bypass.get("proxy") or bypass.get("manual_proxy") or "—"
    log(f"  Обход блокировок: {'включён' if bypass['enabled'] else 'выключен'}, "
        f"источник PAC: {bypass.get('source') or '—'}")
    log(f"    доменов: {bypass.get('domains', 0)}, IP: {bypass.get('blocked_ips', 0)}, прокси: {proxy}")
    if bypass.get("error"):
        log(f"    ! {bypass['error']}")

    rutracker = report.get("rutracker", {})
    log(f"  Rutracker: {'OK' if rutracker.get('ok') else 'ОШИБКА'} — {rutracker.get('message', '')}")

    ok = bool(cookies_info["ok"]) and bool(qb_info["ok"])
    return EXIT_OK if ok else EXIT_FAILURE


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    log = _Logger(quiet=args.quiet and not args.verbose)

    try:
        paths.ensure_dirs()
    except OSError as error:
        print(f"Не удалось создать каталоги конфигов: {error}", file=sys.stderr)

    migrated = paths.migrate_legacy_files()
    for source, target in migrated:
        log(f"Файлы старой версии скопированы: {source} → {target}")

    config = ConfigManager()

    # --- Изменение настроек ------------------------------------------------
    changed = False
    if args.import_cookies is not None:
        from .cookies import parse_cookie_string, save_cookies, validate_cookies

        raw = args.import_cookies
        if raw.strip() == "-":
            raw = sys.stdin.read()
        parsed = parse_cookie_string(raw)
        if not parsed:
            log("Не удалось разобрать куки — строка пуста или неизвестный формат.")
            return EXIT_FAILURE
        for problem in validate_cookies(parsed):
            log(f"Предупреждение: {problem}")
        log(f"Куки сохранены: {save_cookies(parsed)}")
        changed = True

    if args.set_qbittorrent:
        host, username, password = args.set_qbittorrent
        config.set_section("qbittorrent", {"host": host, "username": username, "password": password})
        log("Параметры qBittorrent сохранены.")
        changed = True

    if args.set_proxy is not None:
        config.set_section("bypass", {"manual_proxy": args.set_proxy})
        log(f"Резервный прокси: {args.set_proxy or 'не задан'}")
        changed = True

    if args.no_bypass:
        config.set_section("bypass", {"enabled": False})
        log("Обход блокировок выключен.")
        changed = True

    if args.enable_bypass:
        config.set_section("bypass", {"enabled": True})
        log("Обход блокировок включён.")
        changed = True

    if changed:
        config.save()

    # --- Системная интеграция ---------------------------------------------
    if args.enable_autostart or args.disable_autostart:
        from .integration import set_autostart

        target = set_autostart(args.enable_autostart)
        log(f"Автозапуск: {'включён (' + str(target) + ')' if target else 'выключен'}")

    if args.install_service:
        from .integration import enable_systemd_timer, install_systemd_units

        service_path, timer_path = install_systemd_units()
        log(f"Unit-файлы созданы: {service_path}, {timer_path}")
        ok, message = enable_systemd_timer()
        log(message)
        if not ok:
            log("Включите вручную: systemctl --user enable --now autoupdate-torrents.timer")
        return EXIT_OK if ok else EXIT_FAILURE

    if args.uninstall_service:
        from .integration import disable_systemd_timer

        ok, message = disable_systemd_timer()
        log(message)
        return EXIT_OK if ok else EXIT_FAILURE

    if args.print_paths:
        log(f"Конфиги: {paths.config_dir()}")
        log(f"Кэш:     {paths.cache_dir()}")
        log(f"Данные:  {paths.data_dir()}")
        return EXIT_OK

    # --- Остальные режимы ---------------------------------------------------
    if args.refresh_pac:
        service = _build_service(log, config)
        config.save()
        return EXIT_OK if service.refresh_pac(force=True) else EXIT_FAILURE

    if args.check_host:
        service = _build_service(log, config)
        config.save()
        log(service.check_host(args.check_host))
        return EXIT_OK

    if args.list:
        from .torrent_store import TorrentStore

        store = TorrentStore(log=log)
        tracked = store.items()
        if not tracked:
            log("Список отслеживаемых раздач пуст.")
            return EXIT_OK
        for topic_id, data in tracked.items():
            log(f"  {topic_id}  {data.get('save_path', '')}")
        log(f"Всего: {len(tracked)}")
        return EXIT_OK

    if args.update:
        config.save()
        return _run_update(args, log, config)

    if args.check:
        config.save()
        return _run_check(log, config)

    # Если меняли только настройки (например, `--import-cookies`) — выходим.
    if changed:
        return EXIT_OK

    # --- Графический интерфейс ---------------------------------------------
    config.save()
    try:
        from .gui.app import run_gui

        return run_gui(config=config)
    except ImportError as error:
        print(
            "Не удалось загрузить графический интерфейс (нужен PyQt6):\n"
            f"  {error}\n"
            "CachyOS/Arch: sudo pacman -S python-pyqt6\n"
            "Остальные режимы работают без графики: --update, --check, --list.",
            file=sys.stderr,
        )
        return EXIT_FAILURE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
