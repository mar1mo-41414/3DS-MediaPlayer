"""外部コマンドの中止 (GUI の「中止」ボタンの土台)。"""

import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import cleanup_assets, make_template, requires_tools
from mkcia import proc, validate, video
from mkcia.errors import MkciaError
from mkcia.pipeline import BuildOptions, build_cia
from mkcia.proc import Cancelled, run, set_cancel_event


def tearDownModule():
    set_cancel_event(None)
    cleanup_assets()


class RunCancelTest(unittest.TestCase):
    def tearDown(self):
        set_cancel_event(None)

    def test_cancelled_is_a_user_error_subclass(self):
        self.assertTrue(issubclass(Cancelled, MkciaError))

    def test_normal_run_unaffected_by_an_unset_event(self):
        set_cancel_event(threading.Event())
        self.assertEqual(run(["echo", "hello"]).strip(), "hello")

    def test_already_set_event_prevents_starting(self):
        ev = threading.Event()
        ev.set()
        set_cancel_event(ev)
        with self.assertRaises(Cancelled):
            run(["echo", "never"])

    def test_cancel_during_a_long_command_terminates_it_quickly(self):
        ev = threading.Event()
        set_cancel_event(ev)
        threading.Timer(0.5, ev.set).start()
        t0 = time.time()
        with self.assertRaises(Cancelled):
            run(["sleep", "30"])
        self.assertLess(time.time() - t0, 5)

    def test_stubborn_process_is_killed(self):
        ev = threading.Event()
        set_cancel_event(ev)
        threading.Timer(0.3, ev.set).start()
        t0 = time.time()
        with self.assertRaises(Cancelled):
            run(["bash", "-c", "trap '' TERM; sleep 30"])  # SIGTERM を無視する
        self.assertLess(time.time() - t0, 8)

    def test_failure_still_reports_exit_code_and_tail(self):
        with self.assertRaises(MkciaError) as cm:
            run(["bash", "-c", "echo oops >&2; exit 3"])
        self.assertIn("exit 3", str(cm.exception))
        self.assertIn("oops", str(cm.exception))

    def test_large_output_does_not_deadlock(self):
        out = run(["bash", "-c", "head -c 3000000 /dev/zero | tr '\\0' 'x'"])
        self.assertEqual(len(out), 3000000)

    def test_missing_command(self):
        with self.assertRaises(MkciaError):
            run(["definitely-not-a-command-xyz"])

    def test_cancel_is_not_turned_into_a_misleading_message(self):
        """validate / video が MkciaError を言い換える箇所でも Cancelled はそのまま伝わる。"""
        # ツールの探索も差し替えて、外部ツールが無い環境でも動くようにする
        with mock.patch.object(validate, "find_tool", lambda name: name), \
             mock.patch.object(validate, "run", side_effect=Cancelled("中止しました")):
            with self.assertRaises(Cancelled):
                validate.validate_audio(Path(__file__))
        with mock.patch.object(video, "find_tool", lambda name: name), \
             mock.patch.object(video, "run", side_effect=Cancelled("中止しました")):
            with self.assertRaises(Cancelled):
                video.encode_video(Path(__file__), Path("/tmp/x.mp4"), "light",
                                   info=validate.VideoInfo(10, 10, 5.0, 10, True))


@requires_tools
class BuildCancelTest(unittest.TestCase):
    def tearDown(self):
        set_cancel_event(None)

    def test_cancel_in_the_middle_of_a_build_leaves_nothing_behind(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            t = make_template(d / "t")
            out = d / "out" / "o.cia"
            out.parent.mkdir()
            out.write_bytes(b"PRECIOUS")
            ev = threading.Event()
            set_cancel_event(ev)

            def log(msg):
                if msg.startswith("[3/6]"):  # エンコード後、SMDH 生成の段階で中止
                    ev.set()

            with self.assertRaises(Cancelled):
                build_cia(BuildOptions(t, out, preset="light", compress_code=False), log=log)
            self.assertEqual(out.read_bytes(), b"PRECIOUS")
            self.assertEqual([p.name for p in out.parent.iterdir()], ["o.cia"])


if __name__ == "__main__":
    unittest.main()
