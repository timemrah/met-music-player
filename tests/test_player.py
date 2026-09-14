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
            if win._spectrum is None:
                # Dekoratif mod: tick seviyeleri üretir
                win.playing = True
                self.assertTrue(win._eq_tick())
                self.assertEqual(len(win._eq_levels), 28)
            else:
                # Gerçek mod: seviyeler spectrum mesajıyla gelir (dB -> 0..1)
                class FakeStruct:
                    def get_name(self):
                        return "spectrum"

                    def get_value(self, key):
                        assert key == "magnitude"
                        return [-60.0, -30.0, -6.0] + [-60.0] * 25

                class FakeMsg:
                    def get_structure(self):
                        return FakeStruct()

                win._on_element(None, FakeMsg())
                self.assertEqual(len(win._eq_levels), 28)
                self.assertAlmostEqual(win._eq_levels[0], 0.0)
                self.assertAlmostEqual(win._eq_levels[1], 0.5)
                self.assertAlmostEqual(win._eq_levels[2], 0.9)
        finally:
            win.close()

    def test_gercek_spektrum_bagli(self):
        """Ses zincirinde gerçek veri için spectrum öğesi kurulu olmalı."""
        from gi.repository import Gst
        Gst.init(None)
        if Gst.Registry.get().find_feature("spectrum", Gst.ElementFactory) is None:
            self.skipTest("spectrum öğesi yok")
        app = M.Mp3PlayerApp()
        win = M.Mp3PlayerWindow(app)
        try:
            self.assertIsNotNone(win._spectrum)
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
