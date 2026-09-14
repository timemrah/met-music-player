#!/bin/sh
# MP3 Çalar başlatıcı — ek paket gerekmez (sistem GTK4 + GStreamer kullanır)
exec python3 "$(dirname "$0")/main.py" "$@"
