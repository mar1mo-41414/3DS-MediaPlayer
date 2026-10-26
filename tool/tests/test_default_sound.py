"""タイトル選択音が無いときに使う、既定の音声。"""

import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import ffmpeg, make_audio, make_template, requires_tools
from mkcia import assets
from mkcia.errors import MkciaError
from mkcia.pipeline import BuildOptions, build_cia
from mkcia.proc import REPO_ROOT, find_tool
from mkcia.validate import validate_audio


def max_volume_db(path: Path) -> float:
    """音声の最大音量 (dB)。無音なら -inf。"""
    err = subprocess.run([find_tool("ffmpeg"), "-v", "info", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.search(r"max_volume: (-?[\d.]+|-inf) dB", err)
    assert m, err[-300:]
    return float(m.group(1))


def duration(path: Path) -> float:
    return validate_audio(path)


@requires_tools
class DefaultSoundFileTest(unittest.TestCase):
    def test_the_file_is_shipped_and_valid(self):
        p = assets.DEFAULT_SELECT_SOUND
        self.assertTrue(p.is_file())
        d = duration(p)
        self.assertTrue(0.3 <= d <= assets.BANNER_AUDIO_MAX_SEC, d)
        self.assertLess(p.stat().st_size, 200_000)

    def test_it_is_audible_but_not_clipping(self):
        mv = max_volume_db(assets.DEFAULT_SELECT_SOUND)
        self.assertGreater(mv, -20)  # 聞こえる大きさ
        self.assertLess(mv, -1)  # 変換 (リサンプルなど) で歪まない余裕

    def test_it_is_inside_the_package(self):
        self.assertEqual(assets.DEFAULT_SELECT_SOUND.parent, Path(assets.__file__).parent)


@requires_tools
class BannerAudioTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def probe(self, p):
        out = subprocess.run([find_tool("ffprobe"), "-v", "error", "-show_entries", "stream=codec_name,sample_rate,channels",
                              "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip()
        return out

    def test_no_source_uses_the_default_sound(self):
        out = assets.make_banner_audio(None, self.d / "b.wav")
        self.assertEqual(self.probe(out), "pcm_s16le,32000,2")
        self.assertAlmostEqual(duration(out), 0.7, delta=0.1)
        self.assertGreater(max_volume_db(out), -25)

    def test_a_given_sound_is_used_instead(self):
        out = assets.make_banner_audio(make_audio(self.d / "s.wav", 1.5), self.d / "b.wav")
        self.assertAlmostEqual(duration(out), 1.5, delta=0.1)

    def test_a_silent_file_gives_a_silent_banner(self):
        """無音にしたいときは無音のファイルを置く (無いときは既定の音が鳴るので、これが無音にする方法)。"""
        silent = self.d / "silent.wav"
        ffmpeg("-f", "lavfi", "-i", "anullsrc=r=32000:cl=mono", "-t", 0.5, silent)
        out = assets.make_banner_audio(silent, self.d / "b.wav")
        self.assertLess(max_volume_db(out), -60)

    def test_a_long_given_sound_is_trimmed(self):
        out = assets.make_banner_audio(make_audio(self.d / "long.wav", 10), self.d / "b.wav")
        self.assertLessEqual(duration(out), 3.05)

    def test_a_missing_default_file_is_a_clear_error(self):
        with mock.patch.object(assets, "DEFAULT_SELECT_SOUND", self.d / "nope.wav"):
            with self.assertRaises(MkciaError) as cm:
                assets.make_banner_audio(None, self.d / "b.wav")
        self.assertIn("make-default-sound", str(cm.exception))


@requires_tools
class PipelineDefaultSoundTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)
        self.logs = []

    def tearDown(self):
        self._d.cleanup()

    def build(self, t):
        work = self.d / "work"
        build_cia(BuildOptions(Path(t), output_dir=self.d / "out", preset="light", compress_code=False, keep_work=work),
                  log=self.logs.append)
        return work / "banner.wav"

    def test_no_select_sound_uses_the_default_and_says_so(self):
        wav = self.build(make_template(self.d / "t", copy_sound=False))
        self.assertTrue(any("既定のタイトル選択音を使います" in l for l in self.logs))
        self.assertAlmostEqual(duration(wav), 0.7, delta=0.1)
        self.assertGreater(max_volume_db(wav), -25)

    def test_a_select_sound_in_the_template_wins(self):
        t = make_template(self.d / "t", copy_sound=False)
        make_audio(t / "select_sound.wav", 1.2)
        wav = self.build(t)
        self.assertFalse(any("既定のタイトル選択音" in l for l in self.logs))
        self.assertAlmostEqual(duration(wav), 1.2, delta=0.1)

    def test_a_silent_select_sound_is_respected(self):
        t = make_template(self.d / "t", copy_sound=False)
        ffmpeg("-f", "lavfi", "-i", "anullsrc=r=32000:cl=mono", "-t", 0.5, t / "select_sound.wav")
        wav = self.build(t)
        self.assertLess(max_volume_db(wav), -60)

    def test_a_broken_select_sound_is_an_error_not_a_silent_fallback_to_the_default(self):
        t = make_template(self.d / "t", copy_sound=False)
        (t / "select_sound.wav").write_bytes(b"not audio at all")
        with self.assertRaises(MkciaError) as cm:
            self.build(t)
        self.assertIn("select_sound.wav", str(cm.exception))


class RepositoryTemplatesTest(unittest.TestCase):
    """リポジトリ同梱のサンプルは、独自の音声を持たず、既定の音を使う。"""

    def test_the_example_has_no_select_sound(self):
        ex = REPO_ROOT / "template" / "example"
        if not ex.is_dir():
            self.skipTest("template/example が無い")
        self.assertEqual(sorted(p.name for p in ex.glob("select_sound.*")), [])
        self.assertTrue((ex / "meta.json").is_file())


if __name__ == "__main__":
    unittest.main()
