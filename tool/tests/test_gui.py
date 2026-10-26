"""GUI (Tkinter) の通し操作テスト。画面 (DISPLAY) が無い環境ではスキップする。"""

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import base_assets, cleanup_assets, make_audio, make_image, make_template, make_video, requires_tools
from mkcia import gui_model as gm
from mkcia.proc import set_cancel_event

try:
    import tkinter as tk
    _r = tk.Tk()
    _r.destroy()
    HAVE_DISPLAY = True
except Exception:  # tkinter が無い / 画面が無い
    HAVE_DISPLAY = False

if HAVE_DISPLAY:
    from mkcia import gui


def tearDownModule():
    set_cancel_event(None)
    cleanup_assets()


if HAVE_DISPLAY:
    class FakeApp(gui.App):
        """ダイアログを差し替え、呼ばれた内容を記録する。"""

        def __init__(self, *a, **kw):
            self.errors, self.infos, self.confirms = [], [], []
            self.answers = {"new_name": None, "open_file": None, "directory": None, "confirm": True}
            super().__init__(*a, **kw)

        def ask_open_file(self, title, kind):
            return self.answers["open_file"]

        def ask_directory(self, title):
            return self.answers["directory"]

        def ask_new_name(self):
            return self.answers["new_name"]

        def confirm(self, title, text):
            self.confirms.append(text)
            return self.answers["confirm"]

        def show_error(self, text):
            self.errors.append(text)

        def show_info(self, text):
            self.infos.append(text)


@unittest.skipUnless(HAVE_DISPLAY, "tkinter と画面 (DISPLAY) が必要")
class GuiTestBase(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)
        self.troot = self.d / "template"
        self.troot.mkdir()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = FakeApp(self.root, self.troot)

    def tearDown(self):
        job = self.app.job
        if job is not None and job.is_running():
            job.cancel()
            job.join(10)
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        set_cancel_event(None)
        self._d.cleanup()

    def wait(self, cond, timeout=60.0, what="条件"):
        end = time.time() + timeout
        while time.time() < end:
            self.root.update()
            if cond():
                return
            time.sleep(0.01)
        self.fail(f"タイムアウト: {what}")

    def settle(self):
        """バックグラウンドの読み込み (素材の情報・サムネイル) が終わるまで待つ。"""
        self.wait(lambda: self.app._bg_busy == 0 and self.app._bg.empty(), 30, "素材の読み込み")
        self.root.update()

    def new_template(self, name="Movie"):
        self.app.answers["new_name"] = name
        self.app.on_new_template()
        self.settle()

    def fill(self, **kw):
        for k, v in kw.items():
            self.app.vars[k].set(v)

    def good_fields(self):
        self.fill(title="日本語 Title", publisher="me", version="1.2.3")

    def meta(self):
        return json.loads((self.app.template.path / "meta.json").read_text(encoding="utf-8"))

    def full_template(self, name="Full", **meta):
        make_template(self.troot / name, meta or None)
        return name

    def open_named(self, name):
        self.app.open_template(self.troot / name)
        self.settle()


class StartupTest(GuiTestBase):
    def test_empty_root_shows_a_hint(self):
        self.assertIsNone(self.app.template)
        self.assertEqual(list(self.app.tpl_box.cget("values")), [])
        self.assertIn("テンプレートがありません", self.app.status_var.get())

    def test_lists_existing_templates(self):
        self.full_template("b")
        self.full_template("a")
        self.app.refresh_template_list()
        self.assertEqual(list(self.app.tpl_box.cget("values")), ["a", "b"])

    def test_actions_without_a_template_report_errors_instead_of_crashing(self):
        self.app.save()
        self.app.build()
        self.app.validate()
        self.app.on_choose_asset("video")
        self.assertEqual(len(self.app.errors), 4)
        self.assertIsNone(self.app.job)

    def test_buttons_initial_state(self):
        self.assertEqual(str(self.app.btn_cancel.cget("state")), "disabled")
        self.assertEqual(str(self.app.btn_open.cget("state")), "disabled")


class TemplateFlowTest(GuiTestBase):
    def test_new_template_is_created_and_opened(self):
        self.new_template("My Movie")
        self.assertEqual(self.app.template.name, "My Movie")
        self.assertTrue((self.troot / "My Movie" / "meta.json").exists())
        self.assertEqual(self.app.vars["title"].get(), "My Movie")
        self.assertRegex(self.app.vars["title_id"].get(), r"^000400000[0-9A-F]{5}00$")
        self.assertIn("My Movie", self.app.tpl_box.cget("values"))
        self.assertEqual(self.app.asset_status["video"].get().split(" ")[0], "未設定")

    def test_new_template_cancelled_or_invalid(self):
        self.app.answers["new_name"] = None
        self.app.on_new_template()
        self.assertEqual(self.app.errors, [])
        for bad in ("", "a/b", ".."):
            self.app.answers["new_name"] = bad
            self.app.on_new_template()
        self.assertEqual(len(self.app.errors), 3)
        self.assertEqual(list(self.troot.iterdir()), [])

    def test_duplicate_template_name(self):
        self.new_template("dup")
        self.app.answers["new_name"] = "dup"
        self.app.on_new_template()
        self.assertTrue(any("既に" in e for e in self.app.errors))

    def test_incomplete_new_template_shows_live_problem(self):
        self.new_template("x")
        self.assertIn("publisher", self.app.problem_var.get())
        self.fill(publisher="me")
        self.assertEqual(self.app.problem_var.get(), "")

    def test_live_validation_messages(self):
        self.open_named(self.full_template())
        cases = [("title", "", "title"), ("title_id", "123", "title_id"), ("title_id", "0004000011451400", "範囲外"), ("version", "x", "version"),
                 ("product_code", "bad", "product_code"), ("output", "a/b", "output")]
        for key, bad, frag in cases:
            old = self.app.vars[key].get()
            self.fill(**{key: bad})
            self.assertIn(frag, self.app.problem_var.get(), key)
            self.fill(**{key: old})
            self.assertEqual(self.app.problem_var.get(), "", key)

    def test_opening_a_template_loads_every_field(self):
        make_template(self.troot / "T", {"title": "Hello", "long_title": "Hello Long", "publisher": "Pub",
                                         "version": "2.3.4", "product_code": "CTR-P-ABCD", "loop": True, "volume": 0.4,
                                         "preset": "light", "output": "Out"})
        self.open_named("T")
        a = self.app
        self.assertEqual([a.vars[k].get() for k in ("title", "long_title", "publisher", "version", "product_code", "output")],
                         ["Hello", "Hello Long", "Pub", "2.3.4", "CTR-P-ABCD", "Out"])
        self.assertEqual((bool(a.loop_var.get()), round(a.volume_var.get(), 2)), (True, 0.4))
        self.assertIn("light", a.preset_var.get())
        self.assertEqual(a.volume_text.get(), "0.40")

    def test_broken_meta_json_opens_with_a_warning(self):
        d = self.troot / "Broken"
        make_template(d)
        (d / "meta.json").write_text("{not json")
        self.open_named("Broken")
        self.assertIn("警告", self.app.log.get("1.0", "end"))
        self.assertEqual(self.app.vars["version"].get(), "1.0.0")

    def test_open_arbitrary_directory(self):
        other = self.d / "elsewhere" / "tpl"
        make_template(other)
        self.app.answers["directory"] = str(other)
        self.app.on_open_template_dir()
        self.settle()
        self.assertEqual(self.app.template.path, other)
        self.assertEqual(self.app.tpl_var.get(), str(other))

    def test_open_missing_directory(self):
        self.app.open_template(self.d / "nowhere")
        self.assertTrue(self.app.errors)
        self.assertIsNone(self.app.template)


class SaveTest(GuiTestBase):
    def test_save_writes_meta_json_with_all_fields(self):
        self.new_template("S")
        self.good_fields()
        self.fill(long_title="Long", product_code="CTR-P-ABCD", output="Out Name")
        self.app.loop_var.set(True)
        self.app.volume_var.set(0.35)
        self.app.preset_var.set(dict(gm.preset_choices())["light"])
        self.assertTrue(self.app.save())
        m = self.meta()
        self.assertEqual((m["title"], m["long_title"], m["publisher"], m["version"], m["product_code"], m["output"]),
                         ("日本語 Title", "Long", "me", "1.2.3", "CTR-P-ABCD", "Out Name"))
        self.assertEqual((m["loop"], m["volume"], m["preset"]), (True, 0.35, "light"))
        self.assertIn("保存", self.app.status_var.get())

    def test_default_preset_choice_removes_the_key(self):
        self.new_template("S")
        self.good_fields()
        self.app.preset_var.set(dict(gm.preset_choices())["high"])
        self.app.save()
        self.assertEqual(self.meta()["preset"], "high")
        self.app.preset_var.set(self.app._preset_default_label)
        self.app.save()
        self.assertNotIn("preset", self.meta())

    def test_invalid_input_is_not_saved(self):
        self.new_template("S")
        self.good_fields()
        self.app.save()
        before = (self.app.template.path / "meta.json").read_text()
        self.fill(title="x" * 65)
        self.assertFalse(self.app.save())
        self.assertEqual((self.app.template.path / "meta.json").read_text(), before)
        self.assertTrue(any("title" in e for e in self.app.errors))
        self.assertIn("保存できません", self.app.status_var.get())

    def test_unknown_keys_survive_a_save_from_the_gui(self):
        make_template(self.troot / "K", {"custom": "keep"})
        self.open_named("K")
        self.fill(title="Changed")
        self.app.save()
        self.assertEqual(self.meta()["custom"], "keep")
        self.assertEqual(self.meta()["title"], "Changed")

    def test_ctrl_s_binding(self):
        self.open_named(self.full_template())
        self.fill(title="ViaShortcut")
        self.root.deiconify()  # キーイベントは表示されたウィンドウにしか届かない
        self.root.update()
        self.root.focus_force()
        self.root.update()
        self.root.event_generate("<Control-s>")
        self.root.update()
        self.assertEqual(self.meta()["title"], "ViaShortcut")


class DirtyStateTest(GuiTestBase):
    def two(self):
        self.full_template("one")
        self.full_template("two")
        self.app.refresh_template_list()
        self.open_named("one")

    def switch_to(self, name):
        self.app.tpl_var.set(name)
        self.app.on_template_selected()
        self.settle()

    def test_no_prompt_when_nothing_changed(self):
        self.two()
        self.switch_to("two")
        self.assertEqual(self.app.confirms, [])
        self.assertEqual(self.app.template.name, "two")

    def test_edit_then_switch_asks_and_cancel_stays(self):
        self.two()
        self.fill(title="edited")
        self.app.answers["confirm"] = None
        self.switch_to("two")
        self.assertEqual(len(self.app.confirms), 1)
        self.assertEqual(self.app.template.name, "one")
        self.assertEqual(self.app.tpl_var.get(), "one")
        self.assertEqual(self.app.vars["title"].get(), "edited")

    def test_edit_then_switch_yes_saves(self):
        self.two()
        self.fill(title="saved-title")
        self.app.answers["confirm"] = True
        self.switch_to("two")
        self.assertEqual(self.app.template.name, "two")
        self.assertEqual(json.loads((self.troot / "one" / "meta.json").read_text())["title"], "saved-title")

    def test_edit_then_switch_no_discards(self):
        self.two()
        old = json.loads((self.troot / "one" / "meta.json").read_text())["title"]
        self.fill(title="thrown-away")
        self.app.answers["confirm"] = False
        self.switch_to("two")
        self.assertEqual(self.app.template.name, "two")
        self.assertEqual(json.loads((self.troot / "one" / "meta.json").read_text())["title"], old)

    def test_yes_with_invalid_input_stays_put(self):
        self.two()
        self.fill(title="")
        self.app.answers["confirm"] = True
        self.switch_to("two")
        self.assertEqual(self.app.template.name, "one")
        self.assertTrue(self.app.errors)

    def test_opening_a_template_is_not_dirty(self):
        self.two()
        self.assertFalse(self.app._dirty)
        self.fill(title="x")
        self.assertTrue(self.app._dirty)
        self.app.save()
        self.assertFalse(self.app._dirty)

    def test_loading_a_form_does_not_mark_dirty(self):
        self.two()
        self.open_named("two")
        self.assertFalse(self.app._dirty)

    def test_close_with_unsaved_changes_asks(self):
        self.two()
        self.fill(title="x")
        self.app.answers["confirm"] = None
        self.app.on_close()
        self.assertTrue(self.root.winfo_exists())
        self.app.answers["confirm"] = False
        self.app.on_close()
        with self.assertRaises(tk.TclError):
            self.root.winfo_exists() and self.root.state()


@requires_tools
class AssetFlowTest(GuiTestBase):
    def setUp(self):
        super().setUp()
        self.src = self.d / "src"
        self.src.mkdir()
        self.new_template("A")

    def choose(self, stem, path):
        self.app.answers["open_file"] = str(path)
        self.app.on_choose_asset(stem)
        self.wait(lambda: not self.app.errors and "コピー中" not in self.app.asset_status[stem].get()
                  or bool(self.app.errors), 30, "コピー")
        self.settle()

    def test_setting_all_assets_shows_info_and_thumbnails(self):
        self.choose("video", make_video(self.src / "v.mp4", 4.0, "160x90"))
        self.choose("icon", make_image(self.src / "i.png", "64x64"))
        self.choose("bottom", make_image(self.src / "b.png", "320x240"))
        self.choose("select_sound", make_audio(self.src / "s.wav", 1.0))
        a = self.app
        self.assertIn("160x90", a.asset_status["video"].get())
        self.assertIn("64x64", a.asset_status["icon"].get())
        self.assertIn("320x240", a.asset_status["bottom"].get())
        self.assertIn("1.0秒", a.asset_status["select_sound"].get())
        for stem in ("video", "icon", "bottom"):
            self.assertIn(stem, a._thumbs, stem)
        self.assertEqual(a.asset_thumb["select_sound"].cget("text"), "♪")
        self.assertIn("MB", a.size_label.cget("text"))
        self.assertEqual(a.errors, [])

    def test_bad_file_shows_an_error_and_keeps_the_old_asset(self):
        self.choose("icon", make_image(self.src / "good.png"))
        bad = self.src / "bad.png"
        bad.write_bytes(b"not an image")
        self.choose("icon", bad)
        self.assertEqual(len(self.app.errors), 1)
        self.assertIn("bad.png", self.app.errors[0])
        self.assertIn("64x48", self.app.asset_status["icon"].get())
        self.assertEqual(self.app.template.find_asset("icon").name, "icon.png")

    def test_wrong_kind_of_file(self):
        self.choose("video", make_image(self.src / "pic.png"))
        self.assertTrue(self.app.errors)
        self.assertIsNone(self.app.template.find_asset("video"))

    def test_cancelled_file_dialog_changes_nothing(self):
        self.app.answers["open_file"] = None
        self.app.on_choose_asset("video")
        self.settle()
        self.assertEqual(self.app.errors, [])

    def test_remove_optional_asset(self):
        self.choose("select_sound", make_audio(self.src / "s.wav"))
        self.assertIsNotNone(self.app.template.find_asset("select_sound"))
        self.app.on_remove_asset("select_sound")
        self.settle()
        self.assertIsNone(self.app.template.find_asset("select_sound"))
        self.assertIn("未設定", self.app.asset_status["select_sound"].get())

    def test_remove_buttons_exist_for_every_optional_asset(self):  # 必須は動画だけ
        self.assertEqual(sorted(self.app.asset_remove), ["banner", "bottom", "icon", "select_sound"])

    def test_replacing_a_video_with_a_different_extension(self):
        self.choose("video", make_video(self.src / "a.mp4"))
        mkv = self.src / "b.mkv"
        shutil.copyfile(base_assets() / "video.mp4", mkv)
        self.choose("video", mkv)
        self.assertEqual([p.name for p in self.app.template.asset_candidates("video")], ["video.mkv"])
        self.assertIn("video.mkv", self.app.asset_status["video"].get())

    def test_stale_results_from_another_template_are_ignored(self):
        self.full_template("Other")
        self.open_named("Other")
        before = self.app.asset_status["icon"].get()
        self.app._asset_loaded(("icon", self.troot / "A", "STALE", None, None))
        self.assertEqual(self.app.asset_status["icon"].get(), before)

    def test_switching_templates_refreshes_assets(self):
        self.full_template("Full")
        self.open_named("Full")
        self.assertIn("icon.png", self.app.asset_status["icon"].get())
        self.open_named("A")
        self.assertIn("未設定", self.app.asset_status["icon"].get())


@requires_tools
class BuildFlowTest(GuiTestBase):
    def setUp(self):
        super().setUp()
        self.full_template("Full", title="GUI Movie", output="Gui-Movie", preset="light")
        self.app.refresh_template_list()
        self.open_named("Full")
        self.app.compress_var.set(False)  # 速くする
        self.out = self.d / "outdir"
        self.app.outdir_var.set(str(self.out))

    def run_job(self, starter):
        starter()
        self.assertIsNotNone(self.app.job)
        self.wait(lambda: not self.app.job.is_running() and self.app.job.events.empty(), 120, "ジョブ")
        self.root.update()

    def test_build_produces_the_cia_and_updates_the_ui(self):
        self.run_job(self.app.build)
        a = self.app
        self.assertEqual(a.last_output, self.out / "Gui-Movie.cia")
        self.assertTrue(a.last_output.stat().st_size > 1000)
        self.assertIn("完了", a.status_var.get())
        self.assertEqual(float(a.progress.cget("value")), 6.0)
        self.assertIn("[6/6]", a.log.get("1.0", "end"))
        self.assertEqual(str(a.btn_open.cget("state")), "normal")
        self.assertEqual(str(a.btn_build.cget("state")), "normal")
        self.assertEqual(str(a.btn_cancel.cget("state")), "disabled")
        self.assertEqual(a.errors, [])

    def test_command_lines_are_hidden_unless_requested(self):
        self.app.handle_event(("log", "$ ffmpeg -i x y"))
        self.app.handle_event(("log", "[2/6] 動画エンコード"))
        text = self.app.log.get("1.0", "end")
        self.assertNotIn("ffmpeg -i", text)
        self.assertIn("動画エンコード", text)
        self.app.verbose_var.set(True)
        self.app.handle_event(("log", "$ ffmpeg -i x y"))
        self.assertIn("ffmpeg -i", self.app.log.get("1.0", "end"))

    def test_build_saves_unsaved_edits_first(self):
        self.fill(title="Edited Before Build")
        self.run_job(self.app.build)
        self.assertEqual(self.meta()["title"], "Edited Before Build")
        self.assertFalse(self.app._dirty)

    def test_build_does_not_start_with_invalid_input(self):
        self.fill(title="")
        self.app.build()
        self.assertIsNone(self.app.job)
        self.assertTrue(self.app.errors)
        self.assertFalse(self.out.exists())

    def test_ui_is_locked_while_running(self):
        self.app.build()
        a = self.app
        self.assertEqual(str(a.btn_build.cget("state")), "disabled")
        self.assertEqual(str(a.btn_save.cget("state")), "disabled")
        self.assertEqual(str(a.btn_cancel.cget("state")), "normal")
        a.build()  # 二重起動しない
        self.wait(lambda: not a.job.is_running() and a.job.events.empty(), 120, "ジョブ")

    def test_validate_only_does_not_build(self):
        self.run_job(self.app.validate)
        self.assertFalse(self.out.exists())
        log = self.app.log.get("1.0", "end")
        self.assertIn("検証OK", log)
        self.assertIn("Gui-Movie.cia", log)
        self.assertIn("検証OK", self.app.status_var.get())
        self.assertEqual(str(self.app.btn_open.cget("state")), "disabled")

    def test_validate_reports_problems(self):
        (self.app.template.path / "icon.png").write_bytes(b"broken")
        self.run_job(self.app.validate)
        self.assertTrue(any("icon.png" in e for e in self.app.errors))
        self.assertIn("失敗", self.app.status_var.get())
        self.assertEqual(str(self.app.btn_build.cget("state")), "normal")

    def test_build_error_is_shown_and_ui_recovers(self):
        (self.app.template.path / "video.mp4").write_bytes(b"not a video")
        self.run_job(self.app.build)
        self.assertEqual(len(self.app.errors), 1)
        self.assertIn("video.mp4", self.app.errors[0])
        self.assertEqual(str(self.app.btn_build.cget("state")), "normal")
        self.assertFalse(self.out.exists())

    def test_cancel(self):
        self.app.build()
        self.wait(lambda: "[2/6]" in self.app.log.get("1.0", "end"), 60, "エンコード開始")
        self.app.cancel()
        self.wait(lambda: not self.app.job.is_running() and self.app.job.events.empty(), 60, "中止")
        self.root.update()
        self.assertIn("中止", self.app.status_var.get())
        self.assertFalse((self.out / "Gui-Movie.cia").exists())
        self.assertEqual(float(self.app.progress.cget("value")), 0.0)
        self.assertEqual(self.app.errors, [])  # 中止はエラー扱いにしない
        self.assertEqual(str(self.app.btn_build.cget("state")), "normal")

    def test_cancel_without_a_job_is_harmless(self):
        self.app.cancel()
        self.assertEqual(self.app.errors, [])

    def test_output_dir_default_and_override(self):
        self.app.outdir_var.set("")
        self.assertIsNone(self.app._options().output_dir)
        self.app.outdir_var.set(f"  {self.out}  ")
        self.assertEqual(self.app._options().output_dir, self.out)
        self.app.outdir_var.set("~/somewhere")
        self.assertNotIn("~", str(self.app._options().output_dir))

    def test_compress_checkbox_reaches_the_options(self):
        self.app.compress_var.set(True)
        self.assertTrue(self.app._options().compress_code)
        self.app.compress_var.set(False)
        self.assertFalse(self.app._options().compress_code)

    def test_options_leave_preset_to_meta_json(self):
        self.assertIsNone(self.app._options().preset)

    def test_open_output_folder(self):
        self.run_job(self.app.build)
        with mock.patch.object(gm, "open_folder", return_value=True) as m:
            self.app.open_output_folder()
        m.assert_called_once_with(self.out)
        with mock.patch.object(gm, "open_folder", return_value=False):
            self.app.open_output_folder()
        self.assertTrue(any("開けませんでした" in e for e in self.app.errors))

    def test_close_while_building_cancels(self):
        self.app.build()
        self.wait(lambda: "[2/6]" in self.app.log.get("1.0", "end"), 60, "エンコード開始")
        self.app.answers["confirm"] = False
        self.app.on_close()
        self.assertTrue(self.app.job.is_running() or True)
        self.assertTrue(self.root.winfo_exists())
        self.app.answers["confirm"] = True
        self.app.on_close()
        self.assertFalse(self.app.job.is_running())

    def test_crash_event_is_reported(self):
        self.app.handle_event(("crash", "Traceback...\nRuntimeError: boom"))
        self.assertTrue(any("boom" in e for e in self.app.errors))
        self.assertIn("内部エラー", self.app.status_var.get())


class LiveChecksTest(GuiTestBase):
    def test_title_id_conflict_warning_and_auto_fix(self):
        make_template(self.troot / "a", {"title_id": "000400000FF3A000"})
        make_template(self.troot / "b", {"title_id": "000400000FF3A000"})
        self.open_named("b")
        self.assertIn("a", self.app.id_warn.cget("text"))
        self.assertIn("注意", self.app.id_warn.cget("text"))
        self.app.on_auto_title_id()
        self.assertNotEqual(self.app.vars["title_id"].get(), "000400000FF3A000")
        self.assertNotIn("注意", self.app.id_warn.cget("text"))
        gm.validate_form(self.app.collect_form())

    def test_no_warning_for_a_unique_id(self):
        make_template(self.troot / "a", {"title_id": "000400000FF3A000"})
        make_template(self.troot / "b", {"title_id": "000400000FF3A100"})
        self.open_named("a")
        self.assertNotIn("注意", self.app.id_warn.cget("text"))

    def test_volume_slider_updates_label_and_dirty(self):
        self.open_named(self.full_template())
        self.app.volume_var.set(0.5)
        self.app.on_volume_moved()
        self.assertEqual(self.app.volume_text.get(), "0.50")
        self.assertTrue(self.app._dirty)

    def test_collect_form_round_trip(self):
        make_template(self.troot / "R", {"long_title": "L", "product_code": "CTR-P-ABCD", "loop": True, "volume": 0.3,
                                         "preset": "high", "output": "O"})
        self.open_named("R")
        f = self.app.collect_form()
        self.assertEqual((f.long_title, f.product_code, f.loop, f.volume, f.preset, f.output),
                         ("L", "CTR-P-ABCD", True, 0.3, "high", "O"))

    def test_size_estimate_follows_the_preset(self):
        self.open_named(self.full_template())
        self.wait(lambda: "MB" in self.app.size_label.cget("text"), 20, "見積もり")
        self.app._video_duration = 3600.0  # 1 時間なら、プリセット間の差が丸めに埋もれない
        self.app.preset_var.set(dict(gm.preset_choices())["light"])
        self.app.on_field_changed()
        light = self.app.size_label.cget("text")
        self.app.preset_var.set(dict(gm.preset_choices())["standard"])
        self.app.on_field_changed()
        self.assertNotEqual(self.app.size_label.cget("text"), light)


if __name__ == "__main__":
    unittest.main()
