import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mkcia import cia  # noqa: E402
from mkcia.errors import MkciaError  # noqa: E402
from mkcia.meta import load_meta, parse_meta  # noqa: E402

GOOD = {
    "title": "Video",
    "publisher": "me",
    "title_id": "000400000FF3A000",
    "version": "1.2.3",
}


class MetaTest(unittest.TestCase):
    def test_minimal_ok(self):
        m = parse_meta(GOOD)
        self.assertEqual(m.version, (1, 2, 3))
        self.assertEqual(m.unique_id, 0xFF3A0)
        self.assertEqual(m.long_title, "Video")
        self.assertFalse(m.loop)
        self.assertEqual(m.volume, 1.0)

    def test_missing_required(self):
        for key in ("title", "publisher", "title_id", "version"):
            bad = dict(GOOD)
            del bad[key]
            with self.assertRaises(MkciaError) as cm:
                parse_meta(bad)
            self.assertIn(key, str(cm.exception))

    def test_blank_required_is_missing(self):
        with self.assertRaises(MkciaError):
            parse_meta({**GOOD, "title": "   "})

    def test_title_id_validation(self):
        for bad in ("123", "000400000FF3A00", "0005000000FF3A00", "000400000FF3A001", "zzzzzzzzzzzzzzzz"):
            with self.assertRaises(MkciaError, msg=bad):
                parse_meta({**GOOD, "title_id": bad})

    def test_title_id_0x_prefix_and_lowercase(self):
        m = parse_meta({**GOOD, "title_id": "0x000400000ff3a000"})
        self.assertEqual(m.title_id, "000400000FF3A000")

    def test_version_validation(self):
        for bad in ("1", "1.0", "a.b.c", "64.0.0", "0.0.16"):
            with self.assertRaises(MkciaError, msg=bad):
                parse_meta({**GOOD, "version": bad})

    def test_volume_range(self):
        with self.assertRaises(MkciaError):
            parse_meta({**GOOD, "volume": 1.5})
        self.assertEqual(parse_meta({**GOOD, "volume": 0.25}).volume, 0.25)

    def test_load_meta_errors(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "meta.json"
            with self.assertRaises(MkciaError):
                load_meta(p)
            p.write_text("{not json")
            with self.assertRaises(MkciaError):
                load_meta(p)
            p.write_text(json.dumps(GOOD))
            self.assertEqual(load_meta(p).title, "Video")


class RsfTest(unittest.TestCase):
    def test_rsf_contains_ids(self):
        m = parse_meta({**GOOD, "title": 'A"B' * 5})
        with tempfile.TemporaryDirectory() as d:
            out = cia.write_rsf(m, Path(d) / "app.rsf")
            text = out.read_text()
        self.assertIn("UniqueId                : 0xFF3A0", text)
        self.assertIn('ProductCode             : "CTR-P-MPLY"', text)
        title_line = next(l for l in text.splitlines() if l.strip().startswith("Title"))
        self.assertEqual(title_line.count('"'), 2)  # タイトル中の " は除去される


class RsfRealDeviceTest(unittest.TestCase):
    """実機で起動するために必須の項目 (エミュレータは検査しないので、欠けると実機でだけ落ちる)。"""

    def setUp(self):
        with tempfile.TemporaryDirectory() as d:
            self.text = cia.write_rsf(parse_meta(GOOD), Path(d) / "app.rsf").read_text()

    def test_has_syscall_access(self):
        self.assertIn("SystemCallAccess:", self.text)
        # libctru / ndsp が使う代表的な SVC
        for name in ("CreateThread", "ControlMemory", "SendSyncRequest", "FlushProcessDataCache"):
            self.assertIn(f"{name}:", self.text)

    def test_has_vram_and_dsp_mappings(self):
        self.assertIn("1f000000-1f5fffff:r", self.text)  # VRAM (citro3d の描画先)
        self.assertIn("1ff00000-1ff7ffff", self.text)  # DSP

    def test_has_required_services(self):
        for svc in ("APT:U", "fs:USER", "gsp::Gpu", "hid:USER", "dsp::DSP", "y2r:u", "ptm:u", "cfg:u"):
            self.assertIn(f"- {svc}", self.text)

    def test_sd_access_and_logo(self):
        self.assertIn("- DirectSdmc\n", self.text)
        self.assertIn("- DirectSdmcWrite", self.text)
        self.assertIn("Logo                    : Nintendo", self.text)

    def test_compress_flag_in_rsf(self):
        with tempfile.TemporaryDirectory() as d:
            on = cia.write_rsf(parse_meta(GOOD), Path(d) / "a.rsf").read_text()
            off = cia.write_rsf(parse_meta(GOOD), Path(d) / "b.rsf", compress_code=False).read_text()
        self.assertIn("EnableCompress          : true", on)
        self.assertIn("EnableCompress          : false", off)

    def test_rsf_title_is_ascii_and_short(self):
        for title, want in (("Hello", "Hello"), ("日本語", "MPLAYER"), ("My 動画 Player", "My  Pla"), ("", "MPLAYER"),
                            ('a"b', "ab"), ("12345678901", "1234567"), ("  x  ", "x"), ("!!!", "MPLAYER"), ("é", "MPLAYER")):
            with self.subTest(title=title):
                self.assertEqual(cia.rsf_title(title), want)

    def test_makerom_not_given_desc_template(self):
        """-desc app:N はテンプレート側のサービス/SVC 制限で上書きされ、実機で起動しなくなった。"""
        calls = []
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for n in ("a.elf", "a.rsf", "r.bin", "i.smdh", "b.bnr"):
                (d / n).write_bytes(b"x")
            # 外部ツールが無い環境でも動くよう、ツールの探索も差し替える (実際には何も実行しない)
            with mock.patch.object(cia, "find_tool", lambda name: name), \
                 mock.patch.object(cia, "run", lambda cmd, log=None, cwd=None: calls.append([str(c) for c in cmd]) or ""):
                cia.build_cia(d / "a.elf", d / "a.rsf", d / "r.bin", d / "i.smdh", d / "b.bnr",
                              parse_meta(GOOD), d / "o.cia")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("-desc", calls[0])
        self.assertIn("-exefslogo", calls[0])


class PresetTest(unittest.TestCase):
    def test_presets_satisfy_rom_constraints(self):
        """ROM は幅・高さが 8 の倍数で 512x256 以下の動画だけを受け付ける。"""
        from mkcia.video import PRESETS

        self.assertIn("light", PRESETS)
        for name, p in PRESETS.items():
            self.assertEqual(p.width % 8, 0, name)
            self.assertEqual(p.height % 8, 0, name)
            self.assertLessEqual(p.width, 512, name)
            self.assertLessEqual(p.height, 256, name)
            self.assertLessEqual(p.width, 400, name)  # 上画面より大きくする意味が無い
            self.assertGreater(p.fps, 0, name)


if __name__ == "__main__":
    unittest.main()
