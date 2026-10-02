# Maintainer: autoupdate-torrents contributors
# Сборка:  makepkg -si   (или: paru -S autoupdate-torrents)

pkgname=autoupdate-torrents
pkgver=2.0.0
pkgrel=1
pkgdesc="Автообновление торрентов с rutracker с встроенным обходом блокировок (Antizapret PAC)"
arch=('any')
url="https://github.com/Vastre0/autoupdate-torrents"
license=('custom')
depends=('python' 'python-pyqt6' 'python-requests' 'python-beautifulsoup4')
optdepends=(
  'python-qbittorrent-api: клиент qBittorrent (AUR) — без него обновление раздач недоступно'
  'python-pysocks: поддержка SOCKS5-прокси (например, Tor)'
  'libnotify: уведомления рабочего стола в режиме --update'
  'qBittorrent: торрент-клиент, в который добавляются раздачи'
)
makedepends=('python-build' 'python-installer' 'python-wheel' 'python-setuptools' 'git')
source=("$pkgname::git+$url.git")
sha256sums=('SKIP')

pkgver() {
  cd "$pkgname"
  printf '2.0.0.r%s.%s' "$(git rev-list --count HEAD)" "$(git rev-parse --short HEAD)"
}

build() {
  cd "$pkgname"
  python -m build --wheel --no-isolation
}

package() {
  cd "$pkgname"
  python -m installer --destdir="$pkgdir" dist/*.whl

  install -Dm644 autoupdate-torrents.desktop \
    "$pkgdir/usr/share/applications/autoupdate-torrents.desktop"
  install -Dm644 torrent_manager/data/icon.png \
    "$pkgdir/usr/share/icons/hicolor/256x256/apps/autoupdate-torrents.png"

  install -Dm644 extras/autoupdate-torrents.service \
    "$pkgdir/usr/lib/systemd/user/autoupdate-torrents.service"
  install -Dm644 extras/autoupdate-torrents.timer \
    "$pkgdir/usr/lib/systemd/user/autoupdate-torrents.timer"

  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
}
