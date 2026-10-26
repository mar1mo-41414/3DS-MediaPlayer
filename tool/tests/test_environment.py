"""ROM の ELF / 出力先 / 外部ツールの検証。"""

import os
import stat
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import NO_PERM_CHECK, base_assets, cleanup_assets, make_template, requires_tools, skip_no_symlink, skip_on_windows
from mkcia import validate
from mkcia.errors import MkciaError
from mkcia.pipeline import DEFAULT_ELF
from mkcia.validate import check_elf, check_output, check_tools


def tearDownModule():
    cleanup_assets()


def elf_header(ei_class=1, ei_data=1, machine=40, size=64) -> bytes:
    h = bytearray(size)
    h[:4] = b"\x7fELF"
    h[4], h[5], h[6] = ei_class, ei_data, 1
    struct.pack_into("<H" if ei_data == 1 else ">H", h, 18, machine)
    return bytes(h)


class ElfCheckTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def msg(self, p):
        with self.assertRaises(MkciaError) as cm:
            check_elf(p)
        return str(cm.exception)

    def write(self, name, data):
        p = self.d / name
        p.write_bytes(data)
        return p

    def test_missing(self):
        self.assertIn("見つかりません", self.msg(self.d / "none.elf"))

    def test_directory(self):
        self.assertIn("ディレクトリ", self.msg(self.d))

    def test_bad_files(self):
        cases = {
            "empty": b"",
            "text": b"this is not an elf file at all, sorry",
            "magic-only": b"\x7fELF",
            "short-header": b"\x7fELF" + b"\x01" * 10,
            "zeros": bytes(100),
        }
        for name, data in cases.items():
            with self.subTest(name=name):
                self.assertIn("ELF", self.msg(self.write(name, data)))

    def test_wrong_architecture(self):
        cases = {
            "elf64": elf_header(ei_class=2),
            "big-endian": elf_header(ei_data=2),
            "x86": elf_header(machine=3),
            "x86_64": elf_header(machine=62),
            "aarch64": elf_header(machine=183),
        }
        for name, data in cases.items():
            with self.subTest(name=name):
                self.assertIn("3DS", self.msg(self.write(name, data)))

    def test_valid_arm_header(self):
        p = self.write("ok.elf", elf_header())
        self.assertEqual(check_elf(p), p)

    @unittest.skipUnless(DEFAULT_ELF.is_file(), "prebuilt ELF が無い")
    def test_prebuilt_elf_passes(self):
        check_elf(DEFAULT_ELF)

    @unittest.skipIf(NO_PERM_CHECK, "権限ビットが効かない環境 (root / Windows)")
    def test_unreadable(self):
        p = self.write("x.elf", elf_header())
        os.chmod(p, 0)
        try:
            self.assertIn("読めません", self.msg(p))
        finally:
            os.chmod(p, 0o644)


class OutputCheckTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)
        self.inp = self.d / "video.mp4"
        self.inp.write_bytes(b"x")

    def tearDown(self):
        self._d.cleanup()

    def msg(self, out, inputs=None):
        with self.assertRaises(MkciaError) as cm:
            check_output(out, inputs if inputs is not None else [self.inp])
        return str(cm.exception)

    def test_ok(self):
        out = self.d / "out.cia"
        self.assertEqual(check_output(out, [self.inp]), out)

    def test_missing_parent_directories_are_ok(self):
        check_output(self.d / "a" / "b" / "c" / "out.cia", [self.inp])

    def test_extension_must_be_cia(self):
        for name in ("out", "out.txt", "out.cia.bak", "out.3dsx", "out.CIA.zip"):
            with self.subTest(name=name):
                self.assertIn(".cia", self.msg(self.d / name))
        check_output(self.d / "OUT.CIA", [self.inp])  # 大文字小文字は問わない

    def test_directory_as_output(self):
        d = self.d / "dir.cia"
        d.mkdir()
        self.assertIn("ディレクトリ", self.msg(d))

    @skip_no_symlink
    def test_same_as_input(self):
        link = self.d / "alias.cia"
        link.symlink_to(self.inp)
        self.assertIn("入力ファイルと同じ", self.msg(link))

    def test_parent_is_a_file(self):
        self.assertIn("ディレクトリではありません", self.msg(self.inp / "out.cia"))

    @unittest.skipIf(NO_PERM_CHECK, "権限ビットが効かない環境 (root / Windows)")
    def test_unwritable_parent(self):
        ro = self.d / "ro"
        ro.mkdir()
        os.chmod(ro, stat.S_IRUSR | stat.S_IXUSR)
        try:
            self.assertIn("書き込めません", self.msg(ro / "out.cia"))
            self.assertIn("書き込めません", self.msg(ro / "sub" / "out.cia"))  # まだ無い親も、作れないので NG
        finally:
            os.chmod(ro, 0o755)

    def test_existing_output_file_is_ok(self):
        out = self.d / "exists.cia"
        out.write_bytes(b"old")
        check_output(out, [self.inp])

    def test_unicode_and_spaces(self):
        check_output(self.d / "日本語 名前" / "夜 の 出力.cia", [self.inp])


class ToolsCheckTest(unittest.TestCase):
    def test_all_missing_are_listed_together(self):
        def fake_find(name):
            raise MkciaError(f"外部ツール '{name}' が見つかりません")

        with mock.patch.object(validate, "find_tool", fake_find):
            with self.assertRaises(MkciaError) as cm:
                check_tools()
        m = str(cm.exception)
        for t in validate.REQUIRED_TOOLS:
            self.assertIn(t, m)
        self.assertIn("setup-tools.sh", m)

    def test_only_some_missing(self):
        def fake_find(name):  # 実際のツールの有無に依存しない: makerom と 3dstool だけが無い状況を作る
            if name in ("makerom", "3dstool"):
                raise MkciaError("x")
            return f"/fake/{name}"

        with mock.patch.object(validate, "find_tool", fake_find):
            with self.assertRaises(MkciaError) as cm:
                check_tools()
        m = str(cm.exception)
        self.assertIn("makerom", m)
        self.assertIn("3dstool", m)
        self.assertNotIn("ffmpeg,", m)

    @requires_tools
    @skip_on_windows  # シェルスクリプトの偽 ffmpeg を使う
    def test_ffmpeg_without_libx264(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "ffmpeg"
            fake.write_text("#!/bin/sh\ncat <<'EOF'\n Encoders:\n V....D mpeg4   MPEG-4 part 2\n A....D aac   AAC\nEOF\n")
            fake.chmod(0o755)
            with mock.patch.dict(os.environ, {"MKCIA_TOOLS_DIR": d}):
                with self.assertRaises(MkciaError) as cm:
                    check_tools()
        self.assertIn("libx264", str(cm.exception))

    @requires_tools
    @skip_on_windows  # シェルスクリプトの偽 ffmpeg を使う
    def test_ffmpeg_without_aac(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "ffmpeg"
            fake.write_text("#!/bin/sh\ncat <<'EOF'\n Encoders:\n V....D libx264   H.264\nEOF\n")
            fake.chmod(0o755)
            with mock.patch.dict(os.environ, {"MKCIA_TOOLS_DIR": d}):
                with self.assertRaises(MkciaError) as cm:
                    check_tools()
        self.assertIn("aac", str(cm.exception))

    @requires_tools
    def test_tools_dir_overrides_path(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "ffprobe"
            fake.write_text("#!/bin/sh\necho fake\n")
            fake.chmod(0o755)
            with mock.patch.dict(os.environ, {"MKCIA_TOOLS_DIR": d}):
                self.assertEqual(validate.find_tool("ffprobe"), str(fake))

    @requires_tools
    @skip_on_windows  # Windows には実行権限ビットが無い
    def test_non_executable_in_tools_dir_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "ffprobe").write_text("not executable")
            with mock.patch.dict(os.environ, {"MKCIA_TOOLS_DIR": d}):
                self.assertNotEqual(validate.find_tool("ffprobe"), str(Path(d) / "ffprobe"))

    @requires_tools
    def test_real_tools_pass(self):
        check_tools()


if __name__ == "__main__":
    unittest.main()
