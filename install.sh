#!/usr/bin/env bash
# Установка Torrent Manager на CachyOS / Arch Linux (и другие pacman-дистрибутивы).
#
#   ./install.sh                 # установить для текущего пользователя
#   ./install.sh --with-timer    # + пользовательский таймер systemd (обновление раз в сутки)
#   ./install.sh --autostart     # + автозапуск окна при входе в систему
#   ./install.sh --uninstall     # удалить
#
# Скрипт ставит зависимости из официальных репозиториев через pacman,
# а python-qbittorrent-api (его нет в репозиториях) — в отдельный venv.

set -euo pipefail

APP_NAME="autoupdate-torrents"
APP_TITLE="Torrent Manager"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_NAME"
VENV_DIR="$DATA_DIR/venv"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

PACMAN_PACKAGES=(python python-pyqt6 python-requests python-beautifulsoup4)
OPTIONAL_PACKAGES=(python-pysocks libnotify)

WITH_TIMER=0
WITH_AUTOSTART=0
UNINSTALL=0
SKIP_PACMAN=0

for arg in "$@"; do
  case "$arg" in
    --with-timer) WITH_TIMER=1 ;;
    --autostart) WITH_AUTOSTART=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --skip-pacman) SKIP_PACMAN=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "Неизвестный параметр: $arg" >&2
      exit 2
      ;;
  esac
done

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# ------------------------------------------------------------------ удаление
if [[ $UNINSTALL -eq 1 ]]; then
  info "Удаление $APP_TITLE..."
  have systemctl && systemctl --user disable --now "$APP_NAME.timer" 2>/dev/null || true
  rm -f "$SYSTEMD_DIR/$APP_NAME.service" "$SYSTEMD_DIR/$APP_NAME.timer"
  have systemctl && systemctl --user daemon-reload 2>/dev/null || true
  rm -f "$AUTOSTART_DIR/$APP_NAME.desktop"
  rm -f "$BIN_DIR/$APP_NAME"
  rm -f "$APPS_DIR/$APP_NAME.desktop"
  rm -f "$ICON_DIR/$APP_NAME.png"
  rm -rf "$DATA_DIR"
  info "Готово. Конфиги и куки оставлены в ${XDG_CONFIG_HOME:-$HOME/.config}/$APP_NAME"
  exit 0
fi

# ------------------------------------------------------------------- pacman
if [[ $SKIP_PACMAN -eq 0 ]]; then
  if have pacman; then
    info "Установка зависимостей из репозиториев Arch (нужен sudo):"
    echo "    ${PACMAN_PACKAGES[*]}"
    sudo pacman -S --needed --noconfirm "${PACMAN_PACKAGES[@]}"
    if ! pacman -Qq python-pysocks >/dev/null 2>&1; then
      warn "Необязательный пакет python-pysocks не установлен — SOCKS5-прокси (Tor) будет недоступен."
      warn "Установить: sudo pacman -S python-pysocks"
    fi
  else
    warn "pacman не найден — пропускаю установку системных пакетов."
    warn "Убедитесь, что установлены: PyQt6, requests, beautifulsoup4."
  fi
else
  info "Установка системных пакетов пропущена (--skip-pacman)."
fi

# ---------------------------------------------------------------------- venv
info "Создание venv: $VENV_DIR"
mkdir -p "$DATA_DIR" "$BIN_DIR" "$APPS_DIR" "$ICON_DIR"
python3 -m venv --system-site-packages --upgrade-deps "$VENV_DIR"

info "Установка python-зависимостей (qbittorrent-api) в venv"
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
"$VENV_DIR/bin/python" -m pip install --quiet qbittorrent-api

info "Установка самого приложения"
"$VENV_DIR/bin/python" -m pip install --quiet --no-deps --upgrade "$SOURCE_DIR"

# ------------------------------------------------------------------- ярлыки
info "Создание ярлыка $BIN_DIR/$APP_NAME"
cat > "$BIN_DIR/$APP_NAME" <<EOF
#!/bin/sh
# Запуск Torrent Manager из пользовательского venv.
exec "$VENV_DIR/bin/$APP_NAME" "\$@"
EOF
chmod 755 "$BIN_DIR/$APP_NAME"

info "Установка .desktop и иконки"
install -m 644 "$SOURCE_DIR/autoupdate-torrents.desktop" "$APPS_DIR/$APP_NAME.desktop"
install -m 644 "$SOURCE_DIR/torrent_manager/data/icon.png" "$ICON_DIR/$APP_NAME.png"
have update-desktop-database && update-desktop-database "$APPS_DIR" 2>/dev/null || true
have gtk-update-icon-cache && gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true

# ------------------------------------------------------------- интеграции
if [[ $WITH_TIMER -eq 1 ]]; then
  info "Настройка таймера systemd (systemctl --user)"
  "$VENV_DIR/bin/$APP_NAME" --install-service || warn "Не удалось включить таймер, сделайте это вручную."
fi

if [[ $WITH_AUTOSTART -eq 1 ]]; then
  info "Добавление в автозапуск"
  "$VENV_DIR/bin/$APP_NAME" --enable-autostart
fi

# ------------------------------------------------------------------- итоги
if ! echo ":$PATH:" | grep -q ":$BIN_DIR:"; then
  warn "Каталог $BIN_DIR отсутствует в PATH."
  warn 'Добавьте в ~/.bashrc или ~/.zshrc:  export PATH="$HOME/.local/bin:$PATH"'
fi

cat <<EOF

Готово! Что дальше:

1. Запуск:            $APP_NAME            (или через меню приложений)
2. Импорт куки:       $APP_NAME --import-cookies "bb_session=...; bb_ssl=1"
   либо в приложении кнопкой «Импорт куки из буфера».
3. Диагностика:       $APP_NAME --check
4. Обновление раздач: $APP_NAME --update   (для таймера/скриптов)

Конфиги и куки: ${XDG_CONFIG_HOME:-$HOME/.config}/$APP_NAME
Кэш PAC-скрипта: ${XDG_CACHE_HOME:-$HOME/.cache}/$APP_NAME
EOF
