"""bannertool で SMDH (アイコン+タイトル) と banner (+選択音) を生成する。"""

from pathlib import Path
from typing import Optional

from .proc import Log, find_tool, run


def make_smdh(
    icon_png: Path, dst: Path, title: str, long_title: str, publisher: str, log: Optional[Log] = None
) -> Path:
    run(
        [
            find_tool("bannertool"), "makesmdh",
            "-s", title, "-l", long_title, "-p", publisher,
            "-i", icon_png, "-o", dst,
        ],
        log,
    )
    return dst


def make_banner(banner_png: Path, audio_wav: Path, dst: Path, log: Optional[Log] = None) -> Path:
    run(
        [find_tool("bannertool"), "makebanner", "-i", banner_png, "-a", audio_wav, "-o", dst],
        log,
    )
    return dst
