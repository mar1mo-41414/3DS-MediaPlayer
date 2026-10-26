"""GUI のロジック層 (Tk 無しでテストできる部分)。"""

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import GOOD_META, base_assets, cleanup_assets, make_audio, make_image, make_template, make_video, requires_tools
from mkcia import gui_model as g
from mkcia import video
from mkcia.errors import MkciaError
from mkcia.meta import load_meta, parse_meta
from mkcia.pipeline import BuildOptions
from mkcia.proc import Cancelled, set_cancel_event


def tearDownModule():
    set_cancel_event(None)
    cleanup_assets()


def good_form(**kw):
    f = g.TemplateForm(title="T", publisher="P", title_id="000400000FF3A000", version="1.0.0")
    for k, v in kw.items():
        setattr(f, k, v)
    return f


class PresetChoicesTest(unittest.TestCase):
    def test_covers_all_presets_lightest_first(self):
        names = [n for n, _ in g.preset_choices()]
        self.assertEqual(sorted(names), sorted(video.PRESETS))
        self.assertEqual(names[:4], ["light", "medium", "high", "standard"])

    def test_labels_describe_the_preset(self):
        for name, label in g.preset_choices():
            p = video.PRESETS[name]
            self.assertIn(name, label)
            self.assertIn(f"{p.width}x{p.height}", label)
            self.assertIn(f"{p.fps}fps", label)

    def test_default_preset_is_marked(self):
        label = dict(g.preset_choices())[video.DEFAULT_PRESET]
        self.assertIn("既定", label)


class FormTest(unittest.TestCase):
    def test_to_meta_dict_omits_empty_optionals(self):
        d = good_form().to_meta_dict()
        self.assertEqual(set(d), {"title", "publisher", "title_id", "version", "loop", "volume"})

    def test_to_meta_dict_includes_filled_optionals_and_strips(self):
        d = good_form(title="  T  ", long_title=" Long ", product_code="CTR-P-ABCD", preset=" light ", output=" Out ").to_meta_dict()
        self.assertEqual((d["title"], d["long_title"], d["product_code"], d["preset"], d["output"]),
                         ("T", "Long", "CTR-P-ABCD", "light", "Out"))

    def test_volume_is_rounded_and_bool_is_real(self):
        d = good_form(volume=0.123456789, loop=True).to_meta_dict()
        self.assertEqual((d["volume"], d["loop"]), (0.123, True))

    def test_validate_form_ok(self):
        m = g.validate_form(good_form(preset="light", output="x"))
        self.assertEqual((m.preset, m.output), ("light", "x.cia"))

    def test_validate_form_errors_name_the_field(self):
        cases = [
            ({"title": ""}, "title"), ({"publisher": ""}, "publisher"), ({"title_id": "123"}, "title_id"),
            ({"version": "1"}, "version"), ({"volume": 2.0}, "volume"), ({"title": "x" * 65}, "title"),
            ({"product_code": "bad"}, "product_code"), ({"output": "a/b"}, "output"),
        ]
        for kw, key in cases:
            with self.subTest(kw=kw), self.assertRaises(MkciaError) as cm:
                g.validate_form(good_form(**kw))
            self.assertIn(key, str(cm.exception))

    def test_validate_form_unknown_preset(self):
        with self.assertRaises(MkciaError) as cm:
            g.validate_form(good_form(preset="ultra"))
        self.assertIn("ultra", str(cm.exception))


class TitleIdTest(unittest.TestCase):
    def test_suggested_id_is_valid_and_deterministic(self):
        for name in ("a", "My_Movie", "日本語", "x" * 100, "with space"):
            with self.subTest(name=name):
                tid = g.suggest_title_id(name)
                self.assertEqual(parse_meta(dict(GOOD_META, title_id=tid)).title_id, tid)
                self.assertEqual(tid, g.suggest_title_id(name))
                self.assertTrue(0x0F0000 <= parse_meta(dict(GOOD_META, title_id=tid)).unique_id <= 0x0FFFFF)

    def test_avoids_taken_ids(self):
        first = g.suggest_title_id("same")
        second = g.suggest_title_id("same", taken=[first])
        self.assertNotEqual(first, second)
        self.assertNotEqual(g.suggest_title_id("same", taken=[first, second]), second)

    def test_taken_comparison_is_case_insensitive(self):
        first = g.suggest_title_id("n")
        self.assertNotEqual(g.suggest_title_id("n", taken=[first.lower()]), first)


class TemplateNameTest(unittest.TestCase):
    def test_valid(self):
        for n in ("My_Movie", "日本語 名前", "a-b.c", " padded ", "123", "A" * 100):
            with self.subTest(n=n):
                self.assertEqual(g.check_template_name(n), n.strip())

    def test_invalid(self):
        for n in ("", "   ", ".", "..", ".hidden", "a/b", "a\\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a|b", "a\nb",
                  "a\x00b", "あ" * 50):
            with self.subTest(n=n), self.assertRaises(MkciaError):
                g.check_template_name(n)

    def test_existing_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "taken").mkdir()
            with self.assertRaises(MkciaError) as cm:
                g.check_template_name("taken", Path(d))
            self.assertIn("既に", str(cm.exception))


class TemplateDirTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.root = Path(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def test_list_templates(self):
        self.assertEqual(g.list_templates(self.root / "nope"), [])
        (self.root / "b").mkdir()
        (self.root / "b" / "meta.json").write_text("{}")
        (self.root / "a").mkdir()
        (self.root / "a" / "meta.json").write_text("{}")
        (self.root / "junk").mkdir()
        (self.root / "file.txt").write_text("x")
        self.assertEqual(g.list_templates(self.root), ["a", "b"])

    def test_create(self):
        t = g.TemplateDir.create("My Movie", self.root)
        self.assertEqual(t.name, "My Movie")
        form, warnings = t.load_form()
        self.assertEqual((form.title, warnings), ("My Movie", []))
        self.assertEqual(parse_meta(dict(GOOD_META, title_id=form.title_id)).title_id, form.title_id)
        self.assertEqual(g.list_templates(self.root), ["My Movie"])

    def test_create_gives_distinct_title_ids(self):
        a = g.TemplateDir.create("same", self.root).load_form()[0].title_id
        shutil.rmtree(self.root / "same")
        g.TemplateDir.create("other", self.root)
        b = g.TemplateDir.create("same", self.root).load_form()[0].title_id
        self.assertNotEqual(g.TemplateDir(self.root / "other").load_form()[0].title_id, b)
        self.assertEqual(a[:8], b[:8])

    def test_create_rejects_bad_and_duplicate_names(self):
        g.TemplateDir.create("dup", self.root)
        for n in ("dup", "", "a/b", ".."):
            with self.subTest(n=n), self.assertRaises(MkciaError):
                g.TemplateDir.create(n, self.root)

    def test_create_in_unwritable_place(self):
        (self.root / "file").write_text("x")
        with self.assertRaises(MkciaError):
            g.TemplateDir.create("x", self.root / "file")

    def test_load_form_defaults_when_missing_or_broken(self):
        d = self.root / "t"
        d.mkdir()
        form, w = g.TemplateDir(d).load_form()
        self.assertEqual((form.title, form.version, form.volume, w), ("", "1.0.0", 1.0, []))
        for text, frag in (("{broken", "壊れて"), ("[1,2]", "オブジェクト"), ("", "壊れて")):
            with self.subTest(text=text):
                (d / "meta.json").write_text(text)
                form, w = g.TemplateDir(d).load_form()
                self.assertEqual(form.version, "1.0.0")
                self.assertTrue(any(frag in x for x in w), w)

    def test_load_form_not_utf8(self):
        d = self.root / "t"
        d.mkdir()
        (d / "meta.json").write_bytes('{"title": "日本"}'.encode("shift_jis"))
        form, w = g.TemplateDir(d).load_form()
        self.assertTrue(w)

    def test_load_form_coerces_wrong_types(self):
        d = self.root / "t"
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"title": 123, "loop": "yes", "volume": "loud", "preset": None,
                                                 "publisher": ["a"], "version": 1.5}))
        form, _ = g.TemplateDir(d).load_form()
        self.assertEqual((form.title, form.loop, form.volume, form.preset), ("123", False, 1.0, ""))

    def test_load_form_accepts_bom(self):
        d = self.root / "t"
        d.mkdir()
        (d / "meta.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"title": "BOM"}).encode())
        self.assertEqual(g.TemplateDir(d).load_form()[0].title, "BOM")

    def test_save_form_round_trips_through_the_real_loader(self):
        t = g.TemplateDir.create("rt", self.root)
        form = good_form(title="日本語 Title", long_title="Long", preset="light", output="Out Name", loop=True, volume=0.4)
        t.save_form(form)
        meta = load_meta(t.path / "meta.json")
        self.assertEqual((meta.title, meta.preset, meta.output, meta.loop, meta.volume),
                         ("日本語 Title", "light", "Out Name.cia", True, 0.4))
        self.assertEqual(t.load_form()[0].title, "日本語 Title")

    def test_save_form_invalid_leaves_file_untouched(self):
        t = g.TemplateDir.create("keep", self.root)
        before = (t.path / "meta.json").read_text()
        with self.assertRaises(MkciaError):
            t.save_form(good_form(volume=9))
        self.assertEqual((t.path / "meta.json").read_text(), before)

    def test_save_form_preserves_unknown_keys_and_clears_emptied_optionals(self):
        t = g.TemplateDir.create("pk", self.root)
        raw = json.loads((t.path / "meta.json").read_text())
        raw.update(custom_note="keep me", preset="light", output="Old")
        (t.path / "meta.json").write_text(json.dumps(raw))
        t.save_form(good_form(preset="", output=""))
        after = json.loads((t.path / "meta.json").read_text())
        self.assertEqual(after["custom_note"], "keep me")
        self.assertNotIn("preset", after)
        self.assertNotIn("output", after)

    def test_save_form_leaves_no_temp_files_and_normal_permissions(self):
        t = g.TemplateDir.create("perm", self.root)
        old = os.umask(0o022)
        try:
            t.save_form(good_form())
        finally:
            os.umask(old)
        self.assertEqual([p.name for p in t.path.iterdir()], ["meta.json"])
        self.assertEqual((t.path / "meta.json").stat().st_mode & 0o777, 0o644)

    def test_save_form_recovers_from_a_broken_existing_file(self):
        t = g.TemplateDir.create("broken", self.root)
        (t.path / "meta.json").write_text("{not json")
        t.save_form(good_form())
        self.assertEqual(load_meta(t.path / "meta.json").title, "T")

    def test_title_id_conflicts(self):
        a = g.TemplateDir.create("a", self.root)
        b = g.TemplateDir.create("b", self.root)
        tid = a.load_form()[0].title_id
        self.assertEqual(g.title_id_conflicts(tid, self.root), ["a"])
        self.assertEqual(g.title_id_conflicts(tid, self.root, exclude="a"), [])
        self.assertEqual(g.title_id_conflicts(tid.lower(), self.root), ["a"])
        self.assertEqual(g.title_id_conflicts("", self.root), [])
        b_form = b.load_form()[0]
        b_form.title_id = tid
        b.save_form(b_form, _skip_validation=True)
        self.assertEqual(g.title_id_conflicts(tid, self.root), ["a", "b"])


@requires_tools
class AssetTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.root = Path(self._d.name)
        self.src = self.root / "src"
        self.src.mkdir()
        self.t = g.TemplateDir.create("tpl", self.root / "tpls")

    def tearDown(self):
        self._d.cleanup()

    def test_assets_table(self):
        self.assertEqual([a.stem for a in g.ASSETS], ["video", "icon", "bottom", "select_sound", "banner"])
        self.assertEqual([a.required for a in g.ASSETS], [True, False, False, False, False])  # 必須は動画だけ

    def test_unset_assets(self):
        self.assertIsNone(self.t.find_asset("video"))
        self.assertIn("必須", self.t.describe_asset("video"))
        self.assertEqual(self.t.describe_asset("select_sound"), "未設定")

    def test_set_each_kind(self):
        for stem, maker, name in (("video", make_video, "a.mp4"), ("icon", make_image, "b.png"), ("bottom", make_image, "c.png"),
                                  ("select_sound", make_audio, "d.wav"), ("banner", make_image, "e.png")):
            with self.subTest(stem=stem):
                dest = self.t.set_asset(stem, maker(self.src / name))
                self.assertEqual(dest, self.t.path / (stem + Path(name).suffix))
                self.assertEqual(self.t.find_asset(stem), dest)
                self.assertTrue(dest.stat().st_size > 0)

    def test_replacing_with_another_extension_removes_the_old_one(self):
        self.t.set_asset("video", make_video(self.src / "a.mp4"))
        mkv = self.src / "b.mkv"
        shutil.copyfile(base_assets() / "video.mp4", mkv)
        self.t.set_asset("video", mkv)
        self.assertEqual([p.name for p in self.t.asset_candidates("video")], ["video.mkv"])
        self.assertEqual(self.t.find_asset("video").name, "video.mkv")

    def test_uppercase_extension_is_normalized(self):
        up = self.src / "PHOTO.PNG"
        make_image(up)
        self.assertEqual(self.t.set_asset("icon", up).name, "icon.png")

    def test_names_with_spaces_and_unicode(self):
        p = make_video(self.src / "日本語 の 夜 (1).mp4")
        self.assertEqual(self.t.set_asset("video", p).name, "video.mp4")

    def test_same_file_is_a_noop(self):
        dest = self.t.set_asset("icon", make_image(self.src / "i.png"))
        mtime = dest.stat().st_mtime_ns
        self.assertEqual(self.t.set_asset("icon", dest), dest)
        self.assertEqual(dest.stat().st_mtime_ns, mtime)

    def test_symlink_source_is_copied_as_a_real_file(self):
        link = self.src / "link.png"
        link.symlink_to(make_image(self.src / "real.png"))
        dest = self.t.set_asset("icon", link)
        self.assertFalse(dest.is_symlink())

    def test_bad_sources_leave_the_template_untouched(self):
        good = self.t.set_asset("icon", make_image(self.src / "good.png"))
        before = good.read_bytes()
        bad_cases = {
            "missing": self.src / "nope.png",
            "dir": self.src,
        }
        for label, p in bad_cases.items():
            with self.subTest(label=label), self.assertRaises(MkciaError):
                self.t.set_asset("icon", p)
        empty = self.src / "empty.png"
        empty.write_bytes(b"")
        corrupt = self.src / "corrupt.png"
        corrupt.write_bytes(b"not an image")
        wrongext = make_audio(self.src / "a.wav")
        for p in (empty, corrupt, wrongext):
            with self.subTest(p=p.name), self.assertRaises(MkciaError):
                self.t.set_asset("icon", p)
        self.assertEqual(good.read_bytes(), before)
        self.assertEqual([p.name for p in self.t.path.iterdir() if p.name != "meta.json"], ["icon.png"])

    def test_extension_must_match_the_kind(self):
        with self.assertRaises(MkciaError) as cm:
            self.t.set_asset("video", make_image(self.src / "i.png"))
        self.assertIn(".png", str(cm.exception))
        with self.assertRaises(MkciaError):
            self.t.set_asset("icon", make_video(self.src / "v.mp4"))
        noext = self.src / "noext"
        shutil.copyfile(base_assets() / "icon.png", noext)
        with self.assertRaises(MkciaError):
            self.t.set_asset("icon", noext)

    def test_corrupt_media_of_right_extension_is_rejected(self):
        for stem, name in (("video", "x.mp4"), ("select_sound", "x.wav")):
            p = self.src / name
            p.write_bytes(b"garbage garbage garbage")
            with self.subTest(stem=stem), self.assertRaises(MkciaError):
                self.t.set_asset(stem, p)

    def test_remove_optional_and_required(self):
        self.t.set_asset("select_sound", make_audio(self.src / "s.wav"))
        self.t.set_asset("banner", make_image(self.src / "b.png"))
        self.t.remove_asset("select_sound")
        self.t.remove_asset("banner")
        self.assertIsNone(self.t.find_asset("select_sound"))
        self.t.remove_asset("select_sound")  # 無くても失敗しない
        self.t.set_asset("video", make_video(self.src / "v.mp4"))
        with self.assertRaises(MkciaError):  # 動画は必須なので削除できない
            self.t.remove_asset("video")
        self.assertIsNotNone(self.t.find_asset("video"))
        self.t.set_asset("icon", make_image(self.src / "i.png"))  # icon / bottom は任意 (無ければ動画から作る)
        self.t.remove_asset("icon")
        self.assertIsNone(self.t.find_asset("icon"))

    def test_remove_removes_every_extension(self):
        self.t.set_asset("select_sound", make_audio(self.src / "s.wav"))
        shutil.copyfile(self.src / "s.wav", self.t.path / "select_sound.mp3")
        self.t.remove_asset("select_sound")
        self.assertEqual(self.t.asset_candidates("select_sound"), [])

    def test_describe_asset(self):
        self.t.set_asset("video", make_video(self.src / "v.mp4", 2.0, "160x90"))
        self.t.set_asset("icon", make_image(self.src / "i.png", "64x48"))
        self.t.set_asset("select_sound", make_audio(self.src / "s.wav", 1.0))
        self.assertIn("160x90", self.t.describe_asset("video"))
        self.assertIn("音声あり", self.t.describe_asset("video"))
        self.assertIn("64x48", self.t.describe_asset("icon"))
        self.assertIn("1.0秒", self.t.describe_asset("select_sound"))

    def test_describe_asset_of_a_broken_file_does_not_raise(self):
        (self.t.path / "icon.png").write_bytes(b"broken")
        self.assertIn("問題あり", self.t.describe_asset("icon"))

    def test_thumbnails(self):
        png = g.make_thumbnail(make_image(self.src / "i.png", "200x100"), 50)
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertTrue(g.make_thumbnail(make_video(self.src / "v.mp4"), 50).startswith(b"\x89PNG"))
        bad = self.src / "bad.png"
        bad.write_bytes(b"nope")
        self.assertIsNone(g.make_thumbnail(bad))
        self.assertIsNone(g.make_thumbnail(self.src / "missing.png"))


class DurationFormatTest(unittest.TestCase):
    def test_formats(self):
        for sec, want in ((None, "長さ不明"), (0.0, "0.0秒"), (0.4, "0.4秒"), (9.94, "9.9秒"), (10, "0:10"), (59.6, "1:00"),
                          (61, "1:01"), (231.1, "3:51"), (3600, "60:00"), (36000, "600:00")):
            with self.subTest(sec=sec):
                self.assertEqual(g._fmt_duration(sec), want)


class EstimateTest(unittest.TestCase):
    def test_size_text(self):
        self.assertEqual(g.estimate_size_text(None, "light"), "不明")
        self.assertIn("MB", g.estimate_size_text(60, "medium"))
        self.assertIn("MB", g.estimate_size_text(60, ""))  # プリセット未指定は既定
        self.assertEqual(g.estimate_size_text(60, "no-such"), "不明")

    def test_bigger_preset_means_bigger_estimate(self):
        def mb(p):
            return float(g.estimate_size_text(600, p).split()[1])

        self.assertLess(mb("light"), mb("medium"))


class JobTest(unittest.TestCase):
    def tearDown(self):
        set_cancel_event(None)

    def drain(self, job, timeout=10):
        job.join(timeout)
        ev = []
        while not job.events.empty():
            ev.append(job.events.get())
        return ev

    def test_success_events(self):
        ev = self.drain(g.Job(lambda log: (log("[1/6] a"), log("hello"), "RESULT")[2]).start())
        self.assertEqual(ev[0], ("log", "[1/6] a"))
        self.assertEqual(ev[1], ("stage", 1, 6, "a"))
        self.assertEqual(ev[2], ("log", "hello"))
        self.assertEqual(ev[-1], ("done", "RESULT"))

    def test_error_cancel_and_crash_mapping(self):
        def raiser(exc):
            def f(log):
                raise exc
            return f

        self.assertEqual(self.drain(g.Job(raiser(MkciaError("悪い"))).start())[-1], ("error", "悪い"))
        self.assertEqual(self.drain(g.Job(raiser(Cancelled("x"))).start())[-1], ("cancelled",))
        last = self.drain(g.Job(raiser(RuntimeError("boom"))).start())[-1]
        self.assertEqual(last[0], "crash")
        self.assertIn("RuntimeError: boom", last[1])

    def test_keyboard_interrupt_in_the_worker_is_reported_not_lost(self):
        last = self.drain(g.Job(lambda log: (_ for _ in ()).throw(KeyboardInterrupt())).start())[-1]
        self.assertEqual(last[0], "crash")

    def test_cancel_event_is_installed_and_cleared(self):
        from mkcia import proc

        seen = []
        job = g.Job(lambda log: seen.append(proc._cancel_event is not None))
        job.start()
        job.join(5)
        self.assertEqual(seen, [True])
        self.assertIsNone(proc._cancel_event)

    def test_cancel_interrupts_a_running_command(self):
        from mkcia.proc import run

        job = g.Job(lambda log: run(["sleep", "30"])).start()
        time.sleep(0.4)
        job.cancel()
        t0 = time.time()
        ev = self.drain(job, 10)
        self.assertEqual(ev[-1], ("cancelled",))
        self.assertLess(time.time() - t0, 6)
        self.assertFalse(job.is_running())

    def test_stage_regex_ignores_other_lines(self):
        ev = self.drain(g.Job(lambda log: (log("完了: x"), log("$ cmd [1/2]"), log("[2/6]no space"))[0]).start())
        stages = [e for e in ev if e[0] == "stage"]
        self.assertEqual(stages, [("stage", 2, 6, "no space")])


@requires_tools
class JobRealTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)

    def tearDown(self):
        set_cancel_event(None)
        self._d.cleanup()

    def drain(self, job):
        job.join(120)
        ev = []
        while not job.events.empty():
            ev.append(job.events.get())
        return ev

    def test_validation_job_returns_a_summary(self):
        t = make_template(self.d / "t")
        ev = self.drain(g.start_validation(BuildOptions(t, self.d / "o.cia", preset="light")))
        kind, text = ev[-1]
        self.assertEqual(kind, "done")
        for frag in ("t", "light", "160x90", "o.cia", "MB"):
            self.assertIn(frag, text)
        self.assertFalse((self.d / "o.cia").exists())  # 検証だけで作らない

    def test_validation_job_reports_problems(self):
        t = make_template(self.d / "t", skip=("video.mp4",))
        ev = self.drain(g.start_validation(BuildOptions(t, self.d / "o.cia")))
        self.assertEqual(ev[-1][0], "error")
        self.assertIn("video", ev[-1][1])

    def test_build_job_produces_a_cia_and_stages(self):
        t = make_template(self.d / "t")
        ev = self.drain(g.start_build(BuildOptions(t, self.d / "o.cia", preset="light", compress_code=False)))
        self.assertEqual(ev[-1], ("done", self.d / "o.cia"))
        self.assertEqual([e[1] for e in ev if e[0] == "stage"], [1, 2, 3, 4, 5, 6])
        self.assertTrue((self.d / "o.cia").stat().st_size > 1000)

    def test_cancelled_build_leaves_nothing(self):
        t = make_template(self.d / "t")
        out = self.d / "o.cia"
        job = g.start_build(BuildOptions(t, out, preset="light", compress_code=False))
        deadline = time.time() + 30
        while time.time() < deadline:  # エンコード開始後に中止
            if any(e[0] == "stage" and e[1] >= 2 for e in list(job.events.queue)):
                break
            time.sleep(0.02)
        job.cancel()
        ev = self.drain(job)
        self.assertIn(ev[-1][0], ("cancelled", "done"))  # 早すぎて終わっていた場合も許す
        if ev[-1][0] == "cancelled":
            self.assertFalse(out.exists())
        self.assertEqual([p.name for p in self.d.iterdir() if p.name.startswith(".")], [])


if __name__ == "__main__":
    unittest.main()
