#!/bin/sh
# MP3 Çalar — kurulumu kaldırma (sudo gerekmez)
set -e
rm -f "$HOME/.local/bin/mp3-player" "$HOME/.local/share/applications/mp3player.desktop"
update-desktop-database "$HOME/.local/share/applications/" 2>/dev/null || true
echo "Kaldırıldı."
