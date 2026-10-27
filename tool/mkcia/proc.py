"""外部ツールのサブプロセス呼び出し共通部。"""

import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional, Sequence

from .errors import MkciaError

Log = Callable[[str], None]

# <repo>/tool/mkcia/proc.py -> <repo>
REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_ROOT = REPO_ROOT / "template"  # テンプレートディレクトリ置き場 (名前だけで指定できる)
OUT_ROOT = REPO_ROOT / "out"  # 生成した CIA の既定の出力先


def _search_dirs():
    env = os.environ.get("MKCIA_TOOLS_DIR")
    if env:
        yield Path(env)
    yield REPO_ROOT / "tools" / "bin"


# 外部コマンドの起動に共通の引数。Windows では GUI (pythonw、コンソール無し) から子プロセスを起こすと、
# 既定ではコンソールウィンドウが一瞬ずつ開いて閉じる (サムネイルや動画の確認で ffmpeg / ffprobe を呼ぶたび) ので、出さない。
# stdin も塞ぐ (コンソールが無いと、標準入力のハンドルが無効で起動に失敗することがあるため)。
SUBPROCESS_KWARGS = {"stdin": subprocess.DEVNULL}
if os.name == "nt":
    SUBPROCESS_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW


def find_tool(name: str) -> str:
    """MKCIA_TOOLS_DIR -> <repo>/tools/bin -> PATH の順で外部ツールを探す。"""
    # Windows では ffmpeg -> ffmpeg.exe のように拡張子を補って探す (shutil.which と同じ PATHEXT)
    exts = [""] + [e for e in os.environ.get("PATHEXT", ".EXE").lower().split(os.pathsep) if e] if os.name == "nt" else [""]
    for d in _search_dirs():
        for ext in exts:
            p = d / (name + ext)
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
    found = shutil.which(name)
    if found:
        return found
    raise MkciaError(
        f"外部ツール '{name}' が見つかりません。"
        f" PATH に置くか MKCIA_TOOLS_DIR / {REPO_ROOT / 'tools' / 'bin'} に配置してください。"
    )


class Cancelled(MkciaError):
    """GUI などからの中止要求で処理を打ち切ったことを表す。"""


# 中止要求。GUI が set() すると、実行中の外部コマンドを終了させ Cancelled を送出する。
# (同時に走るビルドは 1 つだけという前提のモジュール全体の状態)
_cancel_event: Optional[threading.Event] = None


def set_cancel_event(event: Optional[threading.Event]) -> None:
    global _cancel_event
    _cancel_event = event


def _terminate(p: subprocess.Popen) -> None:
    p.terminate()
    try:
        p.wait(timeout=2)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    for f in (p.stdout, p.stderr):  # パイプを閉じて ResourceWarning やリークを避ける
        if f:
            f.close()


def run(cmd: Sequence[str], log: Optional[Log] = None, cwd: Optional[Path] = None) -> str:
    """コマンドを実行して stdout を返す。失敗時は stderr 付きで MkciaError。中止要求があれば Cancelled。"""
    if log:
        log("$ " + " ".join(str(c) for c in cmd))
    if _cancel_event is not None and _cancel_event.is_set():
        raise Cancelled("中止しました")
    try:
        p = subprocess.Popen(
            [str(c) for c in cmd],
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            **SUBPROCESS_KWARGS,
        )
    except OSError as e:
        raise MkciaError(f"{cmd[0]} を実行できません: {e}") from e
    try:
        while True:
            try:
                out, err = p.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if _cancel_event is not None and _cancel_event.is_set():
                    _terminate(p)
                    raise Cancelled("中止しました") from None
    except BaseException:  # KeyboardInterrupt を含め、子プロセスを残さない
        if p.poll() is None:
            _terminate(p)
        raise
    if p.returncode != 0:
        tail = "\n".join((out + err).strip().splitlines()[-15:])
        raise MkciaError(f"{Path(str(cmd[0])).name} が失敗しました (exit {p.returncode}):\n{tail}")
    return out
