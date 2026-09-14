#!/usr/bin/env python3
"""Sade modern MP3 çalar — Debian 13 + GNOME (GTK4 + Libadwaita + GStreamer).

Özellikler:
- Klasörü pencereye sürükle-bırak -> içindeki mp3'ler playliste eklenir
- Tekli mp3 dosyaları da sürükle-bırak ile eklenebilir
- Çift tıklama ile çalma, sıra ile otomatik devam, karışık çalma modu
- Önceki / Oynat-Duraklat / Sonraki, süre çubuğu (seek)
- Playlist oturumlar arası saklanır (~/.config/mp3-player/playlist.json)
"""
import json
import os
import random
import sys
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


def track_info(path):
    """MP3 dosyasından başlık ve süre bilgisini okur."""
    title = Path(path).stem
    duration = None
    if HAS_MUTAGEN:
        try:
            audio = MP3(path)
            if audio.info is not None:
                duration = audio.info.length
            tags = audio.tags
            if tags is not None:
                for key in ("TIT2", "TIT"):
                    if key in tags:
                        title = str(tags[key].text[0])
                        break
        except Exception:
            pass
    return title, duration


class Mp3PlayerWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("MP3 Çalar")
        self.set_default_size(720, 540)

        Gst.init(None)
        factory = Gst.ElementFactory.find("playbin3")
        self.player = Gst.ElementFactory.make("playbin3" if factory else "playbin", "player")
        self.player.set_property("volume", 1.0)
        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", self._on_eos)
        bus.connect("message::error", self._on_error)

        self.playlist = []  # {"path": str, "title": str, "duration": float|None}
        self.current = -1
        self.playing = False
        self.shuffle = False
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

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_row.set_halign(Gtk.Align.CENTER)
        controls.append(btn_row)

        btn_prev = Gtk.Button(icon_name="media-skip-backward-symbolic", tooltip_text="Önceki")
        btn_prev.connect("clicked", lambda *_: self.play_prev())
        btn_row.append(btn_prev)

        self.btn_play = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Oynat / Duraklat")
        self.btn_play.add_css_class("suggested-action")
        self.btn_play.connect("clicked", lambda *_: self.toggle_play())
        btn_row.append(self.btn_play)

        btn_next = Gtk.Button(icon_name="media-skip-forward-symbolic", tooltip_text="Sonraki")
        btn_next.connect("clicked", lambda *_: self.play_next(manual=True))
        btn_row.append(btn_next)

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
        return True

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
