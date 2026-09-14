"""MP3 Çalar odak testleri: python3 -m unittest discover -s tests -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as M


class TestFormat(unittest.TestCase):
    def test_fmt_time(self):
        self.assertEqual(M.fmt_time(0), "0:00")
        self.assertEqual(M.fmt_time(65), "1:05")
        self.assertEqual(M.fmt_time(3661), "1:01:01")
        self.assertEqual(M.fmt_time(None), "--:--")


class TestLogo(unittest.TestCase):
    def test_logo_svg_gecerli(self):
        import xml.etree.ElementTree as ET
        path = os.path.join(os.path.dirname(__file__), "..", "logo.svg")
        self.assertTrue(os.path.isfile(path), "logo.svg yok")
        root = ET.parse(path).getroot()
        self.assertTrue(root.tag.endswith("svg"), root.tag)


@unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
                     "ekran yok, arayüz testi atlanıyor")
class TestNoVolumeBar(unittest.TestCase):
    def test_ses_cubugu_yok(self):
        """Pencerede seek çubuğu dışında Gtk.Scale (ses çubuğu) bulunmamalı."""
        app = M.Mp3PlayerApp()
        win = M.Mp3PlayerWindow(app)
        try:
            scales = []

            def walk(w):
                if isinstance(w, M.Gtk.Scale):
                    scales.append(w)
                child = w.get_first_child() if hasattr(w, "get_first_child") else None
                while child is not None:
                    walk(child)
                    child = child.get_next_sibling()

            walk(win)
            self.assertEqual(len(scales), 1, f"beklenen 1 scale, bulunan: {len(scales)}")
            self.assertIs(scales[0], win.scale)
        finally:
            win.close()

    def test_eq_duzeni(self):
        """Butonlar solda, sağda ekolayzer alanı olmalı."""
        app = M.Mp3PlayerApp()
        win = M.Mp3PlayerWindow(app)
        try:
            self.assertIsInstance(win.eq_area, M.Gtk.DrawingArea)
            self.assertEqual(win.btn_row.get_halign(), M.Gtk.Align.START)
            self.assertTrue(win._eq_tick())
            win.playing = True
            self.assertTrue(win._eq_tick())
            self.assertEqual(len(win._eq_levels), 28)
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
