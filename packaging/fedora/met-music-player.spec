Name:           met-music-player
Version:        1.0.0
Release:        1%{?dist}
Summary:        Minimal modern MP3 player (GTK4 + Libadwaita + GStreamer)
# Sürüm etiketine (vX.Y.Z) karşılık gelir; CI --define "version" ile ezer.
License:        MIT
URL:            https://github.com/timemrah/met-music-player
Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz

BuildArch:      noarch
Requires:       python3
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       gstreamer1
Requires:       gstreamer1-plugins-base
Requires:       gstreamer1-plugins-good
Requires:       gstreamer1-plugins-bad-free
Requires:       gstreamer1-plugins-ugly-free
Requires:       python3-mutagen
Recommends:     pipewire-gstreamer

%description
MET Music Player is a minimal MP3 player with drag-and-drop playlist,
shuffle mode, seek bar and a live spectrum analyzer. It is built on the
system GTK4 + Libadwaita + GStreamer stack and bundles no libraries.

%prep
%setup -q

%install
install -D -m 0755 main.py %{buildroot}%{_datadir}/met-music-player/main.py
install -D -m 0644 logo.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/mp3-player.svg
install -D -m 0644 com.emrah.mp3player.desktop %{buildroot}%{_datadir}/applications/com.emrah.mp3player.desktop
install -D -m 0644 LICENSE %{buildroot}%{_licensedir}/%{name}/LICENSE
mkdir -p %{buildroot}%{_bindir}
ln -s %{_datadir}/met-music-player/main.py %{buildroot}%{_bindir}/mp3-player

%files
%{_bindir}/mp3-player
%{_datadir}/met-music-player/main.py
%{_datadir}/icons/hicolor/scalable/apps/mp3-player.svg
%{_datadir}/applications/com.emrah.mp3player.desktop
%{_licensedir}/%{name}/LICENSE

%changelog
* Mon Sep 15 2026 Mehmet Emrah TUNÇEL <timemrah@gmail.com> - 1.0.0-1
- İlk sürüm: sürükle-bırak playlist, karışık çalma, canlı spektrum.
