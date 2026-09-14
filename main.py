#!/usr/bin/env python3
"""Sade modern MP3 çalar — Debian 13 + GNOME (GTK4 + Libadwaita + GStreamer).

Özellikler:
- Klasörü pencereye sürükle-bırak -> içindeki mp3'ler playliste eklenir
- Tekli mp3 dosyaları da sürükle-bırak ile eklenebilir
- Çift tıklama ile çalma, sıra ile otomatik devam, karışık çalma modu
- Önceki / Oynat-Duraklat / Sonraki, süre çubuğu (seek)
- Çalarken gerçek spektrum verisiyle (60 FPS hedefli), peak tutuculu ekolayzer
- Playlist oturumlar arası saklanır (~/.config/mp3-player/playlist.json)
"""
import json
import os
import random
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gst, Gtk  # noqa: E402

try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3NoHeaderError
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

APP_ID = "com.emrah.mp3player"
CONFIG_DIR = Path(GLib.get_user_config_dir()) / "mp3-player"
PLAYLIST_FILE = CONFIG_DIR / "playlist.json"


def fmt_time(seconds):
    """Saniyeyi m:ss veya h:mm:ss formatına çevirir."""
    if seconds is None or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def resolve_duration(path, info):
    """Xing başlığı bozuksa (0 süre) dosya boyutu/bit hızından tahmin eder."""
    length = getattr(info, "length", 0) or 0
    if length > 0:
        return float(length)
    bitrate = getattr(info, "bitrate", 0) or 0
    if bitrate > 0:
        try:
            return os.path.getsize(path) * 8 / bitrate
        except OSError:
            return None
    return None


def track_info(path):
    """MP3 dosyasından başlık ve süre bilgisini okur."""
    title = Path(path).stem
    duration = None
    if HAS_MUTAGEN:
        try:
            audio = MP3(path)
            if audio.info is not None:
                duration = resolve_duration(path, audio.info)
            tags = audio.tags
            if tags is not None:
                for key in ("TIT2", "TIT"):
                    if key in tags:
                        title = str(tags[key].text[0])
                        break
        except Exception:
            pass
    return title, duration


_SPEC_FLOOR_DB = -57.0
_SPEC_FALL_PER_SEC = 0.8


def spec_level(db, index, bands):
    """dB büyüklüğünü 0..1 çubuk seviyesine çevirir; tiz bantlara telafi uygular."""
    try:
        db = float(db)
    except (TypeError, ValueError):
        return 0.0
    if db <= _SPEC_FLOOR_DB + 1.0:
        return 0.0
    base = (db - _SPEC_FLOOR_DB) / -_SPEC_FLOOR_DB
    comp = 1.0 + 1.2 * (index / max(1, bands - 1))
    return max(0.0, min(1.0, base * comp))


def peak_step(peak, hold_until, level, now, dt, fall=_SPEC_FALL_PER_SEC):
    """Peak-hold: yükselince 0.5 sn tut, sonra yavaşça düş, çubuğa değince dur."""
    if level >= peak:
        return level, now + 0.5
    if now >= hold_until:
        return max(level, peak - fall * max(0.0, dt)), hold_until
    return peak, hold_until


_LOG_BARS = 28
_LOG_FMIN = 30.0
_LOG_FMAX = 16000.0
_LOG_NYQ = 22050.0
_LOG_LIN_BANDS = 2048


def _log_groups(lin_bands=_LOG_LIN_BANDS, bars=_LOG_BARS,
                fmin=_LOG_FMIN, fmax=_LOG_FMAX, nyq=_LOG_NYQ):
    edges = [fmin * (fmax / fmin) ** (b / bars) for b in range(bars + 1)]
    width = nyq / lin_bands
    groups = []
    for b in range(bars):
        idx = [k for k in range(lin_bands)
               if edges[b] <= (k + 0.5) * width < edges[b + 1]]
        if not idx:
            idx = [min(lin_bands - 1, max(0, int((edges[b] + edges[b + 1]) / 2 / width)))]
        groups.append(idx)
    return groups


_GROUPS_CACHE = {_LOG_LIN_BANDS: _log_groups()}


def log_rebin(mags):
    """Lineer bantları 28 logaritmik bara indirir (grup içi tepe değerle)."""
    mags = list(mags)
    n = len(mags)
    if n == _LOG_BARS:
        return mags
    grp = _GROUPS_CACHE.get(n)
    if grp is None:
        grp = _log_groups(lin_bands=n)
        _GROUPS_CACHE[n] = grp
    return [max(mags[k] for k in g) for g in grp]


class Mp3PlayerWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("MP3 Çalar")
        self.set_icon_name("mp3-player")
        self.set_default_size(720, 540)

        Gst.init(None)
        factory = Gst.ElementFactory.find("playbin3")
        self.player = Gst.ElementFactory.make("playbin3" if factory else "playbin", "player")
        self.player.set_property("volume", 1.0)
        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", self._on_eos)
        bus.connect("message::error", self._on_error)
        bus.connect("message::element", self._on_element)
        self._spectrum = self._setup_spectrum_sink()

        self.playlist = []  # {"path": str, "title": str, "duration": float|None}
        self.current = -1
        self.playing = False
        self.shuffle = False
        self._av_delay = 0.35
        self._spec_gen = 0
        self._tick_n = 0
        self._updating_scale = False
        self._duration_ns = 0

        self._build_ui()
        self._setup_dnd()
        self._load_playlist()
        self._refresh_list()
        GLib.timeout_add(500, self._tick)

    # ---- Arayüz ----
    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root)

        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="MP3 Çalar"))
        root.append(header)

        btn_folder = Gtk.Button(icon_name="folder-open-symbolic", tooltip_text="Klasör aç")
        btn_folder.connect("clicked", self._on_open_folder)
        header.pack_start(btn_folder)

        btn_files = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="MP3 dosyası ekle")
        btn_files.connect("clicked", self._on_open_files)
        header.pack_start(btn_files)

        self.btn_shuffle = Gtk.ToggleButton(
            icon_name="media-playlist-shuffle-symbolic", tooltip_text="Karışık çal"
        )
        self.btn_shuffle.connect("toggled", self._on_shuffle_toggled)
        header.pack_end(self.btn_shuffle)

        btn_clear = Gtk.Button(icon_name="edit-clear-all-symbolic", tooltip_text="Listeyi temizle")
        btn_clear.connect("clicked", self._on_clear)
        header.pack_end(btn_clear)

        self.empty_label = Gtk.Label(
            label="Başlamak için bir klasörü buraya sürükleyip bırakın\nveya sol üstten Klasör açın",
            justify=Gtk.Justification.CENTER,
        )
        self.empty_label.add_css_class("dim-label")
        self.empty_label.set_vexpand(True)
        self.empty_label.set_valign(Gtk.Align.CENTER)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("boxed-list")

        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.stack.add_named(self.empty_label, "empty")
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(self.listbox)
        scrolled.set_vexpand(True)
        self.stack.add_named(scrolled, "list")
        root.append(self.stack)

        click = Gtk.GestureClick.new()
        click.set_button(1)
        click.connect("pressed", self._on_list_pressed)
        self.listbox.add_controller(click)

        key = Gtk.EventControllerKey.new()
        key.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key)

        # Alt kontrol çubuğu
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        controls.set_margin_top(8)
        controls.set_margin_bottom(8)
        controls.set_margin_start(12)
        controls.set_margin_end(12)
        root.append(controls)

        self.now_label = Gtk.Label(label="Çalan parça yok", ellipsize=3)
        self.now_label.add_css_class("dim-label")
        controls.append(self.now_label)

        seek_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls.append(seek_row)
        self.lbl_pos = Gtk.Label(label="--:--")
        self.lbl_pos.add_css_class("dim-label")
        seek_row.append(self.lbl_pos)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1000, 1)
        self.scale.set_hexpand(True)
        self.scale.set_draw_value(False)
        self.scale.connect("change-value", self._on_seek)
        seek_row.append(self.scale)
        self.lbl_dur = Gtk.Label(label="--:--")
        self.lbl_dur.add_css_class("dim-label")
        seek_row.append(self.lbl_dur)

        bottom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        controls.append(bottom_row)

        self.btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.btn_row.set_halign(Gtk.Align.START)
        self.btn_row.set_valign(Gtk.Align.CENTER)
        bottom_row.append(self.btn_row)

        btn_prev = Gtk.Button(icon_name="media-skip-backward-symbolic", tooltip_text="Önceki")
        btn_prev.set_size_request(52, 64)
        btn_prev.connect("clicked", lambda *_: self.play_prev())
        self.btn_row.append(btn_prev)

        self.btn_play = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Oynat / Duraklat")
        self.btn_play.set_size_request(60, 64)
        self.btn_play.add_css_class("suggested-action")
        self.btn_play.connect("clicked", lambda *_: self.toggle_play())
        self.btn_row.append(self.btn_play)

        btn_next = Gtk.Button(icon_name="media-skip-forward-symbolic", tooltip_text="Sonraki")
        btn_next.set_size_request(52, 64)
        btn_next.connect("clicked", lambda *_: self.play_next(manual=True))
        self.btn_row.append(btn_next)

        # Ekolayzer: gerçek spektrum verisi + peak tutucu (yoksa dekoratif mod)
        self.eq_area = Gtk.DrawingArea()
        self.eq_area.set_hexpand(True)
        self.eq_area.set_content_height(64)
        self.eq_area.set_valign(Gtk.Align.CENTER)
        self.eq_area.add_css_class("card")
        self.eq_area.set_draw_func(self._draw_eq, None)
        bottom_row.append(self.eq_area)
        self._eq_levels = []
        self._eq_targets = []
        self._eq_peaks = []
        self._eq_hold = []
        self._eq_last_apply_t = None
        self._last_stream_t = None
        GLib.timeout_add(120, self._eq_tick)

    def _setup_dnd(self):
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)

    # ---- Playlist yönetimi ----
    def _collect_mp3s(self, folder):
        found = []
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if name.lower().endswith(".mp3"):
                    found.append(os.path.join(root, name))
        return sorted(found)

    def add_paths(self, gio_files):
        new_files = []
        for gf in gio_files:
            path = gf.get_path()
            if not path:
                continue
            if os.path.isdir(path):
                new_files.extend(self._collect_mp3s(path))
            elif path.lower().endswith(".mp3") and os.path.isfile(path):
                new_files.append(path)
        if not new_files:
            return
        existing = {t["path"] for t in self.playlist}
        added = 0
        for path in new_files:
            if path in existing:
                continue
            title, duration = track_info(path)
            self.playlist.append({"path": path, "title": title, "duration": duration})
            existing.add(path)
            added += 1
        self._refresh_list()
        self._save_playlist()
        if added and self.current == -1:
            self.play_index(0, autoplay=False)

    def _refresh_list(self):
        while (row := self.listbox.get_row_at_index(0)) is not None:
            self.listbox.remove(row)
        for i, track in enumerate(self.playlist):
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            box.set_margin_start(12)
            box.set_margin_end(12)
            num = Gtk.Label(label=str(i + 1))
            num.add_css_class("dim-label")
            num.set_size_request(30, -1)
            box.append(num)
            name = Gtk.Label(label=track["title"], xalign=0, ellipsize=3)
            name.set_hexpand(True)
            box.append(name)
            dur = Gtk.Label(label=fmt_time(track["duration"]))
            dur.add_css_class("dim-label")
            box.append(dur)
            row.set_child(box)
            self.listbox.append(row)
        self.stack.set_visible_child_name("list" if self.playlist else "empty")
        self._highlight_current()

    def _highlight_current(self):
        for i in range(len(self.playlist)):
            row = self.listbox.get_row_at_index(i)
            if row is None:
                continue
            if i == self.current:
                self.listbox.select_row(row)
            first = row.get_child()
            if first is not None:
                name_label = first.get_last_child().get_prev_sibling()
                if i == self.current:
                    name_label.add_css_class("accent")
                else:
                    name_label.remove_css_class("accent")

    def _save_playlist(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            PLAYLIST_FILE.write_text(
                json.dumps([t["path"] for t in self.playlist], ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _load_playlist(self):
        try:
            paths = json.loads(PLAYLIST_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        for path in paths:
            if isinstance(path, str) and path.lower().endswith(".mp3") and os.path.isfile(path):
                title, duration = track_info(path)
                self.playlist.append({"path": path, "title": title, "duration": duration})
        if self.playlist:
            self.current = 0
            self._load_current(play=False)

    # ---- Çalma ----
    def _load_current(self, play=True):
        if not (0 <= self.current < len(self.playlist)):
            return
        self._spec_gen += 1
        uri = Gst.filename_to_uri(self.playlist[self.current]["path"])
        self.player.set_state(Gst.State.NULL)
        self.player.set_property("uri", uri)
        self._duration_ns = 0
        if play:
            self.player.set_state(Gst.State.PLAYING)
            self.playing = True
        else:
            self.playing = False
            self.player.set_state(Gst.State.PAUSED)
        self._update_play_button()
        self._highlight_current()
        self.now_label.set_text(f"♪ {self.playlist[self.current]['title']}")

    def play_index(self, index, autoplay=True):
        if not self.playlist:
            return
        self.current = index % len(self.playlist)
        self._load_current(play=autoplay)

    def toggle_play(self):
        if not self.playlist:
            return
        if self.current == -1:
            self.play_index(0)
            return
        if self.playing:
            self.player.set_state(Gst.State.PAUSED)
            self.playing = False
        else:
            self.player.set_state(Gst.State.PLAYING)
            self.playing = True
        self._update_play_button()

    def play_next(self, manual=False):
        if not self.playlist:
            return
        if self.shuffle and len(self.playlist) > 1:
            choices = [i for i in range(len(self.playlist)) if i != self.current]
            nxt = random.choice(choices)
        else:
            nxt = (self.current + 1) % len(self.playlist)
        self.play_index(nxt, autoplay=True)

    def play_prev(self):
        if not self.playlist:
            return
        pos = self._position_sec()
        if pos is not None and pos > 3:
            self._seek_fraction(0.0)
            return
        self.play_index((self.current - 1) % len(self.playlist), autoplay=True)

    def _update_play_button(self):
        icon = "media-playback-pause-symbolic" if self.playing else "media-playback-start-symbolic"
        self.btn_play.set_icon_name(icon)

    def _on_eos(self, _bus, _msg):
        GLib.idle_add(self.play_next)
        return True

    def _on_error(self, _bus, msg):
        err, _dbg = msg.parse_error()
        print(f"Oynatma hatası: {err}", file=sys.stderr)
        GLib.idle_add(self.play_next)
        return True

    def _setup_spectrum_sink(self):
        """Ses zincirine spectrum öğesi ekler; olmazsa None (dekoratif moda düşülür)."""
        try:
            reg = Gst.Registry.get()
            if reg.find_feature("spectrum", Gst.ElementFactory) is None:
                return None
            if reg.find_feature("audioconvert", Gst.ElementFactory) is None:
                return None
            sink = Gst.parse_bin_from_description(
                "audioconvert ! spectrum name=eq_sp bands=2048 "
                "threshold=-57 interval=16666667 post-messages=true "
                "! audioconvert ! autoaudiosink",
                True,
            )
            if sink.get_by_name("eq_sp") is None:
                return None
            self.player.set_property("audio-sink", sink)
            return sink.get_by_name("eq_sp")
        except Exception as err:
            print(f"Gerçek spektrum kurulamadı, dekoratif animasyon kullanılacak: {err}")
            return None

    def _on_element(self, _bus, msg):
        if self._spectrum is None:
            return True
        st = msg.get_structure()
        if st is None or st.get_name() != "spectrum":
            return True
        try:
            mags = list(st.get_value("magnitude"))
        except Exception:
            return True
        if not mags:
            return True
        bars = log_rebin(mags)
        if st.has_field("stream-time"):
            try:
                self._last_stream_t = int(st.get_value("stream-time"))
            except (TypeError, ValueError):
                pass
        GLib.timeout_add(int(self._av_delay * 1000), self._apply_spec_frame,
                         (bars, self._spec_gen))
        return True

    def _apply_spec_frame(self, payload):
        """Gecikmiş spektrum karesini uygular; bayat/duraklatılmış kareyi düşürür."""
        bars, gen = payload
        if gen != self._spec_gen or not self.playing or self._spectrum is None:
            return False
        n = len(bars)
        if len(self._eq_levels) != n:
            self._eq_levels = [0.0] * n
            self._eq_peaks = [0.0] * n
            self._eq_hold = [0.0] * n
        now = time.monotonic()
        dt = min(0.1, max(0.0, now - (self._eq_last_apply_t or now)))
        self._eq_last_apply_t = now
        for i, db in enumerate(bars):
            lv = spec_level(db, i, n)
            self._eq_levels[i] = lv
            pk, hd = peak_step(self._eq_peaks[i], self._eq_hold[i], lv, now, dt)
            self._eq_peaks[i], self._eq_hold[i] = pk, hd
        self.eq_area.queue_draw()
        return False

    def _refresh_av_delay(self):
        """Analiz-işitme önceliğini konum farkından ölçüp yumuşatır."""
        if self._last_stream_t is None:
            return
        ok, pos = self.player.query_position(Gst.Format.TIME)
        if not ok:
            return
        sample = max(0.0, min(1.5, (self._last_stream_t - pos) / Gst.SECOND))
        self._av_delay += 0.3 * (sample - self._av_delay)

    # ---- Süre çubuğu / ses ----
    def _position_sec(self):
        ok, pos = self.player.query_position(Gst.Format.TIME)
        return pos / Gst.SECOND if ok else None

    def _seek_fraction(self, frac):
        ok, dur = self.player.query_duration(Gst.Format.TIME)
        if not ok or dur <= 0:
            return
        ns = int(dur * max(0.0, min(1.0, frac)))
        self.player.seek_simple(
            Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, ns
        )
        self._spec_gen += 1

    def _on_seek(self, _scale, _scroll, value):
        if self._updating_scale:
            return False
        self._seek_fraction(value / 1000.0)
        return False

    def _tick(self):
        ok_d, dur = self.player.query_duration(Gst.Format.TIME)
        ok_p, pos = self.player.query_position(Gst.Format.TIME)
        if ok_d and dur > 0:
            self._duration_ns = dur
            self.lbl_dur.set_text(fmt_time(dur / Gst.SECOND))
            if ok_p:
                self._updating_scale = True
                self.scale.set_value(pos / dur * 1000.0)
                self._updating_scale = False
                self.lbl_pos.set_text(fmt_time(pos / Gst.SECOND))
        else:
            track = self.playlist[self.current] if 0 <= self.current < len(self.playlist) else None
            if track and track["duration"]:
                self.lbl_dur.set_text(fmt_time(track["duration"]))
        self._tick_n += 1
        if self.playing and self._tick_n % 4 == 0:
            self._refresh_av_delay()
        return True

    # ---- Ekolayzer animasyonu ----
    def _eq_tick(self):
        if self._spectrum is None:
            self._eq_fake()
            return True
        # Gerçek veri spectrum mesajlarıyla gelir; duraklayınca çubukları söndür
        n = len(self._eq_levels)
        if len(self._eq_peaks) != n:
            self._eq_peaks = [0.0] * n
        if not self.playing and any(v > 0.003 for v in self._eq_levels + self._eq_peaks):
            self._eq_levels = [max(0.0, lv - 0.08) for lv in self._eq_levels]
            self._eq_peaks = [max(lv, pk - 0.08)
                              for lv, pk in zip(self._eq_levels, self._eq_peaks)]
            self.eq_area.queue_draw()
        return True

    def _eq_fake(self):
        """Gerçek spektrum kurulamazsa kullanılan dekoratif animasyon."""
        n = 28
        if len(self._eq_levels) != n:
            self._eq_levels = [0.0] * n
            self._eq_targets = [0.0] * n
            self._eq_peaks = [0.0] * n
            self._eq_hold = [0.0] * n
        changed = False
        for i in range(n):
            if self.playing and random.random() < 0.35:
                self._eq_targets[i] = random.random()
            elif not self.playing:
                self._eq_targets[i] = 0.0
            lv = self._eq_levels[i] + (self._eq_targets[i] - self._eq_levels[i]) * 0.45
            if abs(lv - self._eq_levels[i]) > 0.002:
                changed = True
            self._eq_levels[i] = lv
        self._eq_peaks = list(self._eq_levels)
        if changed or self.playing:
            self.eq_area.queue_draw()

    def _draw_eq(self, _area, cr, width, height, _data):
        n = len(self._eq_levels) or 1
        gap, bar_w = 6, 7
        total = n * (bar_w + gap) - gap
        x0 = max(8, (width - total) / 2)
        base = height - 8
        span = max(1, base - 16)
        if self.playing:
            bar_rgb = (0x1C / 255, 0x71 / 255, 0xD8 / 255)
            peak_rgb = (0x77 / 255, 0xAA / 255, 0xE8 / 255)
        else:
            bar_rgb = (0.6, 0.6, 0.6)
            peak_rgb = (0.8, 0.8, 0.8)
        cr.set_source_rgb(*bar_rgb)
        for i, lv in enumerate(self._eq_levels):
            h = 4 + lv * span
            cr.rectangle(x0 + i * (bar_w + gap), base - h, bar_w, h)
        cr.fill()
        peaks = self._eq_peaks if len(self._eq_peaks) == n else [0.0] * n
        cr.set_source_rgb(*peak_rgb)
        for i, pk in enumerate(peaks):
            y = base - pk * span
            cr.rectangle(x0 + i * (bar_w + gap), y - 1, bar_w, 2)
        cr.fill()

    # ---- Olaylar ----
    def _on_drop(self, _target, value, _x, _y):
        try:
            files = value.get_files()
        except Exception:
            return False
        if not files:
            return False
        self.add_paths(files)
        return True

    def _on_list_pressed(self, _gesture, n_press, x, y):
        if n_press != 2:
            return
        row = self.listbox.get_row_at_y(y)
        if row is not None:
            self.play_index(row.get_index(), autoplay=True)

    def _on_key_pressed(self, _ctl, keyval, _keycode, _state):
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            row = self.listbox.get_selected_row()
            if row is not None:
                self._remove_index(row.get_index())
                return True
        return False

    def _remove_index(self, index):
        if not (0 <= index < len(self.playlist)):
            return
        was_current = index == self.current
        del self.playlist[index]
        if not self.playlist:
            self.player.set_state(Gst.State.NULL)
            self.current = -1
            self.playing = False
            self.now_label.set_text("Çalan parça yok")
            self._update_play_button()
        elif was_current:
            self.player.set_state(Gst.State.NULL)
            self.current = min(index, len(self.playlist) - 1)
            self._load_current(play=True)
        elif index < self.current:
            self.current -= 1
        self._refresh_list()
        self._save_playlist()

    def _on_open_folder(self, _btn):
        dlg = Gtk.FileDialog.new()
        dlg.set_title("Müzik klasörü seç")
        dlg.select_folder(self, None, self._on_folder_done)

    def _on_folder_done(self, dlg, result):
        try:
            folder = dlg.select_folder_finish(result)
        except Exception:
            return
        if folder is not None:
            self.add_paths([folder])

    def _on_open_files(self, _btn):
        dlg = Gtk.FileDialog.new()
        dlg.set_title("MP3 dosyaları seç")
        f = Gtk.FileFilter()
        f.set_name("MP3 ses dosyaları")
        f.add_pattern("*.mp3")
        f.add_mime_type("audio/mpeg")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dlg.set_filters(filters)
        dlg.open_multiple(self, None, self._on_files_done)

    def _on_files_done(self, dlg, result):
        try:
            model = dlg.open_multiple_finish(result)
        except Exception:
            return
        if model is None:
            return
        self.add_paths([model.get_item(i) for i in range(model.get_n_items())])

    def _on_shuffle_toggled(self, btn):
        self.shuffle = btn.get_active()

    def _on_clear(self, _btn):
        self.player.set_state(Gst.State.NULL)
        self.playlist.clear()
        self.current = -1
        self.playing = False
        self.now_label.set_text("Çalan parça yok")
        self._update_play_button()
        self._refresh_list()
        self._save_playlist()


class Mp3PlayerApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = Mp3PlayerWindow(self)
        win.present()


def main():
    app = Mp3PlayerApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
