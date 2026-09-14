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
                # Gerçek mod: kare gecikmeli uygulanır (dB -> 0..1)
                mags = [-60.0, -30.0, -6.0] + [-60.0] * 25
                bars = M.log_rebin(mags)
                win.playing = True
                self.assertFalse(win._apply_spec_frame((bars, win._spec_gen)))
                exp0 = M.spec_level(-60.0, 0, 28)
                exp1 = M.spec_level(-30.0, 1, 28)
                exp2 = M.spec_level(-6.0, 2, 28)
                self.assertEqual(len(win._eq_levels), 28)
                self.assertAlmostEqual(win._eq_levels[0], exp0)
                self.assertAlmostEqual(win._eq_levels[1], exp1)
                self.assertAlmostEqual(win._eq_levels[2], exp2)
                self.assertAlmostEqual(win._eq_peaks[1], exp1)
                self.assertGreater(win._eq_hold[1], 0.0)
        finally:
            win.close()

    def test_spec_gecikme_uygulama(self):
        """Bayat nesil ve duraklatılmış kare düşürülür."""
        app = M.Mp3PlayerApp()
        win = M.Mp3PlayerWindow(app)
        try:
            if win._spectrum is None:
                self.skipTest("spectrum kurulu değil")
            bars = M.log_rebin([-30.0] * 256)
            win.playing = True
            win._apply_spec_frame((bars, win._spec_gen))
            before = list(win._eq_levels)
            self.assertGreater(max(before), 0.0)
            win._apply_spec_frame((bars, win._spec_gen + 999))
            self.assertEqual(win._eq_levels, before)
            win.playing = False
            win._eq_levels = [0.0] * 28
            win._apply_spec_frame((bars, win._spec_gen))
            self.assertEqual(win._eq_levels, [0.0] * 28)
        finally:
            win.close()


class TestSpecMapping(unittest.TestCase):
    def test_zemin_sessiz(self):
        self.assertEqual(M.spec_level(-60.0, 0, 28), 0.0)
        self.assertEqual(M.spec_level(-100.0, 27, 28), 0.0)
        self.assertEqual(M.spec_level(None, 5, 28), 0.0)

    def test_tavan_kirpilir(self):
        self.assertEqual(M.spec_level(0.0, 0, 28), 1.0)
        self.assertEqual(M.spec_level(0.0, 27, 28), 1.0)

    def test_tiz_telafisi(self):
        low = M.spec_level(-36.0, 0, 28)
        high = M.spec_level(-36.0, 27, 28)
        self.assertGreater(high, low)
        self.assertTrue(0.30 < low < 0.36, low)
        self.assertTrue(0.70 < high < 0.75, high)

    def test_db_arttikca_seviye_artar(self):
        vals = [M.spec_level(db, 10, 28) for db in (-47, -36, -24, -12, 0)]
        self.assertEqual(vals, sorted(vals))
        self.assertGreater(vals[-1], vals[0])


class TestPeakStep(unittest.TestCase):
    def test_yukselince_tutar(self):
        self.assertEqual(M.peak_step(0.2, 0.0, 0.7, 100.0, 0.016), (0.7, 100.5))

    def test_tutma_suresince_dusmez(self):
        self.assertEqual(M.peak_step(0.7, 100.5, 0.3, 100.4, 0.016), (0.7, 100.5))

    def test_sonra_yavasca_duser(self):
        peak, hold = M.peak_step(0.7, 100.5, 0.3, 101.0, 0.25)
        self.assertAlmostEqual(peak, 0.5)
        self.assertEqual(hold, 100.5)

    def test_cubuga_degince_durur(self):
        self.assertEqual(M.peak_step(0.35, 90.0, 0.3, 100.0, 1.0), (0.3, 90.0))


class TestLogRebin(unittest.TestCase):
    def test_uzunluk(self):
        self.assertEqual(len(M.log_rebin([-60.0] * 256)), 28)

    def test_kisa_girdi_doldurulur(self):
        self.assertEqual(len(M.log_rebin([-30.0] * 10)), 28)

    def test_tiz_ton_sag_yarida(self):
        mags = [-60.0] * 256
        mags[74] = -6.0  # ~6400 Hz
        bars = M.log_rebin(mags)
        self.assertAlmostEqual(max(bars), -6.0)
        loud = [i for i, v in enumerate(bars) if v > -20.0]
        self.assertTrue(loud and min(loud) > 10, loud)

    def test_pes_ton_sol_yarida(self):
        mags = [-60.0] * 256
        mags[3] = -6.0  # ~220 Hz
        bars = M.log_rebin(mags)
        loud = [i for i, v in enumerate(bars) if v > -20.0]
        self.assertTrue(loud and max(loud) < 14, loud)

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
