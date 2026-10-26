"""実際に CIA を作る通しテスト (ffmpeg / bannertool / 3dstool / makerom を使う。やや遅い)。"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import (
    GOOD_META,
    MISSING,
    base_assets,
    cleanup_assets,
    ffmpeg,
    make_audio,
    make_image,
    make_template,
    make_video,
    read_cia_info,
    requires_tools,
    skip_no_symlink,
    skip_on_windows,
)
from mkcia import pipeline, video
from mkcia.errors import MkciaError
from mkcia.pipeline import DEFAULT_ELF, BuildOptions, build_cia
from mkcia.proc import find_tool


def tearDownModule():
    cleanup_assets()


def probe_json(path, *entries):
    out = subprocess.run([find_tool("ffprobe"), "-v", "error", "-show_entries", "stream=" + ",".join(entries),
                          "-of", "json", str(path)], capture_output=True, text=True).stdout
    return json.loads(out)["streams"]


@requires_tools
class E2EBase(unittest.TestCase):
    preset = "light"  # 速いので既定は light

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)
        self.logs = []

    def tearDown(self):
        self._d.cleanup()

    def build(self, tpl, out=None, preset=None, **kw):
        out = out or self.d / "out.cia"
        kw.setdefault("compress_code", False)  # makerom の圧縮が 1 回約 8 秒かかるので、通常のテストでは省く
        opt = BuildOptions(Path(tpl), Path(out), preset=preset or self.preset, **kw)
        return build_cia(opt, log=self.logs.append)

    def assertValidCia(self, path, title_id="000400000FF3A000"):
        info = read_cia_info(path)
        self.assertEqual(info["ncch_magic"], b"NCCH")
        self.assertEqual(info["title_id"], title_id)
        return info

    def assertNoLeftovers(self, directory):
        left = [p.name for p in Path(directory).iterdir() if p.name.endswith(".tmp") or p.name.startswith(".")]
        self.assertEqual(left, [])


class SuccessTest(E2EBase):
    def test_default_build_with_code_compression(self):
        """製品と同じ既定 (ELF コードを圧縮) でも作れる。圧縮なしより小さい。"""
        t = make_template(self.d / "t")
        packed = self.build(t, self.d / "packed.cia", compress_code=True)
        plain = self.build(t, self.d / "plain.cia", compress_code=False)
        self.assertValidCia(packed)
        self.assertLess(packed.stat().st_size, plain.stat().st_size)

    @skip_on_windows
    def test_output_permissions_follow_umask(self):
        old = os.umask(0o022)
        try:
            out = self.build(make_template(self.d / "t"))
        finally:
            os.umask(old)
        self.assertEqual(out.stat().st_mode & 0o777, 0o644)

    def test_basic_build(self):
        out = self.build(make_template(self.d / "t"))
        self.assertTrue(out.is_file())
        info = self.assertValidCia(out)
        self.assertEqual(info["smdh_title"], "TestApp")
        self.assertTrue(any("完了" in l for l in self.logs))
        self.assertNoLeftovers(self.d)

    def test_every_preset_builds(self):
        for name in video.PRESETS:
            with self.subTest(preset=name):
                self.assertValidCia(self.build(make_template(self.d / f"t_{name}"), self.d / f"{name}.cia", preset=name))

    def test_video_without_audio(self):
        t = make_template(self.d / "t")
        make_video(t / "video.mp4", audio=False)
        self.assertValidCia(self.build(t))
        self.assertTrue(any("音声がありません" in l for l in self.logs))

    def test_template_without_sound_builds_with_the_default_sound(self):
        self.assertValidCia(self.build(make_template(self.d / "t", copy_sound=False)))
        self.assertTrue(any("既定のタイトル選択音" in l for l in self.logs))

    def test_alternative_input_formats(self):
        t = self.d / "alt"
        t.mkdir()
        shutil.copyfile(base_assets() / "meta.json", t / "meta.json")
        ffmpeg("-i", base_assets() / "video.mp4", "-c", "copy", t / "video.mkv")
        ffmpeg("-i", base_assets() / "icon.png", t / "icon.jpg")
        ffmpeg("-i", base_assets() / "bottom.png", t / "bottom.bmp")
        ffmpeg("-i", base_assets() / "select_sound.wav", "-c:a", "flac", t / "select_sound.flac")
        self.assertValidCia(self.build(t))

    def test_custom_banner_image(self):
        t = make_template(self.d / "t")
        make_image(t / "banner.png", "256x128")
        self.assertValidCia(self.build(t))

    def test_long_sound_is_trimmed_not_rejected(self):
        t = make_template(self.d / "t", skip=("select_sound.wav",))
        make_audio(t / "select_sound.wav", seconds=10)
        keep = self.d / "work"
        self.build(t, keep_work=keep)
        dur = float(subprocess.run([find_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of",
                                    "csv=p=0", str(keep / "banner.wav")], capture_output=True, text=True).stdout)
        self.assertLessEqual(dur, 3.05)

    def test_title_at_the_length_limit(self):
        t = make_template(self.d / "t", {"title": "T" * 64, "long_title": "L" * 128, "publisher": "P" * 64})
        self.assertValidCia(self.build(t))

    def test_paths_with_spaces_unicode_and_relative(self):
        t = make_template(self.d / "動画 テンプレート (1)")
        out = self.d / "出力 先" / "日本語 名前.cia"
        self.assertValidCia(self.build(t, out))
        cwd = os.getcwd()
        try:
            os.chdir(self.d)
            self.assertValidCia(self.build(Path("動画 テンプレート (1)"), Path("rel/out.cia")))
        finally:
            os.chdir(cwd)
        self.assertTrue((self.d / "rel" / "out.cia").is_file())

    @skip_no_symlink
    def test_symlinked_inputs(self):
        t = make_template(self.d / "t", skip=("video.mp4", "icon.png"))
        (t / "video.mp4").symlink_to(base_assets() / "video.mp4")
        (t / "icon.png").symlink_to(base_assets() / "icon.png")
        self.assertValidCia(self.build(t))

    def test_output_parent_directories_are_created(self):
        out = self.d / "a" / "b" / "c" / "out.cia"
        self.assertValidCia(self.build(make_template(self.d / "t"), out))

    def test_unknown_meta_keys_warn_but_build(self):
        t = make_template(self.d / "t", {"color": "red"})
        self.assertValidCia(self.build(t))
        self.assertTrue(any("警告" in l and "color" in l for l in self.logs))

    def test_keep_work_leaves_artifacts(self):
        keep = self.d / "keep"
        self.build(make_template(self.d / "t"), keep_work=keep)
        for name in ("video.mp4", "app.smdh", "app.bnr", "romfs.bin", "app.rsf", "romfs/config.json"):
            self.assertTrue((keep / name).exists(), name)
        cfg = json.loads((keep / "romfs" / "config.json").read_text())
        self.assertEqual(set(cfg), {"loop", "volume", "deblock"})

    def test_config_reflects_meta(self):
        keep = self.d / "keep"
        self.build(make_template(self.d / "t", {"loop": True, "volume": 0.25}), keep_work=keep)
        cfg = json.loads((keep / "romfs" / "config.json").read_text())
        self.assertEqual((cfg["loop"], cfg["volume"]), (True, 0.25))

    def test_rebuild_overwrites_previous_output(self):
        t = make_template(self.d / "t")
        out = self.d / "out.cia"
        self.build(t, out)
        first = out.read_bytes()
        self.build(make_template(self.d / "t2", {"version": "2.0.0"}), out)
        self.assertNotEqual(first, out.read_bytes())
        self.assertNoLeftovers(self.d)


class TitleTest(E2EBase):
    def test_japanese_title_gets_ascii_internal_name(self):
        t = make_template(self.d / "t", {"title": "日本語タイトル", "publisher": "日本語の人"})
        info = self.assertValidCia(self.build(t))
        self.assertEqual(info["smdh_title"], "日本語タイトル")  # ホームメニュー用はそのまま
        self.assertEqual(info["product_name"], b"MPLAYER")  # 内部名は ASCII のみ (UTF-8 の途中切れを作らない)
        info["product_name"].decode("ascii")

    def test_mixed_title_keeps_ascii_part(self):
        t = make_template(self.d / "t", {"title": "My 動画 Player"})
        self.assertEqual(self.assertValidCia(self.build(t))["product_name"], b"My  Pla")

    def test_title_with_quotes_and_symbols(self):
        for title in ('Say "Hi"', "a:b#c%d", "100%", "{braces}", "back\\slash", "it's", "<tag>", "a&b|c;d$e"):
            with self.subTest(title=title):
                t = make_template(self.d / "t", {"title": title})
                info = self.assertValidCia(self.build(t))
                self.assertEqual(info["smdh_title"], title)

    def test_emoji_title(self):
        t = make_template(self.d / "t", {"title": "🎬 Movie"})
        self.assertEqual(self.assertValidCia(self.build(t))["smdh_title"], "🎬 Movie")


class FailureTest(E2EBase):
    """失敗は、重い処理に入る前に、どのファイルが悪いかを添えて返す。出力は作らない。"""

    def fails(self, tpl, contains, out=None):
        out = out or self.d / "out.cia"
        with mock.patch("mkcia.video.encode_video", side_effect=AssertionError("エンコードに進んではいけない")):
            with self.assertRaises(MkciaError) as cm:
                self.build(tpl, out)
        self.assertIn(contains, str(cm.exception))
        if not Path(out).is_dir():  # 出力先がもともとディレクトリのケースは「存在しない」を確認できない
            self.assertFalse(Path(out).exists())
        if Path(out).parent.is_dir():
            self.assertNoLeftovers(Path(out).parent)
        return str(cm.exception)

    def test_each_corrupted_input_is_named(self):
        for name in ("video.mp4", "icon.png", "bottom.png", "select_sound.wav"):
            for label, data in (("text", b"garbage text\n"), ("zeros", bytes(512))):
                with self.subTest(file=name, data=label):
                    t = make_template(self.d / f"t_{name}_{label}")
                    (t / name).write_bytes(data)
                    self.fails(t, name, out=self.d / f"{name}_{label}.cia")

    def test_swapped_files(self):
        t = make_template(self.d / "t")
        shutil.copyfile(base_assets() / "select_sound.wav", t / "video.mp4")  # 音声を video に
        self.fails(t, "映像がありません")
        t2 = make_template(self.d / "t2")
        shutil.copyfile(base_assets() / "video.mp4", t2 / "select_sound.wav")  # 動画 (音声あり) を sound に → OK
        self.build(t2, self.d / "ok.cia")
        t3 = make_template(self.d / "t3")
        shutil.copyfile(base_assets() / "icon.png", t3 / "select_sound.wav")  # 画像を sound に
        self.fails(t3, "音声ストリームがありません", out=self.d / "o3.cia")

    def test_meta_problems_are_reported(self):
        cases = [
            ({"title": MISSING}, "title"),
            ({"publisher": ""}, "publisher"),
            ({"title_id": "123"}, "title_id"),
            ({"version": "1.0"}, "version"),
            ({"volume": 5}, "volume"),
            ({"loop": "yes"}, "loop"),
            ({"title": "x" * 65}, "title"),
        ]
        for ov, key in cases:
            with self.subTest(ov=ov):
                self.fails(make_template(self.d / f"t{key}{len(self.logs)}", ov), key, out=self.d / f"o{key}{ov.get(key, 0) and 1}.cia")

    def test_too_short_video(self):
        t = make_template(self.d / "t")
        make_video(t / "video.mp4", seconds=0.2)
        self.fails(t, "短すぎ")

    def test_too_long_video_is_rejected_by_size_estimate(self):
        t = make_template(self.d / "t")
        real = pipeline.validate_video(t / "video.mp4")
        huge = type(real)(real.width, real.height, 40 * 3600.0, real.fps, real.has_audio)
        with mock.patch.object(pipeline, "validate_video", return_value=huge):
            self.fails(t, "4GB")

    def test_output_problems(self):
        t = make_template(self.d / "t")
        self.fails(t, ".cia", out=self.d / "out.bin")
        (self.d / "adir.cia").mkdir()
        self.fails(t, "ディレクトリ", out=self.d / "adir.cia")
        (self.d / "afile").write_text("x")
        self.fails(t, "ディレクトリではありません", out=self.d / "afile" / "out.cia")

    @skip_no_symlink
    def test_output_cannot_be_an_input(self):
        t = make_template(self.d / "t")
        link = self.d / "link.cia"
        link.symlink_to(t / "video.mp4")
        with self.assertRaises(MkciaError) as cm:
            self.build(t, link)
        self.assertIn("入力ファイルと同じ", str(cm.exception))
        self.assertTrue((t / "video.mp4").stat().st_size > 100)  # 入力は無傷

    def test_bad_elf_is_reported(self):
        t = make_template(self.d / "t")
        for name, data in (("text.elf", b"nope"), ("empty.elf", b""), ("x86.elf", b"\x7fELF\x02\x01\x01" + bytes(60))):
            with self.subTest(elf=name):
                p = self.d / name
                p.write_bytes(data)
                with self.assertRaises(MkciaError) as cm:
                    self.build(t, self.d / f"{name}.cia", elf=p)
                self.assertIn("ELF", str(cm.exception))
        with self.assertRaises(MkciaError):
            self.build(t, self.d / "m.cia", elf=self.d / "missing.elf")

    def test_unknown_preset(self):
        with self.assertRaises(MkciaError) as cm:
            self.build(make_template(self.d / "t"), preset="nonexistent")
        self.assertIn("nonexistent", str(cm.exception))

    def test_missing_pieces_of_the_template(self):
        for name in ("video.mp4", "meta.json"):  # icon / bottom は無くてよい (動画から作る)
            with self.subTest(missing=name):
                self.fails(make_template(self.d / f"m_{name}", skip=(name,)), "必要なファイルがありません",
                           out=self.d / f"m_{name}.cia")

    def test_validation_happens_before_any_expensive_work(self):
        """ffmpeg を一度も走らせずに失敗する (壊れた icon だけでも動画を変換し始めない)。"""
        t = make_template(self.d / "t")
        (t / "icon.png").write_bytes(b"broken")
        with mock.patch("mkcia.video.encode_video", side_effect=AssertionError("エンコード開始")), \
             mock.patch("mkcia.assets.make_icon", side_effect=AssertionError("アセット処理開始")):
            with self.assertRaises(MkciaError):
                self.build(t)


class FailureLeavesOutputIntactTest(E2EBase):
    def test_existing_output_survives_validation_failure(self):
        out = self.d / "out.cia"
        out.write_bytes(b"PRECIOUS")
        t = make_template(self.d / "t", {"volume": "x"})
        with self.assertRaises(MkciaError):
            self.build(t, out)
        self.assertEqual(out.read_bytes(), b"PRECIOUS")

    def test_existing_output_survives_failure_in_the_final_stage(self):
        """ELF の見た目は正しいが makerom が処理できない場合でも、既存の出力を壊さず一時ファイルも残さない。"""
        out = self.d / "out.cia"
        out.write_bytes(b"PRECIOUS")
        elf = self.d / "fake.elf"
        hdr = bytearray(64)
        hdr[:4] = b"\x7fELF"
        hdr[4], hdr[5], hdr[6] = 1, 1, 1
        hdr[18] = 40
        elf.write_bytes(bytes(hdr))
        with self.assertRaises(MkciaError):
            self.build(make_template(self.d / "t"), out, elf=elf)
        self.assertEqual(out.read_bytes(), b"PRECIOUS")
        self.assertNoLeftovers(self.d)

    def test_temp_output_removed_when_cia_stage_raises(self):
        out = self.d / "out.cia"
        with mock.patch("mkcia.cia.build_cia", side_effect=MkciaError("makerom 失敗")):
            with self.assertRaises(MkciaError):
                self.build(make_template(self.d / "t"), out)
        self.assertFalse(out.exists())
        self.assertNoLeftovers(self.d)

    def test_keyboard_interrupt_cleans_up(self):
        out = self.d / "out.cia"
        with mock.patch("mkcia.romfs.build_romfs_bin", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.build(make_template(self.d / "t"), out)
        self.assertFalse(out.exists())
        self.assertNoLeftovers(self.d)

    def test_empty_output_from_makerom_is_an_error(self):
        out = self.d / "out.cia"
        with mock.patch("mkcia.cia.build_cia", side_effect=lambda *a, **k: None):  # 何も書かない
            with self.assertRaises(MkciaError) as cm:
                self.build(make_template(self.d / "t"), out)
        self.assertIn("空", str(cm.exception))
        self.assertFalse(out.exists())

    def test_unwritable_keep_work(self):
        blocker = self.d / "blocker"
        blocker.write_text("file")
        with self.assertRaises(MkciaError) as cm:
            self.build(make_template(self.d / "t"), keep_work=blocker / "work")
        self.assertIn("作業ディレクトリ", str(cm.exception))


class VideoVariantsTest(E2EBase):
    def encode(self, src, preset="light"):
        out = self.d / "enc.mp4"
        video.encode_video(src, out, preset)
        return out

    def test_output_geometry_matches_preset(self):
        for name, p in video.PRESETS.items():
            with self.subTest(preset=name):
                src = make_video(self.d / f"s_{name}.mp4", 1.0, "320x180", 12)
                s = probe_json(self.encode(src, name), "width", "height", "codec_name", "profile")[0]
                self.assertEqual((s["width"], s["height"]), (p.width, p.height))
                self.assertEqual((s["codec_name"], s["profile"]), ("h264", "Constrained Baseline"))

    def test_fps_is_capped_but_never_raised(self):
        for src_fps, want in ((120, 20), (60, 20), (25, 20), (20, 20), (12, 12), (5, 5), (1, 1)):
            with self.subTest(src_fps=src_fps):
                src = make_video(self.d / f"f{src_fps}.mp4", 2.0, "64x48", src_fps, audio=False)
                s = probe_json(self.encode(src, "light"), "avg_frame_rate")[0]
                num, den = s["avg_frame_rate"].split("/")
                self.assertAlmostEqual(int(num) / int(den), want, delta=1.0)

    def test_audio_is_aac_stereo_32k(self):
        src = make_video(self.d / "s.mp4", 1.0)
        s = [x for x in probe_json(self.encode(src), "codec_type", "codec_name", "sample_rate", "channels")
             if x["codec_type"] == "audio"][0]
        self.assertEqual((s["codec_name"], s["sample_rate"], s["channels"]), ("aac", "32000", 2))

    def test_mono_and_surround_audio_become_stereo(self):
        for layout in ("mono", "5.1"):
            with self.subTest(layout=layout):
                src = self.d / f"{layout}.mp4"
                try:
                    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=64x48:rate=10", "-f", "lavfi", "-i",
                           f"sine=frequency=440:sample_rate=48000,aformat=channel_layouts={layout}", "-t", 1, "-c:v", "libx264",
                           "-c:a", "aac", src)
                except RuntimeError:
                    continue
                s = [x for x in probe_json(self.encode(src), "codec_type", "channels") if x["codec_type"] == "audio"][0]
                self.assertEqual(s["channels"], 2)

    def test_extreme_aspect_ratios_are_letterboxed_not_stretched(self):
        for size in ("32x320", "640x32", "4x4"):
            with self.subTest(size=size):
                try:
                    src = make_video(self.d / f"a{size}.mp4", 1.0, size, audio=False)
                except RuntimeError:
                    continue
                s = probe_json(self.encode(src, "medium"), "width", "height")[0]
                self.assertEqual((s["width"], s["height"]), (360, 216))

    def test_anamorphic_source_is_corrected_with_sar(self):
        wide = make_video(self.d / "sar2.mp4", 1.0, "160x90", audio=False, vf="setsar=2/1")
        normal = make_video(self.d / "sar1.mp4", 1.0, "160x90", audio=False)

        def top_luma(p):
            out = subprocess.run([find_tool("ffmpeg"), "-v", "info", "-i", str(p), "-frames:v", "1", "-vf",
                                  "crop=360:20:0:0,signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "-"],
                                 capture_output=True, text=True).stderr
            return float(out.split("YAVG=")[1].split()[0])

        # SAR 2:1 は表示上かなり横長なので、上下に黒帯 (輝度 ≒ 16) が大きく出る。SAR 1:1 では上端まで絵がある
        self.assertLess(top_luma(self.encode(wide, "medium")), 25)
        self.assertGreater(top_luma(self.encode(normal, "medium")), 25)

    def test_encode_failure_is_wrapped_with_filename(self):
        src = make_video(self.d / "s.mp4", 1.0)
        with mock.patch("mkcia.video.run", side_effect=MkciaError("ffmpeg が失敗しました")):
            with self.assertRaises(MkciaError) as cm:
                video.encode_video(src, self.d / "o.mp4", "light")
        self.assertIn("s.mp4", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
