"""CLI の終了コードとエラー表示。"""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import cleanup_assets, make_template, requires_tools
from mkcia import cli
from mkcia.errors import MkciaError


def tearDownModule():
    cleanup_assets()


class FakeTemplate:
    """meta.json だけがあるダミーのテンプレート (build_cia を差し替えるテスト用)。"""

    def __enter__(self):
        self._d = tempfile.TemporaryDirectory()
        self.path = Path(self._d.name) / "tpl"
        self.path.mkdir()
        (self.path / "meta.json").write_text("{}")
        return str(self.path)

    def __exit__(self, *a):
        self._d.cleanup()


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = cli.main(list(argv))
        except SystemExit as e:  # argparse のエラー
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


class ArgparseTest(unittest.TestCase):
    def test_no_arguments(self):
        rc, _, err = run_cli()
        self.assertEqual(rc, 2)
        self.assertIn("テンプレート", err)

    def test_unknown_preset(self):
        rc, _, err = run_cli("somewhere", "--preset", "ultra")
        self.assertEqual(rc, 2)
        self.assertIn("ultra", err)

    def test_unknown_option(self):
        rc, _, err = run_cli("somewhere", "--frobnicate")
        self.assertEqual(rc, 2)

    def test_help_exits_zero(self):
        rc, out, _ = run_cli("--help")
        self.assertEqual(rc, 0)
        self.assertIn("--preset", out)
        self.assertIn("--output-dir", out)

    def test_no_compress_flag(self):
        with FakeTemplate() as t, mock.patch.object(cli, "build_cia") as b:
            run_cli(t)
            self.assertTrue(b.call_args[0][0].compress_code)
            run_cli(t, "--no-compress")
            self.assertFalse(b.call_args[0][0].compress_code)

    def test_all_presets_are_selectable(self):
        from mkcia.video import PRESETS

        for name in PRESETS:
            with FakeTemplate() as t, mock.patch.object(cli, "build_cia") as b:
                rc, _, _ = run_cli(t, "--preset", name)
            self.assertEqual(rc, 0)
            self.assertEqual(b.call_args[0][0].preset, name)

    def test_preset_defaults_to_none_so_meta_can_decide(self):
        with FakeTemplate() as t, mock.patch.object(cli, "build_cia") as b:
            run_cli(t)
        self.assertIsNone(b.call_args[0][0].preset)


class ExitCodeTest(unittest.TestCase):
    def run_with(self, exc):
        with FakeTemplate() as t, mock.patch.object(cli, "build_cia", side_effect=exc):
            return run_cli(t)

    def test_user_error_returns_1_with_message(self):
        rc, out, err = self.run_with(MkciaError("ここが悪い"))
        self.assertEqual(rc, cli.EXIT_USER_ERROR)
        self.assertIn("エラー: ここが悪い", err)
        self.assertNotIn("Traceback", err)

    def test_internal_error_returns_2_without_traceback(self):
        rc, _, err = self.run_with(RuntimeError("boom"))
        self.assertEqual(rc, cli.EXIT_INTERNAL)
        self.assertIn("内部エラー", err)
        self.assertIn("boom", err)
        self.assertIn("--debug", err)
        self.assertNotIn("Traceback", err)

    def test_internal_error_with_debug_shows_traceback(self):
        with FakeTemplate() as t, mock.patch.object(cli, "build_cia", side_effect=RuntimeError("boom")):
            rc, _, err = run_cli(t, "--debug")
        self.assertEqual(rc, cli.EXIT_INTERNAL)
        self.assertIn("Traceback", err)

    def test_various_unexpected_exceptions_are_contained(self):
        for exc in (ValueError("v"), KeyError("k"), OSError(28, "No space left on device"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
                    ZeroDivisionError(), MemoryError(), RecursionError(), PermissionError(13, "denied")):
            with self.subTest(exc=type(exc).__name__):
                rc, _, err = self.run_with(exc)
                self.assertEqual(rc, cli.EXIT_INTERNAL)
                self.assertIn("内部エラー", err)

    def test_keyboard_interrupt_returns_130(self):
        rc, _, err = self.run_with(KeyboardInterrupt())
        self.assertEqual(rc, cli.EXIT_INTERRUPTED)
        self.assertIn("中断", err)

    def test_success_returns_0(self):
        with FakeTemplate() as t, mock.patch.object(cli, "build_cia"):
            rc, _, err = run_cli(t)
        self.assertEqual((rc, err), (0, ""))


class TemplateResolutionTest(unittest.TestCase):
    """テンプレートは「パス」でも「template/ 配下の名前」でも指定できる。"""

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.root = Path(self._d.name)
        self.troot = self.root / "template"
        self.troot.mkdir()
        p = mock.patch.object(cli, "TEMPLATE_ROOT", self.troot)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self._d.cleanup()

    def mk(self, base, name, with_meta=True):
        d = base / name
        d.mkdir(parents=True, exist_ok=True)
        if with_meta:
            (d / "meta.json").write_text("{}")
        return d

    def test_bare_name_resolves_under_template_root(self):
        d = self.mk(self.troot, "Twinkle_Night")
        self.assertEqual(cli.resolve_template(Path("Twinkle_Night")), d)

    def test_name_with_spaces_and_unicode(self):
        d = self.mk(self.troot, "ツイン クル 夜")
        self.assertEqual(cli.resolve_template(Path("ツイン クル 夜")), d)

    def test_existing_path_is_used_as_is(self):
        d = self.mk(self.root, "elsewhere")
        self.assertEqual(cli.resolve_template(d), d)

    def test_path_wins_over_name_when_both_are_templates(self):
        self.mk(self.troot, "dup")
        cwd = os.getcwd()
        other = self.mk(self.root / "cwd", "dup")
        try:
            os.chdir(self.root / "cwd")
            self.assertEqual(cli.resolve_template(Path("dup")), Path("dup"))
        finally:
            os.chdir(cwd)

    def test_template_beats_a_plain_directory_of_the_same_name(self):
        """カレントに同名の (meta.json の無い) ディレクトリがあっても、template/ 側の本物を使う。"""
        real = self.mk(self.troot, "movie")
        cwd = os.getcwd()
        self.mk(self.root / "cwd", "movie", with_meta=False)
        try:
            os.chdir(self.root / "cwd")
            self.assertEqual(cli.resolve_template(Path("movie")), real)
        finally:
            os.chdir(cwd)

    def test_nested_name(self):
        d = self.mk(self.troot / "group", "sub")
        self.assertEqual(cli.resolve_template(Path("group/sub")), d)

    def test_not_found_lists_available_templates(self):
        self.mk(self.troot, "alpha")
        self.mk(self.troot, "beta")
        with self.assertRaises(MkciaError) as cm:
            cli.resolve_template(Path("gamma"))
        m = str(cm.exception)
        self.assertIn("gamma", m)
        self.assertIn("alpha", m)
        self.assertIn("beta", m)

    def test_not_found_without_any_templates(self):
        with self.assertRaises(MkciaError) as cm:
            cli.resolve_template(Path("whatever"))
        self.assertNotIn("使えるテンプレート", str(cm.exception))

    def test_directories_without_meta_are_not_listed(self):
        self.mk(self.troot, "ok")
        self.mk(self.troot, "junk", with_meta=False)
        (self.troot / "file.txt").write_text("x")
        self.assertEqual(cli.list_templates(), ["ok"])

    def test_list_option(self):
        self.mk(self.troot, "b_tpl")
        self.mk(self.troot, "a_tpl")
        rc, out, _ = run_cli("--list")
        self.assertEqual((rc, out.split()), (0, ["a_tpl", "b_tpl"]))

    def test_list_with_no_templates(self):
        rc, out, _ = run_cli("--list")
        self.assertEqual(rc, 0)
        self.assertIn("テンプレートがありません", out)

    def test_cli_passes_resolved_template_to_build(self):
        d = self.mk(self.troot, "Named")
        with mock.patch.object(cli, "build_cia") as b:
            rc, _, _ = run_cli("Named")
        self.assertEqual(rc, 0)
        self.assertEqual(b.call_args[0][0].template_dir, d)

    def test_unknown_name_is_a_user_error(self):
        rc, _, err = run_cli("nonexistent_template_xyz")
        self.assertEqual(rc, cli.EXIT_USER_ERROR)
        self.assertIn("見つかりません", err)


class OutputOptionsTest(unittest.TestCase):
    def opts(self, *args):
        with FakeTemplate() as t, mock.patch.object(cli, "build_cia") as b:
            rc, _, err = run_cli(t, *args)
        self.assertEqual(rc, 0, err)
        return b.call_args[0][0]

    def test_defaults_leave_output_to_the_pipeline(self):
        o = self.opts()
        self.assertIsNone(o.output)
        self.assertIsNone(o.output_dir)

    def test_explicit_output(self):
        self.assertEqual(self.opts("-o", "/x/y/z.cia").output, Path("/x/y/z.cia"))
        self.assertEqual(self.opts("--output", "rel.cia").output, Path("rel.cia"))

    def test_output_dir(self):
        self.assertEqual(self.opts("--output-dir", "/some/dir").output_dir, Path("/some/dir"))


@requires_tools
class RealErrorsThroughCliTest(unittest.TestCase):
    """実物のツール類を通して、ユーザー向けのエラーが返ること (遅い処理の前に落ちる)。"""

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def test_missing_template(self):
        rc, _, err = run_cli(str(self.d / "nope"), "-o", str(self.d / "o.cia"))
        self.assertEqual(rc, 1)
        self.assertIn("見つかりません", err)
        self.assertFalse((self.d / "o.cia").exists())

    def test_bad_meta_is_reported_before_encoding(self):
        t = make_template(self.d / "t", {"volume": "loud"})
        with mock.patch("mkcia.video.encode_video", side_effect=AssertionError("エンコードに進んではいけない")):
            rc, _, err = run_cli(str(t), "-o", str(self.d / "o.cia"))
        self.assertEqual(rc, 1)
        self.assertIn("volume", err)

    def test_stdout_progress_and_stderr_error_are_separate(self):
        t = make_template(self.d / "t", {"title": ""})
        rc, out, err = run_cli(str(t), "-o", str(self.d / "o.cia"))
        self.assertEqual(rc, 1)
        self.assertIn("[1/6]", out)
        self.assertIn("エラー", err)
        self.assertNotIn("エラー", out)


if __name__ == "__main__":
    unittest.main()
