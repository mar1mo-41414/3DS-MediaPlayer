"""preset / 出力名 / 出力先の決まり方 (引数 > meta.json > 既定) と、meta.json の preset / output の検証。"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import GOOD_META, cleanup_assets, make_template, requires_tools
from mkcia import video
from mkcia.errors import MkciaError
from mkcia.meta import MAX_OUTPUT_NAME_BYTES, parse_meta
from mkcia.pipeline import BuildOptions, build_cia, resolve_output, resolve_preset
from mkcia.proc import OUT_ROOT, find_tool


def tearDownModule():
    cleanup_assets()


def good(**kw):
    d = dict(GOOD_META)
    d.update(kw)
    return d


class MetaOutputNameTest(unittest.TestCase):
    def test_cia_suffix_is_added(self):
        for given, want in (("Movie", "Movie.cia"), ("Movie.cia", "Movie.cia"), ("Movie.CIA", "Movie.CIA"),
                            ("a.b.c", "a.b.c.cia"), ("My-Movie", "My-Movie.cia"), ("日本語の映画", "日本語の映画.cia"),
                            ("with space", "with space.cia"), ("movie.cia.cia", "movie.cia.cia"), ("x.cia ", "x.cia")):
            with self.subTest(given=given):
                self.assertEqual(parse_meta(good(output=given)).output, want)

    def test_absent_or_null_means_default(self):
        self.assertIsNone(parse_meta(good()).output)
        self.assertIsNone(parse_meta(good(output=None)).output)

    def test_directories_and_path_tricks_are_rejected(self):
        for bad in ("a/b.cia", "/abs.cia", "../x.cia", "..\\x.cia", "dir\\x", "..", ".", "./x.cia", "~/x.cia/"):
            if bad == "~/x.cia/":
                bad = "a/"
            with self.subTest(bad=bad), self.assertRaises(MkciaError):
                parse_meta(good(output=bad))

    def test_characters_not_allowed_on_fat(self):
        for ch in '<>:"|?*':
            with self.subTest(ch=ch), self.assertRaises(MkciaError) as cm:
                parse_meta(good(output=f"a{ch}b"))
            self.assertIn("output", str(cm.exception))

    def test_empty_and_degenerate_names(self):
        for bad in ("", " ", "   ", ".cia", ".CIA", "name.", "..."):
            with self.subTest(bad=bad), self.assertRaises(MkciaError):
                parse_meta(good(output=bad))

    def test_control_characters(self):
        for ch in ("\n", "\t", "\x00", "\x1b"):
            with self.subTest(ch=repr(ch)), self.assertRaises(MkciaError):
                parse_meta(good(output=f"a{ch}b"))

    def test_wrong_types(self):
        for bad in (5, 1.5, True, [], {}, ["a.cia"]):
            with self.subTest(bad=bad), self.assertRaises(MkciaError) as cm:
                parse_meta(good(output=bad))
            self.assertIn("output", str(cm.exception))

    def test_length_limit_is_in_bytes(self):
        parse_meta(good(output="a" * (MAX_OUTPUT_NAME_BYTES - 4)))
        with self.assertRaises(MkciaError):
            parse_meta(good(output="a" * (MAX_OUTPUT_NAME_BYTES - 3)))
        with self.assertRaises(MkciaError):  # 日本語は 1 文字 3 バイト
            parse_meta(good(output="あ" * 70))

    def test_lone_surrogate(self):
        with self.assertRaises(MkciaError):
            parse_meta(good(output="bad\ud800"))


class MetaPresetTest(unittest.TestCase):
    def test_default_is_none(self):
        self.assertIsNone(parse_meta(good()).preset)
        self.assertIsNone(parse_meta(good(preset=None)).preset)
        self.assertIsNone(parse_meta(good(preset="")).preset)

    def test_stored_as_given(self):
        self.assertEqual(parse_meta(good(preset=" light ")).preset, "light")

    def test_wrong_types(self):
        for bad in (1, 1.5, True, [], {}, ["light"]):
            with self.subTest(bad=bad), self.assertRaises(MkciaError) as cm:
                parse_meta(good(preset=bad))
            self.assertIn("preset", str(cm.exception))

    def test_preset_and_output_are_known_keys(self):
        self.assertEqual(parse_meta(good(preset="light", output="x")).warnings, [])


class ResolveFunctionsTest(unittest.TestCase):
    def meta(self, **kw):
        return parse_meta(good(**kw))

    def test_preset_priority(self):
        self.assertEqual(resolve_preset(BuildOptions(Path("t")), self.meta()), video.DEFAULT_PRESET)
        self.assertEqual(resolve_preset(BuildOptions(Path("t")), self.meta(preset="light")), "light")
        self.assertEqual(resolve_preset(BuildOptions(Path("t"), preset="high"), self.meta(preset="light")), "high")
        self.assertEqual(resolve_preset(BuildOptions(Path("t"), preset="high"), self.meta()), "high")

    def test_unknown_preset_in_meta_names_the_source_and_choices(self):
        with self.assertRaises(MkciaError) as cm:
            resolve_preset(BuildOptions(Path("t")), self.meta(preset="ultra"))
        m = str(cm.exception)
        self.assertIn("meta.json", m)
        self.assertIn("ultra", m)
        for name in video.PRESETS:
            self.assertIn(name, m)

    def test_unknown_preset_from_argument(self):
        with self.assertRaises(MkciaError):
            resolve_preset(BuildOptions(Path("t"), preset="ultra"), self.meta())

    def test_output_priority(self):
        root = Path("/tmp/some/Template_Name")
        self.assertEqual(resolve_output(BuildOptions(root), self.meta(), root), OUT_ROOT / "Template_Name.cia")
        self.assertEqual(resolve_output(BuildOptions(root), self.meta(output="Custom"), root), OUT_ROOT / "Custom.cia")
        self.assertEqual(resolve_output(BuildOptions(root, output_dir=Path("/d")), self.meta(output="Custom"), root),
                         Path("/d/Custom.cia"))
        self.assertEqual(resolve_output(BuildOptions(root, output_dir=Path("/d")), self.meta(), root),
                         Path("/d/Template_Name.cia"))
        self.assertEqual(resolve_output(BuildOptions(root, output=Path("/x/y.cia"), output_dir=Path("/d")),
                                        self.meta(output="Custom"), root), Path("/x/y.cia"))

    def test_default_name_with_odd_template_paths(self):
        for tpl, name in ((Path("/tmp/with space"), "with space.cia"), (Path("/tmp/日本語"), "日本語.cia"),
                          (Path("/tmp/a/../b"), "b.cia")):
            with self.subTest(tpl=str(tpl)):
                self.assertEqual(resolve_output(BuildOptions(tpl), self.meta(), tpl).name, name)

    def test_default_out_dir_is_inside_the_repository(self):
        self.assertEqual(OUT_ROOT.name, "out")
        self.assertTrue((OUT_ROOT.parent / "tool" / "mkcia").is_dir())


@requires_tools
class ResolutionE2ETest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)
        self.logs = []

    def tearDown(self):
        self._d.cleanup()

    def build(self, tpl, **kw):
        kw.setdefault("compress_code", False)
        return build_cia(BuildOptions(Path(tpl), **kw), log=self.logs.append)

    def work_dims(self, work):
        out = subprocess.run([find_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height", "-of", "csv=p=0", str(work / "video.mp4")],
                             capture_output=True, text=True).stdout.strip()
        return tuple(int(x) for x in out.split(","))

    def test_meta_preset_and_output_name_are_used(self):
        t = make_template(self.d / "tpl", {"preset": "light", "output": "My-Movie"})
        work = self.d / "work"
        out = self.build(t, output_dir=self.d / "out", keep_work=work)
        self.assertEqual(out, self.d / "out" / "My-Movie.cia")
        self.assertEqual(self.work_dims(work), (video.PRESETS["light"].width, video.PRESETS["light"].height))
        self.assertTrue(any("preset=light" in l for l in self.logs))

    def test_argument_beats_meta(self):
        t = make_template(self.d / "tpl", {"preset": "light", "output": "FromMeta"})
        work = self.d / "work"
        out = self.build(t, preset="medium", output=self.d / "explicit.cia", keep_work=work)
        self.assertEqual(out, self.d / "explicit.cia")
        self.assertEqual(self.work_dims(work), (video.PRESETS["medium"].width, video.PRESETS["medium"].height))
        self.assertFalse((self.d / "FromMeta.cia").exists())

    def test_defaults_name_after_template_directory(self):
        t = make_template(self.d / "Template_X")
        out = self.build(t, output_dir=self.d / "o", preset="light")
        self.assertEqual(out, self.d / "o" / "Template_X.cia")
        self.assertTrue(out.is_file())

    def test_default_preset_is_used_when_nothing_is_specified(self):
        t = make_template(self.d / "tpl")
        work = self.d / "work"
        self.build(t, output_dir=self.d / "o", keep_work=work)
        self.assertTrue(any(f"preset={video.DEFAULT_PRESET}" in l for l in self.logs))

    def test_bad_meta_preset_fails_before_encoding(self):
        t = make_template(self.d / "tpl", {"preset": "ultra"})
        with mock.patch("mkcia.video.encode_video", side_effect=AssertionError("エンコードに進んではいけない")):
            with self.assertRaises(MkciaError) as cm:
                self.build(t, output_dir=self.d / "o")
        self.assertIn("ultra", str(cm.exception))
        self.assertFalse((self.d / "o").exists())

    def test_bad_meta_output_fails_before_encoding(self):
        t = make_template(self.d / "tpl", {"output": "sub/dir.cia"})
        with mock.patch("mkcia.video.encode_video", side_effect=AssertionError("エンコードに進んではいけない")):
            with self.assertRaises(MkciaError):
                self.build(t, output_dir=self.d / "o")

    def test_output_dir_is_created_and_name_with_unicode(self):
        t = make_template(self.d / "tpl", {"output": "日本語 の 名前"})
        out = self.build(t, output_dir=self.d / "new" / "dir", preset="light")
        self.assertEqual(out.name, "日本語 の 名前.cia")
        self.assertTrue(out.is_file())

    def test_output_dir_that_is_a_file(self):
        (self.d / "afile").write_text("x")
        t = make_template(self.d / "tpl")
        with self.assertRaises(MkciaError):
            self.build(t, output_dir=self.d / "afile", preset="light")

    def test_meta_json_with_both_keys_round_trips_through_file(self):
        t = make_template(self.d / "tpl")
        meta = json.loads((t / "meta.json").read_text())
        meta.update(preset="light", output="Round Trip")
        (t / "meta.json").write_text(json.dumps(meta))
        out = self.build(t, output_dir=self.d / "o")
        self.assertEqual(out.name, "Round Trip.cia")


if __name__ == "__main__":
    unittest.main()
