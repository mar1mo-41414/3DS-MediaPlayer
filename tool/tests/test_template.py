"""テンプレートディレクトリの構成チェック (check_template)。"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import NO_PERM_CHECK, base_assets, cleanup_assets, make_template, requires_tools, skip_no_symlink
from mkcia.errors import MkciaError
from mkcia.validate import check_template


def tearDownModule():
    cleanup_assets()


@requires_tools
class TemplateStructureTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.root = Path(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def msg(self, path):
        with self.assertRaises(MkciaError) as cm:
            check_template(path)
        return str(cm.exception)

    def test_ok(self):
        f = check_template(make_template(self.root / "t"))
        self.assertEqual(f.video.name, "video.mp4")
        self.assertEqual(f.sound.name, "select_sound.wav")
        self.assertIsNone(f.banner)

    def test_sound_is_optional(self):
        self.assertIsNone(check_template(make_template(self.root / "t", copy_sound=False)).sound)

    def test_nonexistent(self):
        self.assertIn("見つかりません", self.msg(self.root / "nope"))

    def test_path_is_a_file(self):
        f = self.root / "file.txt"
        f.write_text("x")
        self.assertIn("ディレクトリで指定", self.msg(f))

    def test_empty_directory_lists_what_is_required(self):
        """必須は meta.json と動画だけ。icon / bottom は無ければ動画から作るので、挙げない。"""
        d = self.root / "empty"
        d.mkdir()
        m = self.msg(d)
        for label in ("meta.json", "video."):
            self.assertIn(label, m)
        for label in ("icon.", "bottom."):
            self.assertNotIn(label, m)

    def test_each_required_file_missing(self):
        for name, label in (("video.mp4", "video."), ("meta.json", "meta.json")):
            with self.subTest(name=name):
                d = make_template(self.root / f"no_{name}", skip=(name,))
                m = self.msg(d)
                self.assertIn(label, m)
                self.assertIn("必要なファイルがありません", m)

    def test_multiple_missing_are_all_reported(self):
        d = make_template(self.root / "t", skip=("video.mp4", "meta.json"))
        m = self.msg(d)
        self.assertIn("video.", m)
        self.assertIn("meta.json", m)

    def test_icon_and_bottom_are_optional(self):
        """icon / bottom が無くてもテンプレートとして成立する (動画から作る)。"""
        for skip in (("icon.png",), ("bottom.png",), ("icon.png", "bottom.png")):
            with self.subTest(skip=skip):
                f = check_template(make_template(self.root / ("t_" + "_".join(skip)), skip=skip))
                self.assertEqual(f.icon is None, "icon.png" in skip)
                self.assertEqual(f.bottom is None, "bottom.png" in skip)
                self.assertEqual(f.video.name, "video.mp4")

    def test_required_file_is_a_directory(self):
        for name in ("video.mp4", "icon.png", "bottom.png", "meta.json"):
            with self.subTest(name=name):
                d = make_template(self.root / f"dir_{name}", skip=(name,))
                (d / name).mkdir()
                self.assertIn("ディレクトリ", self.msg(d))

    def test_required_file_is_empty(self):
        for name in ("video.mp4", "icon.png", "bottom.png", "meta.json", "select_sound.wav"):
            with self.subTest(name=name):
                d = make_template(self.root / f"empty_{name}")
                (d / name).write_bytes(b"")
                m = self.msg(d)
                self.assertIn("空", m)
                self.assertIn(name, m)

    @skip_no_symlink
    def test_broken_symlink(self):
        d = make_template(self.root / "t", skip=("video.mp4",))
        (d / "video.mp4").symlink_to(self.root / "does-not-exist")
        self.assertIn("開けません", self.msg(d))

    @skip_no_symlink
    def test_symlinked_inputs_are_accepted(self):
        d = make_template(self.root / "t", skip=("video.mp4",))
        (d / "video.mp4").symlink_to(base_assets() / "video.mp4")
        self.assertEqual(check_template(d).video.name, "video.mp4")

    @unittest.skipIf(NO_PERM_CHECK, "権限ビットが効かない環境 (root / Windows)")
    def test_unreadable_file(self):
        d = make_template(self.root / "t")
        os.chmod(d / "icon.png", 0)
        try:
            self.assertIn("読み取り権限", self.msg(d))
        finally:
            os.chmod(d / "icon.png", 0o644)

    def test_alternative_extensions(self):
        d = self.root / "alt"
        d.mkdir()
        shutil.copyfile(base_assets() / "video.mp4", d / "video.mkv")
        shutil.copyfile(base_assets() / "icon.png", d / "icon.jpg")
        shutil.copyfile(base_assets() / "bottom.png", d / "bottom.webp")
        shutil.copyfile(base_assets() / "meta.json", d / "meta.json")
        shutil.copyfile(base_assets() / "select_sound.wav", d / "select_sound.mp3")
        f = check_template(d)
        self.assertEqual((f.video.name, f.icon.name, f.bottom.name, f.sound.name),
                         ("video.mkv", "icon.jpg", "bottom.webp", "select_sound.mp3"))

    def test_extension_priority(self):
        d = make_template(self.root / "t")
        shutil.copyfile(base_assets() / "video.mp4", d / "video.mkv")
        shutil.copyfile(base_assets() / "select_sound.wav", d / "select_sound.mp3")
        f = check_template(d)
        self.assertEqual(f.video.name, "video.mp4")
        self.assertEqual(f.sound.name, "select_sound.wav")

    def test_unsupported_extension_is_not_picked_up(self):
        d = make_template(self.root / "t", skip=("video.mp4",))
        shutil.copyfile(base_assets() / "video.mp4", d / "video.xyz")
        self.assertIn("video.", self.msg(d))

    def test_optional_banner_is_detected(self):
        d = make_template(self.root / "t")
        shutil.copyfile(base_assets() / "icon.png", d / "banner.png")
        self.assertEqual(check_template(d).banner.name, "banner.png")

    def test_paths_with_spaces_and_unicode(self):
        d = make_template(self.root / "日本語 の 名前")
        self.assertEqual(check_template(d).root.name, "日本語 の 名前")

    def test_trailing_slash_and_relative(self):
        d = make_template(self.root / "t")
        self.assertEqual(check_template(Path(str(d) + "/")).video.name, "video.mp4")
        cwd = os.getcwd()
        try:
            os.chdir(self.root)
            self.assertEqual(check_template(Path("t")).video.name, "video.mp4")
            self.assertEqual(check_template(Path("./t/../t")).video.name, "video.mp4")
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
