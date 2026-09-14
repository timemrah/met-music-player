#!/bin/sh
# MP3 Çalar — GNOME menüsüne kurulum (sudo gerekmez)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
printf '#!/bin/sh\nexec python3 "%s/main.py" "$@"\n' "$HERE" > "$HOME/.local/bin/mp3-player"
chmod +x "$HOME/.local/bin/mp3-player"
sed "s|^Exec=.*|Exec=$HOME/.local/bin/mp3-player|" "$HERE/mp3player.desktop" \
  > "$HOME/.local/share/applications/mp3player.desktop"
update-desktop-database "$HOME/.local/share/applications/" 2>/dev/null || true
echo "Kuruldu: uygulamalar menüsünde 'MP3 Çalar' olarak bulunur."
echo "Uçbirimden çalıştırmak için: mp3-player  (~/.local/bin PATH'te olmalı)"
