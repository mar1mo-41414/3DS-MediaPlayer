"""romfs ディレクトリの組み立てと 3dstool による romfs.bin 生成。"""

import json
import shutil
from pathlib import Path
from typing import Optional

from .proc import Log, find_tool, run

# ROM 本体 (rom/source/main.c) が決め打ちで読むファイル名
ROMFS_VIDEO = "video.mp4"
ROMFS_BOTTOM = "bottom.png"
ROMFS_CONFIG = "config.json"


def stage_romfs(
    romfs_dir: Path, video_mp4: Path, bottom_png: Path, loop: bool, volume: float, deblock: bool = False
) -> Path:
    """romfs_dir に ROM 本体が読む 3 ファイルを配置する。"""
    romfs_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(video_mp4, romfs_dir / ROMFS_VIDEO)
    shutil.copyfile(bottom_png, romfs_dir / ROMFS_BOTTOM)
    (romfs_dir / ROMFS_CONFIG).write_text(
        json.dumps({"loop": bool(loop), "volume": round(float(volume), 3), "deblock": bool(deblock)}) + "\n", encoding="utf-8"
    )
    return romfs_dir


def build_romfs_bin(romfs_dir: Path, dst: Path, log: Optional[Log] = None) -> Path:
    run([find_tool("3dstool"), "-ctf", "romfs", dst, "--romfs-dir", romfs_dir], log)
    return dst
