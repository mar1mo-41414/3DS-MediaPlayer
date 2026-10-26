"""icon / bottom が無いときに動画から作る機能 (埋め込み画像 → 指定秒数のフレーム) のテスト。"""

import contextlib
import io
import json
import math
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import GOOD_META, base_assets, cleanup_assets, ffmpeg, make_image, make_template, make_video, requires_tools
from mkcia import cli, extract, gui_model as g, video
from mkcia.errors import MkciaError
from mkcia.meta import parse_meta
from mkcia.pipeline import BuildOptions, build_cia
from mkcia.proc import find_tool
from mkcia.validate import VideoInfo, validate_image, validate_video


def tearDownModule():
    cleanup_assets()


def good(**kw):
    d = dict(GOOD_META)
    d.update(kw)
    return d


def png_size(path: Path):
    return validate_image(path)


class FrameAtMetaTest(unittest.TestCase):
    def test_default_is_none(self):
        self.assertIsNone(parse_meta(good()).frame_at)
        self.assertIsNone(parse_meta(good(frame_at=None)).frame_at)

    def test_valid_values(self):
        for v, want in ((0, 0.0), (5, 5.0), (12.5, 12.5), (1e-3, 1e-3), (86400, 86400.0)):
            with self.subTest(v=v):
                self.assertEqual(parse_meta(good(frame_at=v)).frame_at, want)

    def test_invalid_values(self):
        for v in ("5", "abc", True, False, [], {}, -1, -0.001, 86401, float("nan"), float("inf"), -float("inf")):
            with self.subTest(v=v), self.assertRaises(MkciaError) as cm:
                parse_meta(good(frame_at=v))
            self.assertIn("frame_at", str(cm.exception))

    def test_is_a_known_key(self):
        self.assertEqual(parse_meta(good(frame_at=3)).warnings, [])


class CliFrameAtTest(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            (Path(d) / "meta.json").write_text("{}")
            with mock.patch.object(cli, "build_cia") as b:
                try:
                    rc = cli.main([d, *argv])
                except SystemExit as e:
                    rc = e.code
        return rc, err.getvalue(), b

    def test_valid(self):
        # 全角の数字 ("５") も float() が読めるので受け付ける (日本語入力のまま打っても通るほうが親切)
        for text, want in (("0", 0.0), ("5", 5.0), ("12.5", 12.5), ("1e1", 10.0), ("５", 5.0)):
            with self.subTest(text=text):
                rc, _, b = self.run_cli("--frame-at", text)
                self.assertEqual(rc, 0)
                self.assertEqual(b.call_args[0][0].frame_at, want)

    def test_default_is_none(self):
        _, _, b = self.run_cli()
        self.assertIsNone(b.call_args[0][0].frame_at)

    def test_invalid(self):
        for text in ("abc", "-1", "nan", "inf", "-inf", "", "1,5", "5秒"):
            with self.subTest(text=text):
                rc, err, b = self.run_cli("--frame-at", text)
                self.assertEqual(rc, 2)
                b.assert_not_called()


class AutoTimeTest(unittest.TestCase):
    def test_values(self):
        self.assertEqual(extract.auto_frame_time(None), extract.FALLBACK_SEC)
        self.assertEqual(extract.auto_frame_time(0), 0)
        self.assertAlmostEqual(extract.auto_frame_time(100), 15.0)
        self.assertEqual(extract.auto_frame_time(10_000), extract.AUTO_MAX_SEC)

    def test_check_frame_at(self):
        info = VideoInfo(100, 100, 10.0, 10, True)
        extract.check_frame_at(None, info)
        extract.check_frame_at(0, info)
        extract.check_frame_at(9.99, info)
        for bad in (10.0, 10.1, 1000):
            with self.subTest(bad=bad), self.assertRaises(MkciaError) as cm:
                extract.check_frame_at(bad, info)
            self.assertIn("frame_at", str(cm.exception))
        extract.check_frame_at(1e6, VideoInfo(100, 100, None, 10, True))  # 長さ不明なら確認できないので通す


@requires_tools
class ExtractTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)
        self.base = make_video(self.d / "base.mp4", 4.0, "160x90", 10)
        self.cover = self.d / "cover.jpg"
        ffmpeg("-f", "lavfi", "-i", "color=c=red:size=200x200", "-frames:v", 1, self.cover)

    def tearDown(self):
        self._d.cleanup()

    def mkv_with(self, *attachments, name="v.mkv"):
        """attachments: (ファイル, 保存名, mime) の並びを添付した mkv を作る。"""
        args = ["-i", self.base, "-c", "copy"]
        for path, fname, mime in attachments:
            args += ["-attach", path]
        for i, (_, fname, mime) in enumerate(attachments):
            args += [f"-metadata:s:t:{i}", f"mimetype={mime}", f"-metadata:s:t:{i}", f"filename={fname}"]
        out = self.d / name
        ffmpeg(*args, out)
        return out

    # ---- 埋め込み画像の検出
    def test_no_embedded_image(self):
        self.assertEqual(extract.embedded_image_indexes(self.base), [])
        self.assertIsNone(extract.extract_embedded(self.base, self.d))

    def test_mkv_attachment_is_found_and_extracted(self):
        v = self.mkv_with((self.cover, "cover.jpg", "image/jpeg"))
        idx = extract.embedded_image_indexes(v)
        self.assertEqual(len(idx), 1)
        out = extract.extract_embedded(v, self.d)
        self.assertEqual(png_size(out), (200, 200))

    def test_mkv_attachment_with_any_name_counts(self):
        v = self.mkv_with((self.cover, "thumb.jpg", "image/jpeg"))
        self.assertEqual(png_size(extract.extract_embedded(v, self.d)), (200, 200))

    def test_mp4_cover_art_is_found(self):
        v = self.d / "c.mp4"
        ffmpeg("-i", self.cover, "-i", self.base, "-map", "0", "-map", "1", "-c", "copy", "-disposition:v:0", "attached_pic", v)
        self.assertEqual(png_size(extract.extract_embedded(v, self.d)), (200, 200))

    def test_cover_named_file_is_preferred(self):
        other = self.d / "other.png"
        ffmpeg("-f", "lavfi", "-i", "color=c=blue:size=300x100", "-frames:v", 1, other)
        v = self.mkv_with((other, "thumb.png", "image/png"), (self.cover, "cover.jpg", "image/jpeg"))
        out = extract.extract_embedded(v, self.d)
        self.assertEqual(png_size(out), (200, 200))  # cover.jpg (200x200) が先、thumb.png (300x100) ではない

    def test_broken_embedded_image_is_ignored(self):
        junk = self.d / "junk.jpg"
        junk.write_bytes(b"this is not a jpeg at all" * 20)
        v = self.mkv_with((junk, "cover.jpg", "image/jpeg"))
        self.assertIsNone(extract.extract_embedded(v, self.d))  # 例外にならず、フレーム抽出に回せる

    def test_non_image_attachment_is_not_an_embedded_image(self):
        font = self.d / "font.ttf"
        font.write_bytes(b"\x00\x01\x00\x00" + bytes(200))
        v = self.mkv_with((font, "font.ttf", "application/x-truetype-font"))
        self.assertEqual(extract.embedded_image_indexes(v), [])

    # ---- フレーム抽出
    def test_extract_frame_size_and_time(self):
        a = extract.extract_frame(self.base, 0.5, self.d / "a.png")
        b = extract.extract_frame(self.base, 3.0, self.d / "b.png")
        self.assertEqual(png_size(a), (160, 90))
        self.assertNotEqual(a.read_bytes(), b.read_bytes())  # 秒数を変えると違う場面 (時計が進む)

    def test_extract_frame_at_zero(self):
        self.assertEqual(png_size(extract.extract_frame(self.base, 0, self.d / "z.png")), (160, 90))

    def test_extract_frame_beyond_the_end_fails_clearly(self):
        with self.assertRaises(MkciaError) as cm:
            extract.extract_frame(self.base, 100, self.d / "x.png")
        self.assertIn("100", str(cm.exception))

    def test_non_square_pixels_are_corrected(self):
        wide = make_video(self.d / "sar.mp4", 2.0, "160x90", audio=False, vf="setsar=2/1")
        self.assertEqual(png_size(extract.extract_frame(wide, 0.5, self.d / "w.png")), (320, 90))

    def test_cover_art_is_not_mistaken_for_the_video(self):
        # 注: ffmpeg で作れる mp4 / mkv ではカバー画像は必ず後ろの番号になるので、`0:v:0` でも先頭は動画のまま。
        # `0:V:0` (カバーを除く) は、カバーが先に来る特殊なコンテナへの保険で、ここでは再現できない。
        v = self.d / "c.mp4"
        ffmpeg("-i", self.cover, "-i", self.base, "-map", "0", "-map", "1", "-c", "copy", "-disposition:v:0", "attached_pic", v)
        self.assertEqual(png_size(extract.extract_frame(v, 0.5, self.d / "f.png")), (160, 90))  # 200x200 のカバーではない
        enc = video.encode_video(v, self.d / "enc.mp4", "light")
        out = subprocess.run([find_tool("ffprobe"), "-v", "error", "-select_streams", "v", "-show_entries",
                              "stream=width,height", "-of", "csv=p=0", str(enc)], capture_output=True, text=True).stdout.split()
        self.assertEqual(out, ["320,192"])  # 動画が 1 本だけ。カバーを動画として変換していない

    # ---- 元画像の選び方
    def info(self, v):
        return validate_video(v)

    def test_source_prefers_embedded_when_frame_at_is_not_given(self):
        v = self.mkv_with((self.cover, "cover.jpg", "image/jpeg"))
        path, how = extract.source_image(v, self.info(v), None, self.d)
        self.assertEqual(png_size(path), (200, 200))
        self.assertIn("埋め込み", how)

    def test_explicit_frame_at_beats_the_embedded_image(self):
        v = self.mkv_with((self.cover, "cover.jpg", "image/jpeg"))
        path, how = extract.source_image(v, self.info(v), 1.0, self.d)
        self.assertEqual(png_size(path), (160, 90))
        self.assertIn("1.0 秒", how)
        self.assertNotIn("自動", how)

    def test_falls_back_to_an_automatic_frame(self):
        path, how = extract.source_image(self.base, self.info(self.base), None, self.d)
        self.assertEqual(png_size(path), (160, 90))
        self.assertIn("自動", how)
        self.assertIn("0.6 秒", how)  # 4 秒の 15%

    def test_frame_at_beyond_the_end_is_an_error(self):
        with self.assertRaises(MkciaError):
            extract.source_image(self.base, self.info(self.base), 4.0, self.d)


@requires_tools
class PipelineGenerationTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)
        self.logs = []

    def tearDown(self):
        self._d.cleanup()

    def build(self, t, **kw):
        kw.setdefault("compress_code", False)
        kw.setdefault("preset", "light")
        work = self.d / "work"
        kw.setdefault("keep_work", work)
        return build_cia(BuildOptions(Path(t), output_dir=self.d / "out", **kw), log=self.logs.append)

    def work(self, name):
        return self.d / "work" / name

    def log_text(self):
        return "\n".join(self.logs)

    def test_neither_icon_nor_bottom(self):
        t = make_template(self.d / "t", skip=("icon.png", "bottom.png"))
        out = self.build(t)
        self.assertTrue(out.is_file())
        self.assertIn("icon / bottom が無いので", self.log_text())
        self.assertTrue(self.work("frame.png").is_file())
        self.assertEqual(png_size(self.work("icon48.png")), (48, 48))  # 中央を正方形に切り抜いて 48x48
        self.assertEqual(png_size(self.work("bottom320.png")), (320, 240))
        self.assertEqual(png_size(self.work("banner.png")), (256, 128))

    def test_only_the_icon_is_missing(self):
        t = make_template(self.d / "t", skip=("icon.png",))
        self.build(t)
        text = self.log_text()
        self.assertIn("icon が無いので", text)
        self.assertNotIn("bottom が無い", text)
        self.assertNotIn("icon / bottom", text)
        self.assertEqual(png_size(self.work("icon48.png")), (48, 48))

    def test_only_the_bottom_is_missing(self):
        t = make_template(self.d / "t", skip=("bottom.png",))
        self.build(t)
        text = self.log_text()
        self.assertIn("bottom が無いので", text)
        self.assertNotIn("icon が無い", text)
        self.assertEqual(png_size(self.work("bottom320.png")), (320, 240))

    def test_existing_images_are_never_replaced(self):
        t = make_template(self.d / "t")
        self.build(t)
        self.assertFalse(self.work("frame.png").exists())
        self.assertNotIn("動画から", self.log_text())
        self.assertNotIn("無いので", self.log_text())

    def test_the_provided_image_is_used_not_a_frame(self):
        """あるほうの画像は、動画のフレームではなく自分の画像から作る (アイコンの元画像が赤一色なら、できたアイコンも赤)。"""
        t = make_template(self.d / "t", skip=("icon.png",))
        ffmpeg("-f", "lavfi", "-i", "color=c=red:size=64x64", "-frames:v", 1, t / "icon.png")
        self.build(t)
        px = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-i", str(self.work("icon48.png")), "-vf", "scale=1:1,format=rgb24",
                             "-f", "rawvideo", "-"], capture_output=True).stdout
        self.assertGreater(px[0], 200)  # R
        self.assertLess(px[1], 60)  # G

    def test_meta_frame_at_is_used(self):
        t = make_template(self.d / "t", {"frame_at": 0.5}, skip=("icon.png", "bottom.png"))
        self.build(t)
        self.assertIn("0.5 秒のフレーム", self.log_text())

    def test_option_beats_meta(self):
        t = make_template(self.d / "t", {"frame_at": 0.5}, skip=("icon.png", "bottom.png"))
        self.build(t, frame_at=0.8)
        self.assertIn("0.8 秒のフレーム", self.log_text())
        self.assertNotIn("0.5 秒", self.log_text())

    def test_automatic_position_when_nothing_is_given(self):
        t = make_template(self.d / "t", skip=("icon.png", "bottom.png"))
        self.build(t)
        self.assertIn("(自動)", self.log_text())

    def test_frame_at_beyond_the_end_fails_before_encoding(self):
        t = make_template(self.d / "t", {"frame_at": 500}, skip=("icon.png", "bottom.png"))
        with mock.patch("mkcia.video.encode_video", side_effect=AssertionError("エンコードに進んではいけない")):
            with self.assertRaises(MkciaError) as cm:
                self.build(t)
        self.assertIn("frame_at", str(cm.exception))

    def test_frame_at_is_not_checked_when_both_images_exist(self):
        t = make_template(self.d / "t", {"frame_at": 500})
        self.build(t)
        self.assertIn("frame_at は使われません", self.log_text())

    def test_embedded_image_in_the_template_video(self):
        t = make_template(self.d / "t", skip=("icon.png", "bottom.png", "video.mp4"))
        cover = self.d / "cover.jpg"
        ffmpeg("-f", "lavfi", "-i", "color=c=green:size=100x100", "-frames:v", 1, cover)
        ffmpeg("-i", base_assets() / "video.mp4", "-c", "copy", "-attach", cover, "-metadata:s:t:0", "mimetype=image/jpeg",
               "-metadata:s:t:0", "filename=cover.jpg", t / "video.mkv")
        self.build(t)
        self.assertIn("埋め込み画像", self.log_text())
        self.assertFalse(self.work("frame.png").exists())

    def test_explicit_frame_at_overrides_the_embedded_image(self):
        t = make_template(self.d / "t", {"frame_at": 0.3}, skip=("icon.png", "bottom.png", "video.mp4"))
        cover = self.d / "cover.jpg"
        ffmpeg("-f", "lavfi", "-i", "color=c=green:size=100x100", "-frames:v", 1, cover)
        ffmpeg("-i", base_assets() / "video.mp4", "-c", "copy", "-attach", cover, "-metadata:s:t:0", "mimetype=image/jpeg",
               "-metadata:s:t:0", "filename=cover.jpg", t / "video.mkv")
        self.build(t)
        self.assertIn("0.3 秒のフレーム", self.log_text())
        self.assertNotIn("埋め込み", self.log_text())

    def test_a_directory_named_icon_is_still_an_error_not_silently_replaced(self):
        t = make_template(self.d / "t", skip=("icon.png",))
        (t / "icon.png").mkdir()
        with self.assertRaises(MkciaError) as cm:
            self.build(t)
        self.assertIn("icon.png", str(cm.exception))

    def test_a_broken_icon_is_an_error_not_silently_replaced(self):
        t = make_template(self.d / "t")
        (t / "icon.png").write_bytes(b"broken")
        with self.assertRaises(MkciaError) as cm:
            self.build(t)
        self.assertIn("icon.png", str(cm.exception))

    def test_a_template_with_only_video_and_meta_builds(self):
        t = make_template(self.d / "t", skip=("icon.png", "bottom.png", "select_sound.wav"))
        out = self.build(t)
        self.assertTrue(out.is_file())


@requires_tools
class RealWorldVideoTest(unittest.TestCase):
    def test_unusual_video_shapes_still_yield_images(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for name, size in (("tall", "64x320"), ("wide", "640x64"), ("tiny", "16x16")):
                with self.subTest(shape=name):
                    v = make_video(d / f"{name}.mp4", 2.0, size, audio=False)
                    path, _ = extract.source_image(v, validate_video(v), None, d)
                    w, h = png_size(path)
                    self.assertGreater(w * h, 0)
                    icon = d / f"{name}_icon.png"
                    from mkcia import assets

                    assets.make_icon(path, icon, crop_square=True)
                    self.assertEqual(png_size(icon), (48, 48))


@requires_tools
class IconCropTest(unittest.TestCase):
    def pixel(self, path, x, y):
        out = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-i", str(path), "-vf", f"crop=1:1:{x}:{y},format=rgb24",
                              "-f", "rawvideo", "-"], capture_output=True).stdout
        return tuple(out[:3])

    def test_wide_source_is_center_cropped_not_squashed(self):
        """左右が青・中央が赤の横長画像から作ったアイコンは、中央 (赤) だけになる。縮めて潰すと両端が青く残る。"""
        from mkcia import assets

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ffmpeg("-f", "lavfi", "-i", "color=c=blue:size=300x100", "-vf",
                   "drawbox=x=100:y=0:w=100:h=100:color=red:t=fill", "-frames:v", 1, d / "wide.png")
            icon = assets.make_icon(d / "wide.png", d / "icon.png", crop_square=True)
            for x in (2, 24, 45):
                r, g_, b = self.pixel(icon, x, 24)
                self.assertGreater(r, 200, f"x={x}")
                self.assertLess(b, 60, f"x={x}")  # どこにも青が混ざらない

    def test_default_icon_keeps_the_whole_image_with_margins(self):
        """ユーザーが用意したアイコンは、従来どおり全体を収める (切り抜かない)。両端の青も残り、上下は透明の余白。"""
        from mkcia import assets

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ffmpeg("-f", "lavfi", "-i", "color=c=blue:size=300x100", "-frames:v", 1, d / "wide.png")
            icon = assets.make_icon(d / "wide.png", d / "icon.png")
            self.assertEqual(png_size(icon), (48, 48))
            self.assertGreater(self.pixel(icon, 2, 24)[2], 200)  # 左端も青


class FormFrameAtTest(unittest.TestCase):
    def test_form_round_trip_and_clearing(self):
        with tempfile.TemporaryDirectory() as d:
            t = g.TemplateDir.create("x", Path(d))
            form, _ = t.load_form()
            form.publisher = "p"
            form.frame_at = "12.5"
            t.save_form(form)
            self.assertEqual(json.loads((t.path / "meta.json").read_text(encoding="utf-8"))["frame_at"], 12.5)
            self.assertEqual(t.load_form()[0].frame_at, "12.5")
            form.frame_at = " "
            t.save_form(form)
            self.assertNotIn("frame_at", json.loads((t.path / "meta.json").read_text(encoding="utf-8")))

    def test_integers_are_shown_without_a_decimal_point(self):
        self.assertEqual(g._fmt_seconds(5), "5")
        self.assertEqual(g._fmt_seconds(5.0), "5")
        self.assertEqual(g._fmt_seconds(0.25), "0.25")
        for bad in (None, True, "5", [1]):
            self.assertEqual(g._fmt_seconds(bad), "")

    def test_invalid_input_is_reported_with_the_field_name(self):
        for text in ("abc", "-1", "nan", "inf", "99999999"):
            with self.subTest(text=text), self.assertRaises(MkciaError) as cm:
                g.validate_form(g.TemplateForm(title="t", publisher="p", title_id="000400000FF3A000", frame_at=text))
            self.assertIn("frame_at", str(cm.exception))

    def test_unset_icon_and_bottom_explain_what_happens(self):
        with tempfile.TemporaryDirectory() as d:
            t = g.TemplateDir.create("x", Path(d))
            self.assertIn("動画から", t.describe_asset("icon"))
            self.assertIn("動画から", t.describe_asset("bottom"))
            self.assertIn("既定", t.describe_asset("select_sound"))  # 無ければ既定の音を使う


if __name__ == "__main__":
    unittest.main()
