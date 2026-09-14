# MP3 Çalar

Debian 13 + GNOME için sade, modern MP3 çalar. Ekstra paket gerekmez —
sistemde zaten kurulu olan GTK4 + Libadwaita + GStreamer kullanır.

## Özellikler

- Playlist: klasörü pencereye **sürükle-bırak** → içindeki MP3'ler listeye eklenir
- Tekli MP3 dosyaları da sürükle-bırak ile eklenebilir
- **Çift tıklama** ile çalma
- Sıralı otomatik devam + **karışık çal** düğmesi
- Önceki / Oynat-Duraklat / Sonraki, süre çubuğu (ses düzeyi sistemden ayarlanır)
- Delete tuşu ile seçili parçayı listeden çıkarma, tek tuşla listeyi temizleme
- Playlist otomatik saklanır (`~/.config/mp3-player/playlist.json`)

Ekolayzer ve animasyon yok — isteğe uygun olarak sade tutuldu.

## Çalıştırma

```sh
./run.sh
# veya
python3 main.py
```

Gerekenler (Debian 13'te öntanımlı kurulu): `python3-gi`,
`gir1.2-gtk-4.0`, `gir1.2-adw-1`, `gstreamer1.0-plugins-good`,
`gstreamer1.0-plugins-bad`, `gstreamer1.0-plugins-ugly`, `python3-mutagen`.

## GNOME menüsüne ekleme (önerilir)

```sh
./install.sh
```

Bu, uygulamalar menüsüne "MP3 Çalar" ekler ve `mp3-player` komutunu
`~/.local/bin` altına kurar. Kaldırmak için `uninstall.sh` çalıştırın.

## Kullanım

1. Müzik klasörünü pencereye sürükleyip bırakın.
2. Çalmak istediğiniz parçaya çift tıklayın.
3. Parçalar sırayla çalar; karışık isterseniz üstteki karışık düğmesini açın.
