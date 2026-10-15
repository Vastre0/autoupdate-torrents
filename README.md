# autoupdate-torrents

Автообновление торрентов с **rutracker.org** в **qBittorrent** — версия для **CachyOS / Arch Linux**
со **встроенным обходом блокировок**.

Приложение следит за списком раздач и по команде (или по расписанию systemd) скачивает свежие
`.torrent` и отправляет их в qBittorrent, поэтому раздачи не «замерзают» без сидов.
Если rutracker заблокирован провайдером, запросы автоматически уходят через прокси
[Антизапрета](https://antizapret.prostovpn.org) — тот же список блокировок использует расширение
«Обход блокировок Рунета» для Firefox. Расширение и браузер при этом не нужны: обход встроен в программу.

```
┌────────────────────────┐      .torrent      ┌──────────────┐
│ rutracker.org (PAC)    │ ─────────────────► │ qBittorrent  │
│  напрямую / через прокси│                    │  Web API     │
└────────────────────────┘                    └──────────────┘
```

## Что изменилось по сравнению с прежней (Windows) версией

| Было | Стало |
|------|-------|
| Файлы рядом со скриптами | XDG-каталоги (`~/.config`, `~/.cache`, `~/.local/share`) |
| Трей только под Windows | Трей под Linux (KDE Plasma, XFCE, GNOME + AppIndicator) |
| Только GUI | GUI + CLI (`--update`, `--check`, `--import-cookies`, …) |
| Нет обновления по расписанию | Пользовательский таймер systemd |
| Прямые запросы к rutracker | Обход блокировок через PAC-скрипт Антизапрета + резервный прокси |
| Конфиг из одного файла рядом с программой | Тот же формат, но в `~/.config/autoupdate-torrents` (старые файлы переносятся автоматически) |

## Установка

### Вариант 1. Скрипт установки (рекомендуется)

```bash
git clone https://github.com/Vastre0/autoupdate-torrents.git
cd autoupdate-torrents
./install.sh                 # зависимости из pacman + venv + ярлык в меню
# ./install.sh --with-timer  # сразу настроить ежедневное обновление
# ./install.sh --autostart   # автозапуск окна при входе в систему
```

Скрипт поставит из репозиториев `python-pyqt6`, `python-requests`, `python-beautifulsoup4`,
создаст venv в `~/.local/share/autoupdate-torrents/venv` и положит ярлык `~/.local/bin/autoupdate-torrents`.

### Вариант 2. PKGBUILD (AUR/makepkg)

```bash
git clone https://github.com/Vastre0/autoupdate-torrents.git && cd autoupdate-torrents
makepkg -si          # или: paru -S autoupdate-torrents, если пакет опубликован в AUR
```

### Вариант 3. Вручную

```bash
sudo pacman -S python-pyqt6 python-requests python-beautifulsoup4
paru -S python-qbittorrent-api     # клиент qBittorrent (есть только в AUR)
python -m venv --system-site-packages ~/.local/share/autoupdate-torrents/venv
~/.local/share/autoupdate-torrents/venv/bin/pip install --no-deps .
```

Необязательно: `python-pysocks` (для SOCKS5-прокси, например Tor), `libnotify` (уведомления в `--update`).

## Быстрый старт

### 1. Куки rutracker

1. Войдите в свой аккаунт на <https://rutracker.org> в браузере.
2. Нажмите `F12` → вкладка **Сеть** (Network) → `F5` → кликните на запрос к `rutracker.org` (`index.php` или `viewtopic.php`).
3. В правой панели в разделе **Заголовки запроса** (Request Headers) скопируйте значение строки `Cookie:` целиком (нужны ключи `bb_session`, `bb_ssl`, `bb_guid`, `bb_t`).
4. В приложении нажмите кнопку **«Импорт куки»** (вверху слева) → **«📋 Вставить из буфера»** → **«Сохранить»**.
   Либо из терминала:

```bash
autoupdate-torrents --import-cookies "bb_session=...; bb_ssl=1; bb_guid=..."
```

Куки сохраняются в `~/.config/autoupdate-torrents/cookies.json` (с правами 600). Со временем сессия на трекере истекает — тогда просто повторите эти шаги.

### 2. qBittorrent

1. В qBittorrent откройте: **Инструменты → Настройки → Веб-интерфейс**.
2. Включите галочку **«Веб-интерфейс (дистанционное управление)»**.
3. Укажите порт (по умолчанию `8080`, если занят — например `8085`), имя пользователя (`admin`) и пароль.
4. В приложении откройте: **Настройки → qBittorrent**, укажите адрес (например `localhost:8080` или `localhost:8085`), имя и пароль, затем нажмите **«Проверить подключение»**.

![Веб-интерфейс qBittorrent](images/screenshot_1.png)
![Настройки qBittorrent](images/screenshot_2.png)

### 3. Добавление раздач

1. **Ссылка:** вставьте ссылку на страницу темы (например, `https://rutracker.org/forum/viewtopic.php?t=1234567`). Кнопка 📋 вставляет из буфера обмена.
2. **Папка:** укажите путь, куда qBittorrent сохраняет файлы этой раздачи.
3. Нажмите **«Добавить в отслеживание»**, затем **«Обновить все торренты»**.

Дальше достаточно периодически нажимать «Обновить все торренты» или включить автообновление по таймеру systemd (см. ниже).

## Обход блокировок

Обход работает так же, как расширение «Обход блокировок Рунета» для Firefox:

1. Приложение скачивает PAC-скрипт Антизапрета (зеркала:
   `antizapret.prostovpn.org:8443`, `:18443`, `e.cen.rodeo:8443`, …) и кэширует его в
   `~/.cache/autoupdate-torrents/pac` (по умолчанию обновление раз в 12 часов).
2. PAC-скрипт разбирается нативно в Python: LZP-сжатые списки доменов, база заблокированных
   IP и подсетей, словари подстановок.
3. Для каждого запроса программа решает, нужен ли прокси: если хост есть в списке —
   запрос идёт через прокси Антизапрета, если нет — напрямую.
4. Если запрос «напрямую» оборвался (типичный признак блокировки у провайдера), он
   автоматически повторяется через прокси.

Маршрутизация запроса выполняется в таком порядке: явно включённый системный
proxy из `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`, ручной proxy (если задан),
прокси из PAC, затем прямой маршрут. Поэтому VPN на роутере с прозрачной маршрутизацией не требует
настройки proxy в приложении — оставьте системный proxy выключенным. Если VPN
предоставляет локальный HTTP/SOCKS5 endpoint, включите системный proxy или задайте
его в поле «Резервный прокси».

Проверить решение по конкретному хосту:

```bash
autoupdate-torrents --check-host rutracker.org
autoupdate-torrents --check-host rutracker.org --no-bypass   # сравнить с прямым доступом
```

> **Важно.** Списки Антизапрета отдаются только по российским IP-адресам: если вы за границей,
> сервер вернёт «Your geoip is not RU». В этом случае укажите свой прокси (см. ниже) или
> включите VPN на время обновления PAC.

### Свой прокси / Официальный плагин RuTracker / Tor

Если PAC Антизапрета блокируется защитой Cloudflare (ошибка `HTTP 403 / Cloudflare Challenge`) или недоступен:

```bash
autoupdate-torrents --set-proxy https://ps1.blockme.site:443  # официальный прокси плагина RuTracker
autoupdate-torrents --set-proxy socks5://127.0.0.1:9050       # Tor
autoupdate-torrents --set-proxy http://127.0.0.1:8118         # Privoxy
```

Или в приложении: **Настройки → Обход блокировок → Резервный прокси**.
Если задан ручной прокси, программа обращается через него в первую очередь, минуя Cloudflare и задержки.
Для SOCKS5 нужен пакет `python-pysocks` (`sudo pacman -S python-pysocks`).

Полностью отключить обход: `--no-bypass` (или снять галочку в настройках).

## Командная строка

```bash
autoupdate-torrents                     # графический интерфейс (по умолчанию)
autoupdate-torrents --update            # разово обновить все раздачи (код возврата 0/1)
autoupdate-torrents --update --notify   # + уведомление рабочего стола
autoupdate-torrents --check             # диагностика: куки, qBittorrent, PAC, rutracker
autoupdate-torrents --list              # список отслеживаемых раздач
autoupdate-torrents --refresh-pac       # перекачать PAC-скрипт
autoupdate-torrents --check-host HOST   # нужен ли прокси для хоста
autoupdate-torrents --import-cookies -  # куки из stdin
autoupdate-torrents --set-qbittorrent localhost:8080 admin adminadmin
autoupdate-torrents --print-paths       # используемые каталоги
autoupdate-torrents --install-service   # таймер systemd (systemctl --user)
autoupdate-torrents --enable-autostart  # автозапуск при входе в сессию
```

## Расписание и автозапуск

```bash
autoupdate-torrents --install-service
systemctl --user list-timers autoupdate-torrents.timer
journalctl --user -u autoupdate-torrents.service -n 50
```

Таймер обновляет раздачи ежедневно в 04:30 (со случайным разбросом ±30 минут) и догоняет
пропущенный запуск после выключенного компьютера. Всё настраивается в
**Настройки → Система**, шаблоны unit-файлов лежат в `extras/`.

## Файлы и каталоги

| Что | Где |
|-----|-----|
| Куки rutracker | `~/.config/autoupdate-torrents/cookies.json` |
| Список раздач | `~/.config/autoupdate-torrents/torrent_config.json` |
| Настройки | `~/.config/autoupdate-torrents/user-config.json` |
| Кэш PAC-скрипта | `~/.cache/autoupdate-torrents/pac/` |
| venv (при установке скриптом) | `~/.local/share/autoupdate-torrents/venv` |

Файлы старой версии (`cookies.json`, `torrent_config.json`, `user-config.json` рядом со скриптами)
переносятся в XDG-каталог при первом запуске.

## Если что-то не работает

| Симптом | Что делать |
|---------|------------|
| «Куки rutracker.org не найдены» | Импортировать строку Cookie (см. выше) |
| «Похоже, куки недействительны» | Куки истекли — обновите их |
| «Не удалось скачать PAC-скрипт» | Проверьте интернет; `--check-host`; при геоблокировке задайте свой прокси |
| `--update` падает с ошибкой qBittorrent | Включите веб-интерфейс qBittorrent и проверьте хост/пароль в настройках |
| `ModuleNotFoundError: qbittorrentapi` | `paru -S python-qbittorrent-api` или `pip install --user qbittorrent-api` |
| SOCKS5-прокси не работает | `sudo pacman -S python-pysocks` |
| Нет иконки в трее (GNOME) | Установите расширение *AppIndicator and KStatusNotifierItem Support* |
| Торрент добавляется, но не качается | Проверьте путь сохранения и права на папку |

Подробная диагностика: `autoupdate-torrents --check`.

## Разработка

```
torrent_manager/
├── antizapret.py   # разбор PAC: LZP, списки домен/IP, определение «нужен прокси»
├── bypass.py       # загрузка/кэш PAC, выбор маршрута, резервный прокси
├── torrents.py     # rutracker (с обходом) и qBittorrent Web API
├── service.py      # прикладная логика (используют GUI и CLI)
├── cli.py          # командный интерфейс
├── config.py       # настройки (XDG)
├── cookies.py      # куки rutracker
├── torrent_store.py# список отслеживаемых раздач
├── integration.py  # автозапуск и таймер systemd
├── gui/            # PyQt6: окно, настройки, трей
└── data/           # иконки и стили
tests/              # unittest: PAC, обход, сервис, CLI, GUI (headless)
```

```bash
python -m unittest discover -v            # все тесты
QT_QPA_PLATFORM=offscreen python -m unittest tests.test_gui_smoke
python -m torrent_manager                 # запуск из репозитория
```

Тесты не обращаются к сети: PAC-скрипт генерируется в формате Антизапрета
(`tests/pac_fixture.py`), включая LZP-сжатие, словари подстановок и base36-дельты IP.

## Благодарности

* [antizapret / prostovpn.org](https://antizapret.prostovpn.org) — PAC-скрипты и списки блокировок.
* [anticensority/runet-censorship-bypass](https://github.com/anticensority/runet-censorship-bypass)
  («Обход блокировок Рунета», GPL-3.0) — формат PAC-скрипта, который реализован здесь нативно.
* [antizapret-pac-generator-light](https://bitbucket.org/anticensority/antizapret-pac-generator-light) —
  генератор PAC (LZP-сжатие, схема `domains`, `d_ipaddr`, `special`).

Приложение использует эти списки только для доступа к контенту, который вам доступен по закону;
ответственность за использование — на пользователе.
