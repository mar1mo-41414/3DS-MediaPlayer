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
        self.assertIn("template", err)

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

    def test_no_compress_flag(self):
        with mock.patch.object(cli, "build_cia") as b:
            run_cli("tpl")
            self.assertTrue(b.call_args[0][0].compress_code)
            run_cli("tpl", "--no-compress")
            self.assertFalse(b.call_args[0][0].compress_code)

    def test_all_presets_are_selectable(self):
        from mkcia.video import PRESETS

        for name in PRESETS:
            with mock.patch.object(cli, "build_cia") as b:
                rc, _, _ = run_cli("tpl", "--preset", name)
            self.assertEqual(rc, 0)
            self.assertEqual(b.call_args[0][0].preset, name)


class ExitCodeTest(unittest.TestCase):
    def test_user_error_returns_1_with_message(self):
        with mock.patch.object(cli, "build_cia", side_effect=MkciaError("ここが悪い")):
            rc, out, err = run_cli("tpl")
        self.assertEqual(rc, cli.EXIT_USER_ERROR)
        self.assertIn("エラー: ここが悪い", err)
        self.assertNotIn("Traceback", err)

    def test_internal_error_returns_2_without_traceback(self):
        with mock.patch.object(cli, "build_cia", side_effect=RuntimeError("boom")):
            rc, _, err = run_cli("tpl")
        self.assertEqual(rc, cli.EXIT_INTERNAL)
        self.assertIn("内部エラー", err)
        self.assertIn("boom", err)
        self.assertIn("--debug", err)
        self.assertNotIn("Traceback", err)

    def test_internal_error_with_debug_shows_traceback(self):
        with mock.patch.object(cli, "build_cia", side_effect=RuntimeError("boom")):
            rc, _, err = run_cli("tpl", "--debug")
        self.assertEqual(rc, cli.EXIT_INTERNAL)
        self.assertIn("Traceback", err)

    def test_various_unexpected_exceptions_are_contained(self):
        for exc in (ValueError("v"), KeyError("k"), OSError(28, "No space left on device"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
                    ZeroDivisionError(), MemoryError(), RecursionError(), PermissionError(13, "denied")):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(cli, "build_cia", side_effect=exc):
                    rc, _, err = run_cli("tpl")
                self.assertEqual(rc, cli.EXIT_INTERNAL)
                self.assertIn("内部エラー", err)

    def test_keyboard_interrupt_returns_130(self):
        with mock.patch.object(cli, "build_cia", side_effect=KeyboardInterrupt):
            rc, _, err = run_cli("tpl")
        self.assertEqual(rc, cli.EXIT_INTERRUPTED)
        self.assertIn("中断", err)

    def test_success_returns_0(self):
        with mock.patch.object(cli, "build_cia"):
            rc, _, err = run_cli("tpl")
        self.assertEqual((rc, err), (0, ""))


class DefaultOutputNameTest(unittest.TestCase):
    def out_for(self, template, cwd=None):
        with mock.patch.object(cli, "build_cia") as b:
            old = os.getcwd()
            try:
                if cwd:
                    os.chdir(cwd)
                run_cli(str(template))
            finally:
                os.chdir(old)
        return b.call_args[0][0].output

    def test_named_after_template_dir_next_to_it(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.out_for(Path(d) / "My Movie")
            self.assertEqual(out, Path(d).resolve() / "My Movie.cia")

    def test_trailing_slash(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.out_for(str(Path(d) / "tpl") + "/")
            self.assertEqual(out.name, "tpl.cia")

    def test_dot_uses_directory_name(self):
        with tempfile.TemporaryDirectory() as d:
            sub = Path(d) / "mytemplate"
            sub.mkdir()
            out = self.out_for(".", cwd=sub)
            self.assertEqual(out.name, "mytemplate.cia")

    def test_explicit_output_wins(self):
        with mock.patch.object(cli, "build_cia") as b:
            run_cli("tpl", "-o", "/x/y/z.cia")
        self.assertEqual(b.call_args[0][0].output, Path("/x/y/z.cia"))


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
