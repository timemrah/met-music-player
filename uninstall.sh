#!/bin/sh
# MP3 Çalar — kurulumu kaldırma (sudo gerekmez)
set -e
rm -f "$HOME/.local/bin/mp3-player" \
  "$HOME/.local/share/applications/mp3player.desktop" \
  "$HOME/.local/share/applications/com.emrah.mp3player.desktop" \
  "$HOME/.local/share/icons/hicolor/scalable/apps/mp3-player.svg"
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor/" 2>/dev/null || true
update-desktop-database "$HOME/.local/share/applications/" 2>/dev/null || true
echo "Kaldırıldı."
