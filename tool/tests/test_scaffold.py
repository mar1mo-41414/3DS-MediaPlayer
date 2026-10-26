"""雛形生成 (`mkcia --new NAME`) のテスト。"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import cleanup_assets, make_template, requires_tools
from mkcia import cli, scaffold
from mkcia.errors import MkciaError
from mkcia.meta import load_meta
from mkcia.pipeline import BuildOptions, build_cia


def tearDownModule():
    cleanup_assets()


def fake_example(root: Path, **meta) -> Path:
    """ffmpeg を使わない軽量な雛形 (中身はダミー。コピーと meta の書き換えだけを試す)。"""
    d = root / "example"
    d.mkdir(parents=True)
    for n in ("video.mp4", "icon.png", "bottom.png", "select_sound.wav"):
        (d / n).write_bytes(b"dummy " + n.encode())
    m = {"title": "TestVideo", "long_title": "Test Video Player", "publisher": "mediaplayer",
         "title_id": "000400000FF3A000", "version": "1.0.0", "loop": False, "volume": 0.8,
         "preset": "medium", "output": "Example"}
    m.update(meta)
    (d / "meta.json").write_text(json.dumps(m))
    return d


class CreateFromExampleTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.root = Path(self._d.name) / "template"
        self.root.mkdir()
        fake_example(self.root)

    def tearDown(self):
        self._d.cleanup()

    def test_copies_everything_and_updates_the_meta(self):
        t = scaffold.create_from_example("MyMovie", self.root)
        self.assertEqual(t, self.root / "MyMovie")
        self.assertEqual(sorted(p.name for p in t.iterdir()),
                         ["bottom.png", "icon.png", "meta.json", "select_sound.wav", "video.mp4"])
        self.assertEqual((t / "video.mp4").read_bytes(), b"dummy video.mp4")
        m = load_meta(t / "meta.json")
        self.assertEqual(m.title, "MyMovie")
        self.assertEqual(m.long_title, "MyMovie")  # long_title は消えて title が使われる
        self.assertIsNone(m.output)  # 雛形の出力名は引き継がない
        self.assertEqual((m.preset, m.loop, m.volume, m.publisher), ("medium", False, 0.8, "mediaplayer"))

    def test_example_is_left_untouched(self):
        before = (self.root / "example" / "meta.json").read_text()
        scaffold.create_from_example("A", self.root)
        self.assertEqual((self.root / "example" / "meta.json").read_text(), before)

    def test_title_id_is_valid_and_differs_from_the_example(self):
        t = scaffold.create_from_example("MyMovie", self.root)
        m = load_meta(t / "meta.json")
        self.assertNotEqual(m.title_id, "000400000FF3A000")
        self.assertRegex(m.title_id, r"^000400000[0-9A-F]{5}00$")

    def test_title_ids_never_collide_across_many_templates(self):
        ids = {"000400000FF3A000"}
        for i in range(40):
            t = scaffold.create_from_example(f"movie{i}", self.root)
            tid = load_meta(t / "meta.json").title_id
            self.assertNotIn(tid, ids, f"movie{i}")
            ids.add(tid)

    def test_same_name_is_refused_the_second_time(self):
        scaffold.create_from_example("dup", self.root)
        with self.assertRaises(MkciaError) as cm:
            scaffold.create_from_example("dup", self.root)
        self.assertIn("既に", str(cm.exception))

    def test_invalid_names(self):
        for bad in ("", "  ", ".", "..", ".hidden", "a/b", "a\\b", "a:b", "a*b", 'a"b', "a\nb", "あ" * 50, "example/../x"):
            with self.subTest(bad=bad), self.assertRaises(MkciaError):
                scaffold.create_from_example(bad, self.root)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["example"])  # 何も作られていない

    def test_name_equal_to_example_is_refused(self):
        with self.assertRaises(MkciaError):
            scaffold.create_from_example("example", self.root)

    def test_unicode_and_spaces(self):
        t = scaffold.create_from_example("日本語 の 映画", self.root)
        self.assertEqual(load_meta(t / "meta.json").title, "日本語 の 映画")

    def test_missing_example(self):
        shutil.rmtree(self.root / "example")
        with self.assertRaises(MkciaError) as cm:
            scaffold.create_from_example("x", self.root)
        self.assertIn("雛形", str(cm.exception))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_example_without_meta_or_with_a_broken_meta(self):
        (self.root / "example" / "meta.json").unlink()
        with self.assertRaises(MkciaError):
            scaffold.create_from_example("x", self.root)
        (self.root / "example" / "meta.json").write_text("{broken")
        with self.assertRaises(MkciaError):
            scaffold.create_from_example("x", self.root)
        (self.root / "example" / "meta.json").write_text("[1, 2]")
        with self.assertRaises(MkciaError):
            scaffold.create_from_example("x", self.root)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["example"])

    def test_example_with_an_invalid_meta_is_caught_before_creating(self):
        shutil.rmtree(self.root / "example")
        fake_example(self.root, publisher="")
        with self.assertRaises(MkciaError):
            scaffold.create_from_example("x", self.root)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["example"])

    def test_nothing_is_left_behind_when_copying_fails(self):
        with mock.patch.object(scaffold.shutil, "copytree", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(MkciaError):
                scaffold.create_from_example("x", self.root)
        self.assertEqual([p.name for p in self.root.iterdir()], ["example"])  # 一時ディレクトリも残さない

    def test_symlinks_in_the_example_are_copied_as_content(self):
        real = self.root.parent / "outside.png"
        real.write_bytes(b"outside")
        (self.root / "example" / "icon.png").unlink()
        (self.root / "example" / "icon.png").symlink_to(real)
        t = scaffold.create_from_example("x", self.root)
        self.assertFalse((t / "icon.png").is_symlink())
        self.assertEqual((t / "icon.png").read_bytes(), b"outside")

    def test_permissions_are_inherited_from_the_example_not_from_the_temp_dir(self):
        """コピー先は雛形と同じ権限になる (内部で使う一時ディレクトリの 0700 を引き継がない)。"""
        t = scaffold.create_from_example("perm", self.root)
        ex = self.root / "example"
        self.assertEqual(t.stat().st_mode & 0o777, ex.stat().st_mode & 0o777)
        for f in ("meta.json", "video.mp4"):
            self.assertEqual((t / f).stat().st_mode & 0o777, (ex / f).stat().st_mode & 0o777, f)
        self.assertNotEqual(t.stat().st_mode & 0o777, 0o700 if ex.stat().st_mode & 0o777 != 0o700 else 0)

    def test_unknown_meta_keys_survive(self):
        shutil.rmtree(self.root / "example")
        fake_example(self.root, custom_note="keep")
        t = scaffold.create_from_example("x", self.root)
        self.assertEqual(json.loads((t / "meta.json").read_text())["custom_note"], "keep")


class NewOptionTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.root = Path(self._d.name) / "template"
        self.root.mkdir()
        fake_example(self.root)
        p = mock.patch.object(cli, "TEMPLATE_ROOT", self.root)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self._d.cleanup()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = cli.main(list(argv))
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue(), err.getvalue()

    def test_new_creates_and_explains_the_next_step(self):
        rc, out, err = self.run_cli("--new", "MyMovie")
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue((self.root / "MyMovie" / "meta.json").is_file())
        self.assertIn("作成しました", out)
        self.assertIn("scripts/mkcia.sh MyMovie", out)

    def test_new_with_an_invalid_or_existing_name_is_a_user_error(self):
        self.assertEqual(self.run_cli("--new", "a/b")[0], cli.EXIT_USER_ERROR)
        self.assertEqual(self.run_cli("--new", "ok")[0], 0)
        rc, _, err = self.run_cli("--new", "ok")
        self.assertEqual(rc, cli.EXIT_USER_ERROR)
        self.assertIn("既に", err)

    def test_new_together_with_a_template_is_rejected(self):
        rc, _, err = self.run_cli("--new", "x", "example")
        self.assertEqual(rc, 2)  # argparse のエラー
        self.assertIn("同時", err)
        self.assertFalse((self.root / "x").exists())

    def test_new_without_a_name_is_an_argparse_error(self):
        rc, _, _ = self.run_cli("--new")
        self.assertEqual(rc, 2)

    def test_new_shows_up_in_list(self):
        self.run_cli("--new", "MyMovie")
        rc, out, _ = self.run_cli("--list")
        self.assertEqual(out.split(), ["MyMovie", "example"])

    def test_missing_example_is_reported(self):
        shutil.rmtree(self.root / "example")
        rc, _, err = self.run_cli("--new", "x")
        self.assertEqual(rc, cli.EXIT_USER_ERROR)
        self.assertIn("雛形", err)

    def test_help_mentions_new(self):
        rc, out, _ = self.run_cli("--help")
        self.assertIn("--new", out)


@requires_tools
class ScaffoldedTemplateBuildsTest(unittest.TestCase):
    def test_a_fresh_template_builds_a_cia_immediately(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "template"
            root.mkdir()
            make_template(root / "example", {"loop": False, "volume": 0.8, "preset": "light", "output": "Example"})
            t = scaffold.create_from_example("MyMovie", root)
            out = build_cia(BuildOptions(t, output_dir=Path(d) / "out", compress_code=False))
            self.assertEqual(out.name, "MyMovie.cia")  # 出力名は雛形の "Example" ではなくテンプレート名
            self.assertTrue(out.stat().st_size > 1000)


if __name__ == "__main__":
    unittest.main()
