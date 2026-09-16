#!/bin/sh
# MP3 Çalar — GNOME menüsüne kurulum (sudo gerekmez)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" \
  "$HOME/.local/share/icons/hicolor/scalable/apps"
cp "$HERE/logo.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/mp3-player.svg"
printf '#!/bin/sh\nexec python3 "%s/main.py" "$@"\n' "$HERE" > "$HOME/.local/bin/mp3-player"
chmod +x "$HOME/.local/bin/mp3-player"
sed "s|^Exec=.*|Exec=$HOME/.local/bin/mp3-player|" "$HERE/com.emrah.mp3player.desktop" \
  > "$HOME/.local/share/applications/com.emrah.mp3player.desktop"
rm -f "$HOME/.local/share/applications/mp3player.desktop"
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor/" 2>/dev/null || true
update-desktop-database "$HOME/.local/share/applications/" 2>/dev/null || true
echo "Kuruldu: uygulamalar menüsünde 'MET Music Player' olarak bulunur."
echo "Uçbirimden çalıştırmak için: mp3-player  (~/.local/bin PATH'te olmalı)"
