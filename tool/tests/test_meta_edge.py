"""meta.json に「いろんなもの」が来たときの検証。どれも traceback にならず MkciaError になること。"""

import json
import math
import tempfile
import unittest
from pathlib import Path

from helpers import GOOD_META  # noqa: F401  (sys.path 設定も兼ねる)
from mkcia.errors import MkciaError
from mkcia.meta import MAX_LONG_TITLE, MAX_PUBLISHER, MAX_TITLE, load_meta, parse_meta


def good(**kw):
    d = dict(GOOD_META)
    d.update(kw)
    return d


class TopLevelTest(unittest.TestCase):
    def test_not_an_object(self):
        for v in ([], [1, 2], "text", 123, 1.5, True, None):
            with self.subTest(v=v), self.assertRaises(MkciaError) as cm:
                parse_meta(v)
            self.assertIn("オブジェクト", str(cm.exception))

    def test_empty_object_lists_all_missing(self):
        with self.assertRaises(MkciaError) as cm:
            parse_meta({})
        for k in ("title", "title_id", "version", "publisher"):
            self.assertIn(k, str(cm.exception))


class RequiredTypesTest(unittest.TestCase):
    def test_wrong_types_for_each_required_key(self):
        bad_values = [123, 1.5, True, [], {}, ["a"], {"a": 1}]
        for key in ("title", "publisher", "title_id", "version"):
            for v in bad_values:
                with self.subTest(key=key, v=v), self.assertRaises(MkciaError) as cm:
                    parse_meta(good(**{key: v}))
                self.assertIn(key, str(cm.exception))

    def test_null_is_missing_for_required(self):
        for key in ("title", "publisher", "title_id", "version"):
            with self.subTest(key=key), self.assertRaises(MkciaError) as cm:
                parse_meta(good(**{key: None}))
            self.assertIn(key, str(cm.exception))

    def test_blank_strings_are_missing(self):
        for key in ("title", "publisher"):
            for v in ("", " ", "　", "   \t "):
                with self.subTest(key=key, v=v), self.assertRaises(MkciaError):
                    parse_meta(good(**{key: v}))


class TextContentTest(unittest.TestCase):
    def test_control_characters_rejected(self):
        for key in ("title", "publisher", "long_title"):
            for ch in ("\n", "\r", "\t", "\x00", "\x1b", "\x7f"):
                with self.subTest(key=key, ch=repr(ch)), self.assertRaises(MkciaError) as cm:
                    parse_meta(good(**{key: f"a{ch}b"}))
                self.assertIn(key, str(cm.exception))

    def test_length_limits_are_in_utf16_units(self):
        parse_meta(good(title="A" * MAX_TITLE))
        with self.assertRaises(MkciaError):
            parse_meta(good(title="A" * (MAX_TITLE + 1)))
        parse_meta(good(publisher="あ" * MAX_PUBLISHER))
        with self.assertRaises(MkciaError):
            parse_meta(good(publisher="あ" * (MAX_PUBLISHER + 1)))
        parse_meta(good(long_title="B" * MAX_LONG_TITLE))
        with self.assertRaises(MkciaError):
            parse_meta(good(long_title="B" * (MAX_LONG_TITLE + 1)))
        # サロゲートペア (絵文字) は UTF-16 で 2 単位
        parse_meta(good(title="😀" * (MAX_TITLE // 2)))
        with self.assertRaises(MkciaError):
            parse_meta(good(title="😀" * (MAX_TITLE // 2 + 1)))

    def test_unicode_titles_ok(self):
        for t in ("日本語タイトル", "Ünïcödé", "한국어", "العربية", "emoji 🎬", "ｱｲｳ", "a b  c"):
            with self.subTest(t=t):
                self.assertEqual(parse_meta(good(title=t)).title, t)

    def test_lone_surrogate_rejected(self):
        with self.assertRaises(MkciaError):
            parse_meta(good(title="bad\ud800"))

    def test_whitespace_is_stripped(self):
        m = parse_meta(good(title="  Title  ", publisher="\tme "))
        self.assertEqual((m.title, m.publisher), ("Title", "me"))

    def test_long_title_defaults_to_title(self):
        for v in (None, "", "  "):
            self.assertEqual(parse_meta(good(title="T", long_title=v)).long_title, "T")


class TitleIdTest(unittest.TestCase):
    def test_invalid_ids(self):
        cases = ["", "0", "123", "0004000000FF3A0", "0004000000FF3A000", "000400000FF3A00G", "0005000000FF3A00",
                 "000400000FF3A001", "0x", "0x0004", "000400000FF3A0 0", "000400000-F3A000", "ゼロ"]
        for v in cases:
            with self.subTest(v=v), self.assertRaises(MkciaError):
                parse_meta(good(title_id=v))

    def test_valid_forms(self):
        for v in ("000400000FF3A000", "000400000ff3a000", "0x000400000FF3A000", "0X000400000ff3a000", "  000400000FF3A000 "):
            with self.subTest(v=v):
                self.assertEqual(parse_meta(good(title_id=v)).title_id, "000400000FF3A000")

    def test_unique_id_range(self):
        self.assertEqual(parse_meta(good(title_id="0004000000000000")).unique_id, 0)
        self.assertEqual(parse_meta(good(title_id="000400000FFFFF00")).unique_id, 0xFFFFF)  # makerom の上限

    def test_unique_id_above_makerom_limit_is_rejected_with_a_suggestion(self):
        """ユニークID は 20bit まで (実測: 0x100000 以上は makerom が "Unique ID is out of range")。"""
        for v in ("0004000010000000", "0004000011451400", "00040000FFFFFF00", "00040000FFFFF100"):
            with self.subTest(v=v), self.assertRaises(MkciaError) as cm:
                parse_meta(good(title_id=v))
            m = str(cm.exception)
            self.assertIn("範囲外", m)
            self.assertIn("000400000FFFFF00", m)
            near = m.split("例: ")[1].split(":")[0]
            self.assertEqual(parse_meta(good(title_id=near)).title_id, near)  # 提案は有効

    def test_boundary_just_below_and_above(self):
        parse_meta(good(title_id="000400000FFFFF00"))
        with self.assertRaises(MkciaError):
            parse_meta(good(title_id="0004000010000000"))


class VersionTest(unittest.TestCase):
    def test_invalid(self):
        for v in ("", "1", "1.0", "1.0.0.0", "a.b.c", "1.0.x", "-1.0.0", "1..0", "1.0.0 ", "v1.0.0", "1,0,0",
                  "64.0.0", "0.64.0", "0.0.16", "1.0.0-beta", "١.٠.٠"):
            if v == "1.0.0 ":
                continue  # 前後の空白は strip される
            with self.subTest(v=v), self.assertRaises(MkciaError):
                parse_meta(good(version=v))

    def test_boundaries_ok(self):
        self.assertEqual(parse_meta(good(version="0.0.0")).version, (0, 0, 0))
        self.assertEqual(parse_meta(good(version="63.63.15")).version, (63, 63, 15))
        self.assertEqual(parse_meta(good(version=" 1.2.3 ")).version, (1, 2, 3))


class OptionalTest(unittest.TestCase):
    def test_loop_must_be_bool(self):
        for v in ("true", "yes", "1", 1, 0, 1.0, [], {}, "false"):
            with self.subTest(v=v), self.assertRaises(MkciaError) as cm:
                parse_meta(good(loop=v))
            self.assertIn("loop", str(cm.exception))
        self.assertTrue(parse_meta(good(loop=True)).loop)
        self.assertFalse(parse_meta(good(loop=False)).loop)
        self.assertFalse(parse_meta(good(loop=None)).loop)

    def test_volume_invalid(self):
        for v in ("loud", "0.5", True, False, [], {}, -0.01, 1.01, 2, 100, -1, float("nan"), float("inf"), -float("inf")):
            with self.subTest(v=v), self.assertRaises(MkciaError) as cm:
                parse_meta(good(volume=v))
            self.assertIn("volume", str(cm.exception))

    def test_volume_valid(self):
        for v, want in ((0, 0.0), (1, 1.0), (0.0, 0.0), (1.0, 1.0), (0.5, 0.5), (1e-9, 1e-9)):
            with self.subTest(v=v):
                self.assertEqual(parse_meta(good(volume=v)).volume, want)
        self.assertEqual(parse_meta(good(volume=None)).volume, 1.0)

    def test_product_code(self):
        for v in ("CTR-P-MPL", "ctr-p-mply", "CTR-P-MPLYX", "CTR-PP-MPLY", "CTRPMPLY", 5, True, ["CTR-P-MPLY"]):
            with self.subTest(v=v), self.assertRaises(MkciaError):
                parse_meta(good(product_code=v))
        self.assertEqual(parse_meta(good(product_code="CTR-N-AB12")).product_code, "CTR-N-AB12")
        self.assertEqual(parse_meta(good(product_code=None)).product_code, "CTR-P-MPLY")

    def test_unknown_keys_are_warnings_not_errors(self):
        m = parse_meta(good(color="red", extra={"a": 1}))
        self.assertEqual(len(m.warnings), 2)
        self.assertTrue(any("color" in w for w in m.warnings))
        self.assertEqual(parse_meta(good()).warnings, [])


class LoadMetaTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.p = Path(self._d.name) / "meta.json"

    def tearDown(self):
        self._d.cleanup()

    def test_missing_file(self):
        with self.assertRaises(MkciaError) as cm:
            load_meta(self.p)
        self.assertIn("見つかりません", str(cm.exception))

    def test_directory_instead_of_file(self):
        self.p.mkdir()
        with self.assertRaises(MkciaError):
            load_meta(self.p)

    def test_bad_json_variants(self):
        bad = ["", "   ", "{", "{'a': 1}", '{"a": }', '{"a": 1,}', "[1,", "nul", '{"title": "x"} trailing',
               "// comment\n{}", '{"a": 1}{"b": 2}', "\x00\x01\x02", '{"a": "unterminated}']
        for text in bad:
            with self.subTest(text=text):
                self.p.write_text(text)
                with self.assertRaises(MkciaError) as cm:
                    load_meta(self.p)
                self.assertIn("meta.json", str(cm.exception))

    def test_not_utf8(self):
        self.p.write_bytes('{"title": "日本"}'.encode("shift_jis"))
        with self.assertRaises(MkciaError) as cm:
            load_meta(self.p)
        self.assertIn("UTF-8", str(cm.exception))

    def test_utf8_bom_is_accepted(self):
        self.p.write_bytes(b"\xef\xbb\xbf" + json.dumps(GOOD_META).encode())
        self.assertEqual(load_meta(self.p).title, "TestApp")

    def test_huge_file_rejected(self):
        self.p.write_text('{"title": "' + "a" * 1_100_000 + '"}')
        with self.assertRaises(MkciaError) as cm:
            load_meta(self.p)
        self.assertIn("大きすぎ", str(cm.exception))

    def test_deeply_nested_does_not_crash(self):
        self.p.write_text("[" * 100000 + "]" * 100000)
        with self.assertRaises(MkciaError):
            load_meta(self.p)

    def test_special_float_constants(self):
        self.p.write_text('{"title":"t","publisher":"p","title_id":"000400000FF3A000","version":"1.0.0","volume":NaN}')
        with self.assertRaises(MkciaError):
            load_meta(self.p)

    def test_duplicate_keys_last_wins(self):
        self.p.write_text('{"title":"a","title":"b","publisher":"p","title_id":"000400000FF3A000","version":"1.0.0"}')
        self.assertEqual(load_meta(self.p).title, "b")

    def test_error_messages_are_japanese_and_name_the_key(self):
        self.p.write_text(json.dumps(good(volume="x")))
        with self.assertRaises(MkciaError) as cm:
            load_meta(self.p)
        self.assertIn("volume", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
