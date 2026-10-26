"""メディア (動画・画像・音声) の検証。壊れたもの・違う種類のものを渡したときの挙動。"""

import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import base_assets, cleanup_assets, ffmpeg, make_audio, make_image, make_video, requires_tools
from mkcia.errors import MkciaError
from mkcia.validate import (
    MAX_CIA_BYTES,
    check_size,
    estimate_cia_bytes,
    validate_audio,
    validate_image,
    validate_video,
)


def tearDownModule():
    cleanup_assets()


@requires_tools
class MediaValidationTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def err(self, fn, path):
        with self.assertRaises(MkciaError) as cm:
            fn(path)
        return str(cm.exception)

    # ---- 動画
    def test_valid_video(self):
        info = validate_video(make_video(self.d / "v.mp4", 1.0, "160x90", 10))
        self.assertEqual((info.width, info.height), (160, 90))
        self.assertTrue(info.has_audio)
        self.assertAlmostEqual(info.fps, 10, delta=0.5)
        self.assertAlmostEqual(info.duration, 1.0, delta=0.3)

    def test_video_without_audio_is_ok(self):
        self.assertFalse(validate_video(make_video(self.d / "v.mp4", audio=False)).has_audio)

    def test_video_garbage_inputs(self):
        garbage = {
            "text": b"hello world, I am not a video\n",
            "zeros": bytes(4096),
            "random": bytes(range(256)) * 16,
            "html": b"<html><body>404</body></html>",
            "json": b'{"a": 1}',
            "png-header-only": b"\x89PNG\r\n\x1a\n" + b"\x00" * 20,
        }
        for name, data in garbage.items():
            with self.subTest(name=name):
                p = self.d / f"{name}.mp4"
                p.write_bytes(data)
                m = self.err(validate_video, p)
                self.assertIn(p.name, m)  # どのファイルが悪いか分かる
                self.assertTrue("読めません" in m or "取得できません" in m, m)
                self.assertNotIn("moov atom", m)  # ffmpeg の生ログを見せない

    def test_truncated_video_does_not_crash(self):
        full = make_video(self.d / "full.mp4", 2.0)
        data = full.read_bytes()
        for cut in (10, 100, len(data) // 2):
            with self.subTest(cut=cut):
                p = self.d / f"cut{cut}.mp4"
                p.write_bytes(data[:cut])
                try:
                    validate_video(p)  # 通ってもよい (先頭だけ読める場合)
                except MkciaError as e:
                    self.assertIn(p.name, str(e))

    def test_audio_only_as_video(self):
        p = make_audio(self.d / "a.wav")
        m = self.err(validate_video, p)
        self.assertIn("映像がありません", m)

    def test_still_image_as_video(self):
        p = make_image(self.d / "i.png")
        m = self.err(validate_video, p)
        self.assertTrue("静止画" in m or "短すぎ" in m or "映像" in m, m)

    def test_too_short_video(self):
        m = self.err(validate_video, make_video(self.d / "s.mp4", 0.2))
        self.assertIn("短すぎ", m)

    def test_single_frame_video(self):
        p = self.d / "one.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc=size=64x64:rate=10", "-frames:v", 1, "-c:v", "libx264", p)
        self.assertIn("短すぎ", self.err(validate_video, p))

    def test_cover_art_only_is_not_a_video(self):
        a = make_audio(self.d / "a.wav")
        cover = make_image(self.d / "c.png")
        p = self.d / "song.mp3"
        try:
            ffmpeg("-i", a, "-i", cover, "-map", "0:a", "-map", "1:v", "-c:a", "libmp3lame", "-c:v", "mjpeg",
                   "-disposition:v", "attached_pic", p)
        except RuntimeError:
            self.skipTest("libmp3lame/mjpeg が無い ffmpeg")
        self.assertIn("映像がありません", self.err(validate_video, p))

    def test_odd_dimensions_and_extreme_aspect(self):
        for size in ("2x2", "1x100", "100x1", "161x91", "3840x2160"):
            with self.subTest(size=size):
                try:
                    p = make_video(self.d / f"{size}.mp4", 1.0, size, audio=False)
                except RuntimeError:
                    continue  # エンコーダが作れないサイズはテスト素材として不適
                info = validate_video(p)
                self.assertGreater(info.width, 0)

    def test_video_in_other_containers(self):
        base = make_video(self.d / "b.mp4", 1.0)
        for ext in (".mkv", ".mov", ".avi", ".webm"):
            with self.subTest(ext=ext):
                p = self.d / f"v{ext}"
                try:
                    ffmpeg("-i", base, "-c:v", "libvpx" if ext == ".webm" else "mpeg4", "-an" if ext == ".webm" else "-c:a",
                           *([] if ext == ".webm" else ["aac"]), p)
                except RuntimeError:
                    continue
                self.assertGreater(validate_video(p).width, 0)

    # ---- 画像
    def test_valid_images_in_many_formats(self):
        for ext in (".png", ".jpg", ".bmp", ".gif", ".webp"):
            with self.subTest(ext=ext):
                p = self.d / f"i{ext}"
                try:
                    make_image(p)
                except RuntimeError:
                    continue
                validate_image(p)

    def test_image_garbage(self):
        for name, data in {"text": b"not an image", "zeros": bytes(1000), "png-magic": b"\x89PNG\r\n\x1a\n" + b"x" * 50,
                           "jpeg-magic": b"\xff\xd8\xff" + b"x" * 50}.items():
            with self.subTest(name=name):
                p = self.d / f"{name}.png"
                p.write_bytes(data)
                m = self.err(validate_image, p)
                self.assertIn(p.name, m)

    def test_image_file_that_is_really_a_video_or_audio(self):
        # 動画を icon として渡しても「画像ストリームがある」ので通るが、音声は弾く
        self.err(validate_image, make_audio(self.d / "a.wav"))

    def test_image_with_wrong_extension_is_fine(self):
        p = make_image(self.d / "real.png")
        q = self.d / "actually_png.jpg"
        shutil.copyfile(p, q)
        validate_image(q)

    def test_one_pixel_image(self):
        p = self.d / "one.png"
        ffmpeg("-f", "lavfi", "-i", "color=c=red:s=2x2,scale=1:1", "-frames:v", 1, p)
        validate_image(p)

    def test_huge_image_dimensions_rejected(self):
        p = self.d / "huge.png"
        try:
            ffmpeg("-f", "lavfi", "-i", "color=c=black:size=17000x8", "-frames:v", 1, p)
        except RuntimeError:
            self.skipTest("巨大画像を作れない")
        self.assertIn("大きすぎ", self.err(validate_image, p))

    # ---- 音声
    def test_valid_audio_formats(self):
        for ext in (".wav", ".mp3", ".ogg", ".flac", ".m4a"):
            with self.subTest(ext=ext):
                p = self.d / f"a{ext}"
                try:
                    make_audio(p)
                except RuntimeError:
                    continue
                validate_audio(p)

    def test_audio_garbage(self):
        for name, data in {"text": b"nope", "zeros": bytes(2000), "riff-only": b"RIFF\x00\x00\x00\x00WAVE"}.items():
            with self.subTest(name=name):
                p = self.d / f"{name}.wav"
                p.write_bytes(data)
                self.assertIn(p.name, self.err(validate_audio, p))

    def test_video_without_audio_stream_as_sound(self):
        p = make_video(self.d / "silent.mp4", audio=False)
        self.assertIn("音声ストリームがありません", self.err(validate_audio, p))

    def test_image_as_sound(self):
        self.assertIn("音声ストリームがありません", self.err(validate_audio, make_image(self.d / "i.png")))

    def test_very_short_audio_is_ok(self):
        p = self.d / "tiny.wav"
        ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000", "-t", 0.01, p)
        validate_audio(p)

    def test_video_with_audio_as_sound_is_ok(self):
        validate_audio(base_assets() / "video.mp4")


class SizeEstimateTest(unittest.TestCase):
    def test_estimate(self):
        self.assertIsNone(estimate_cia_bytes(None, 400, 48))
        self.assertGreater(estimate_cia_bytes(60, 400, 48), 60 * 448 * 125)

    def test_ok_for_normal_lengths(self):
        for sec in (1, 60, 3600, 6 * 3600):
            with self.subTest(sec=sec):
                check_size(sec, 400, 48)

    def test_too_long_rejected(self):
        with self.assertRaises(MkciaError) as cm:
            check_size(30 * 3600, 400, 48)
        self.assertIn("4GB", str(cm.exception))

    def test_boundary(self):
        sec_ok = (MAX_CIA_BYTES - 3_000_000) / (448 * 125) - 1
        check_size(sec_ok, 400, 48)
        with self.assertRaises(MkciaError):
            check_size(sec_ok + 10, 400, 48)

    def test_unknown_duration_is_allowed(self):
        check_size(None, 400, 48)


if __name__ == "__main__":
    unittest.main()
