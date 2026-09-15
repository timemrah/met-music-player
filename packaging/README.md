# Paketleme

Yerli paketler + AppImage, GitHub Actions ile derlenir
([release.yml](../.github/workflows/release.yml)).

## Dosyalar

- `../debian/` — Debian/Ubuntu paketi (`met-music-player_*.deb`).
  Derleme: `dpkg-buildpackage -us -uc -b` (Build-Depends: `debhelper`).
- `fedora/met-music-player.spec` — Fedora paketi (`*.rpm`).
  Derleme: `rpmbuild -bb packaging/fedora/met-music-player.spec`.
- `arch/PKGBUILD` — AUR paketi. AUR'a gönderim ayrı bir depodan yapılır:
  ```sh
  updpkgsums && makepkg --printsrcinfo > .SRCINFO
  git push aur master   # ssh://aur@aur.archlinux.org/met-music-player.git
  ```
- `appimage/AppImageBuilder.yml` — taşınabilir AppImage tarifi
  (Ubuntu 24.04 tabanlı; glibc 2.39 → Debian 13/güncel Fedora/Arch'ta çalışır).
  Yerel derleme: `cd appimage && appimage-builder --recipe AppImageBuilder.yml --skip-test`.

## Sürüm çıkarma

1. Dört yerdeki sürümü eşitle: `debian/changelog`, `fedora/*.spec`
   (`Version:`), `arch/PKGBUILD` (`pkgver`), `appimage/AppImageBuilder.yml`
   (`app_info` altındaki `version:` — en üstteki `version: 1` şema sürümüdür).
2. `git tag vX.Y.Z && git push --tags`
3. Actions `.deb` + `.rpm` + `.AppImage` derleyip Release'e ekler.
4. AUR için yukarıdaki `updpkgsums` adımını yapıp AUR deposuna push'la.

Her itişte (sürüm dışı) `.deb` ve `.rpm` derlenerek paketleme çürümesi
erken yakalanır; AppImage yalnızca etiketlerde derlenir (yavaş iştir).
