"""外部ツールのサブプロセス呼び出し共通部。"""

import os
import shutil
import subprocess
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


def find_tool(name: str) -> str:
    """MKCIA_TOOLS_DIR -> <repo>/tools/bin -> PATH の順で外部ツールを探す。"""
    for d in _search_dirs():
        p = d / name
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    found = shutil.which(name)
    if found:
        return found
    raise MkciaError(
        f"外部ツール '{name}' が見つかりません。"
        f" PATH に置くか MKCIA_TOOLS_DIR / {REPO_ROOT / 'tools' / 'bin'} に配置してください。"
    )


def run(cmd: Sequence[str], log: Optional[Log] = None, cwd: Optional[Path] = None) -> str:
    """コマンドを実行して stdout を返す。失敗時は stderr 付きで MkciaError。"""
    if log:
        log("$ " + " ".join(str(c) for c in cmd))
    try:
        r = subprocess.run(
            [str(c) for c in cmd],
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
    except OSError as e:
        raise MkciaError(f"{cmd[0]} を実行できません: {e}") from e
    if r.returncode != 0:
        tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-15:])
        raise MkciaError(f"{Path(str(cmd[0])).name} が失敗しました (exit {r.returncode}):\n{tail}")
    return r.stdout
