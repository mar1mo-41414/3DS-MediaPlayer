import json
import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
