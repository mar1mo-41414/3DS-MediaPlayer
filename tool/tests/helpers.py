"""テスト共通: ffmpeg で小さなテスト用メディアを作る / テンプレートを組み立てる / CIA の中身を読む。"""

import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mkcia.errors import MkciaError  # noqa: E402
from mkcia.pipeline import DEFAULT_ELF  # noqa: E402
from mkcia.proc import find_tool  # noqa: E402

GOOD_META = {
    "title": "TestApp",
    "publisher": "tester",
    "title_id": "000400000FF3A000",
    "version": "1.0.0",
}


def _tools_available() -> bool:
    try:
        for t in ("ffmpeg", "ffprobe", "bannertool", "3dstool", "makerom"):
            find_tool(t)
    except MkciaError:
        return False
    return DEFAULT_ELF.is_file()


TOOLS_OK = _tools_available()
requires_tools = unittest.skipUnless(TOOLS_OK, "外部ツール (ffmpeg/ffprobe/bannertool/3dstool/makerom) と prebuilt ELF が必要")


def ffmpeg(*args) -> None:
    r = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", *map(str, args)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + r.stderr[-500:])


def make_video(path: Path, seconds: float = 1.0, size: str = "160x90", fps: int = 10, audio: bool = True,
               vf: str = "") -> Path:
    args = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100"]
    args += ["-t", seconds, "-pix_fmt", "yuv420p"]
    if vf:
        args += ["-vf", vf]
    args += ["-c:v", "libx264", "-preset", "ultrafast"]
    args += ["-c:a", "aac"] if audio else ["-an"]
    ffmpeg(*args, path)
    return path


def make_image(path: Path, size: str = "64x48") -> Path:
    ffmpeg("-f", "lavfi", "-i", f"testsrc=size={size}:rate=1", "-frames:v", 1, path)
    return path


def make_audio(path: Path, seconds: float = 1.0) -> Path:
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=880:sample_rate=32000", "-t", seconds, path)
    return path


_cache = {}


def base_assets() -> Path:
    """全テストで使い回す正常な素材 (1 回だけ生成)。"""
    if "dir" not in _cache:
        d = Path(tempfile.mkdtemp(prefix="mkcia-test-assets-"))
        make_video(d / "video.mp4")
        make_image(d / "icon.png", "64x64")
        make_image(d / "bottom.png", "320x240")
        make_audio(d / "select_sound.wav")
        (d / "meta.json").write_text(json.dumps(GOOD_META))
        _cache["dir"] = d
    return _cache["dir"]


def cleanup_assets() -> None:
    d = _cache.pop("dir", None)
    if d:
        shutil.rmtree(d, ignore_errors=True)


MISSING = object()  # meta_overrides で「このキーを meta.json から消す」ための目印


def make_template(dest: Path, meta_overrides=None, skip=(), copy_sound=True) -> Path:
    """正常なテンプレートを dest に作る。skip に含めたファイル名は作らない。

    meta_overrides: meta.json のキーを上書きする辞書。値が MISSING ならそのキーを消す (None は JSON の null)。
    """
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("video.mp4", "icon.png", "bottom.png", "select_sound.wav", "meta.json"):
        if name in skip or (name == "select_sound.wav" and not copy_sound):
            continue
        shutil.copyfile(base_assets() / name, dest / name)
    if meta_overrides is not None and "meta.json" not in skip:
        meta = dict(GOOD_META)
        meta.update(meta_overrides)
        meta = {k: v for k, v in meta.items() if v is not MISSING}
        (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return dest


# ---------------------------------------------------------------- CIA の中身

def _align(n, a=64):
    return (n + a - 1) // a * a


def cia_content_offset(data: bytes) -> int:
    hsz, _typ, _ver, cert, tik, tmd, _meta = struct.unpack_from("<IHHIIII", data, 0)
    off = _align(hsz)
    off = _align(off + cert)
    off = _align(off + tik)
    return _align(off + tmd)


def read_cia_info(path: Path) -> dict:
    d = Path(path).read_bytes()
    c = cia_content_offset(d)
    return {
        "ncch_magic": d[c + 0x100:c + 0x104],
        "title_id": d[c + 0x108:c + 0x110][::-1].hex().upper(),
        "product_name": d[c + 0x200:c + 0x208].rstrip(b"\0"),
        "product_code": d[c + 0x150:c + 0x160].rstrip(b"\0").decode("ascii", "replace"),
        "smdh_title": _smdh_title(d),
    }


def _smdh_title(d: bytes) -> str:
    i = d.find(b"SMDH")
    if i < 0:
        return ""
    return d[i + 8 + 0x80 * 0:i + 8 + 0x80 * 0 + 0x80].decode("utf-16-le", "replace").rstrip("\0")
