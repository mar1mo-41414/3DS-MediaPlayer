"""入力の事前検証。

重い処理 (エンコードなど) を始める前に、テンプレート・メディア・出力先・ROM の ELF・外部ツールを
まとめて確認し、問題があれば「どのファイルの何が悪いか」を日本語で伝える (ffmpeg などの生ログは見せない)。
"""

import json
import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .errors import MkciaError
from .proc import find_tool, run

# ここに挙げた拡張子のファイルを、(stem + 拡張子) の順で探す。ffmpeg が読める形式なら何でもよい
VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif")
SOUND_EXTS = (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac")

MIN_VIDEO_SEC = 0.5
# FAT32 の 1 ファイル上限は 4GiB。余裕を見て、見積もりがこれを超えるなら作らない
MAX_CIA_BYTES = 3_800_000_000
# 画像の極端な大きさ (ffmpeg に巨大なバッファを確保させない)
MAX_IMAGE_SIDE = 16384


@dataclass
class TemplateFiles:
    root: Path
    meta: Path
    video: Path
    icon: Path
    bottom: Path
    sound: Optional[Path] = None
    banner: Optional[Path] = None


def _first_existing(root: Path, stem: str, exts) -> Optional[Path]:
    """root/stem+ext を exts の順で探し、最初に見つかったパスを返す (存在だけを見る)。"""
    for ext in exts:
        p = root / f"{stem}{ext}"
        if p.exists() or p.is_symlink():
            return p
    return None


def _check_regular_file(p: Path, label: str) -> Path:
    if p.is_dir():
        raise MkciaError(f"{label} はファイルではなくディレクトリです: {p}")
    if not p.is_file():  # 壊れたシンボリックリンクなど
        raise MkciaError(f"{label} を開けません (壊れたリンクかもしれません): {p}")
    try:
        size = p.stat().st_size
    except OSError as e:
        raise MkciaError(f"{label} の情報を取得できません: {p} ({e.strerror})") from e
    if size == 0:
        raise MkciaError(f"{label} が空 (0 バイト) です: {p}")
    if not os.access(p, os.R_OK):
        raise MkciaError(f"{label} の読み取り権限がありません: {p}")
    return p


def check_template(template_dir: Path) -> TemplateFiles:
    """テンプレートディレクトリの構成を確認する (中身のメディア検証は validate_* で別途)。"""
    root = Path(template_dir)
    if not root.exists():
        raise MkciaError(f"テンプレートディレクトリが見つかりません: {root}")
    if not root.is_dir():
        raise MkciaError(f"テンプレートはディレクトリで指定してください (ファイルが渡されました): {root}")

    required = [
        ("meta", "meta.json", ("",)),
        ("video", "video.(mp4|mkv|mov|avi|webm|m4v)", None),
        ("icon", "icon.(png|jpg|jpeg|bmp|webp|gif)", None),
        ("bottom", "bottom.(png|jpg|jpeg|bmp|webp|gif)", None),
    ]
    found = {}
    missing: List[str] = []
    for key, label, _ in required:
        if key == "meta":
            p = root / "meta.json"
            p = p if (p.exists() or p.is_symlink()) else None
        elif key == "video":
            p = _first_existing(root, "video", VIDEO_EXTS)
        else:
            p = _first_existing(root, key, IMAGE_EXTS)
        if p is None:
            missing.append(label)
        else:
            found[key] = _check_regular_file(p, p.name)
    if missing:
        raise MkciaError(
            "テンプレートに必要なファイルがありません: " + ", ".join(missing) + f"\n  ({root})"
        )

    sound = _first_existing(root, "select_sound", SOUND_EXTS)
    banner = _first_existing(root, "banner", IMAGE_EXTS)
    return TemplateFiles(
        root=root,
        meta=found["meta"],
        video=found["video"],
        icon=found["icon"],
        bottom=found["bottom"],
        sound=_check_regular_file(sound, sound.name) if sound else None,
        banner=_check_regular_file(banner, banner.name) if banner else None,
    )


# ---------------------------------------------------------------- メディア

def _probe(path: Path, label: str, extra: Optional[List[str]] = None) -> dict:
    """ffprobe の JSON を返す。読めなければファイル名付きの MkciaError。"""
    try:
        out = run([find_tool("ffprobe"), "-v", "error", "-show_format", "-show_streams",
                   "-of", "json", *(extra or []), str(path)])
    except MkciaError as e:
        # ffprobe が走らない (ツール無し) 場合はそのまま、走って失敗したなら「読めない」と言い換える
        if "見つかりません" in str(e) or "実行できません" in str(e):
            raise
        raise MkciaError(f"{label} をメディアファイルとして読めません (壊れているか、非対応の形式です): {path}") from e
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise MkciaError(f"{label} の情報を解析できません: {path}") from e


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _streams(info: dict, kind: str) -> List[dict]:
    return [s for s in info.get("streams", []) if s.get("codec_type") == kind]


def _duration(info: dict) -> Optional[float]:
    d = _num(info.get("format", {}).get("duration"))
    if d is None:
        for s in info.get("streams", []):
            d = _num(s.get("duration"))
            if d is not None:
                break
    return d


@dataclass
class VideoInfo:
    width: int
    height: int
    duration: Optional[float]  # 秒。不明なら None
    fps: float  # 不明なら 0
    has_audio: bool


def validate_video(path: Path) -> VideoInfo:
    label = path.name
    info = _probe(path, label)
    vs = [s for s in _streams(info, "video") if s.get("disposition", {}).get("attached_pic") != 1]
    if not vs:
        if _streams(info, "audio"):
            raise MkciaError(f"{label} には映像がありません (音声のみのファイルです): {path}")
        raise MkciaError(f"{label} に映像ストリームがありません: {path}")
    v = vs[0]
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if w <= 0 or h <= 0:
        raise MkciaError(f"{label} の映像サイズを取得できません: {path}")
    dur = _duration(info)
    if dur is None:
        # 長さが分からない形式 (一部の webm など) / 静止画。実際のフレーム数で判断する
        cnt = _probe(path, label, ["-count_frames", "-select_streams", "v:0"])
        frames = int((_streams(cnt, "video") or [{}])[0].get("nb_read_frames") or 0)
        if frames <= 1:
            raise MkciaError(f"{label} は静止画か、フレームが 1 枚以下です (動画ではありません): {path}")
    elif dur < MIN_VIDEO_SEC:
        raise MkciaError(f"{label} が短すぎます ({dur:.2f} 秒。{MIN_VIDEO_SEC} 秒以上が必要です): {path}")
    num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
    d = _num(den) or 1.0
    fps = (_num(num) or 0.0) / d
    return VideoInfo(w, h, dur, fps, bool(_streams(info, "audio")))


def validate_image(path: Path) -> None:
    label = path.name
    info = _probe(path, label)
    vs = _streams(info, "video")
    if not vs:
        raise MkciaError(f"{label} は画像として読めません (画像ストリームがありません): {path}")
    w, h = int(vs[0].get("width") or 0), int(vs[0].get("height") or 0)
    if w <= 0 or h <= 0:
        raise MkciaError(f"{label} の画像サイズを取得できません: {path}")
    if w > MAX_IMAGE_SIDE or h > MAX_IMAGE_SIDE:
        raise MkciaError(f"{label} が大きすぎます ({w}x{h}。一辺 {MAX_IMAGE_SIDE}px 以下にしてください): {path}")


def validate_audio(path: Path) -> None:
    label = path.name
    info = _probe(path, label)
    if not _streams(info, "audio"):
        raise MkciaError(f"{label} に音声ストリームがありません: {path}")
    d = _duration(info)
    if d is not None and d <= 0:
        raise MkciaError(f"{label} の音声の長さが 0 です: {path}")


# ---------------------------------------------------------------- サイズ見積もり

def estimate_cia_bytes(duration_sec: Optional[float], video_kbps: int, audio_kbps: int) -> Optional[int]:
    """CIA サイズのおおまかな見積もり (動画のビットレート × 長さ。romfs/コード分は上乗せ)。"""
    if duration_sec is None:
        return None
    return int(duration_sec * (video_kbps + audio_kbps) * 1000 / 8) + 3_000_000


def check_size(duration_sec: Optional[float], video_kbps: int, audio_kbps: int) -> None:
    est = estimate_cia_bytes(duration_sec, video_kbps, audio_kbps)
    if est is not None and est > MAX_CIA_BYTES:
        raise MkciaError(
            f"動画が長すぎて CIA が 4GB (FAT32 の上限) を超えます (見積もり {est / 1e9:.1f}GB、"
            f"動画 {duration_sec / 60:.0f} 分)。動画を短くしてください"
        )


# ---------------------------------------------------------------- ELF / 出力 / ツール

def check_elf(path: Path) -> Path:
    """ROM 本体の ELF が 32bit リトルエンディアンの ARM ELF か確認する (makerom は不正な ELF でクラッシュする)。"""
    p = Path(path)
    if not p.exists():
        raise MkciaError(
            f"ROM 本体の ELF が見つかりません: {p}\n"
            " scripts/make-prebuilt.sh で prebuilt/mediaplayer.elf を作るか --elf で指定してください"
        )
    if p.is_dir():
        raise MkciaError(f"ROM 本体の ELF にディレクトリが指定されています: {p}")
    try:
        head = p.read_bytes()[:20]
    except OSError as e:
        raise MkciaError(f"ROM 本体の ELF を読めません: {p} ({e.strerror})") from e
    if len(head) < 20 or head[:4] != b"\x7fELF":
        raise MkciaError(f"ROM 本体の ELF が ELF 形式ではありません: {p}")
    ei_class, ei_data = head[4], head[5]
    (e_machine,) = struct.unpack_from("<H", head, 18)
    if ei_class != 1 or ei_data != 1 or e_machine != 40:
        raise MkciaError(f"ROM 本体の ELF が 3DS (32bit ARM リトルエンディアン) 向けではありません: {p}")
    return p


def check_output(output: Path, inputs: List[Path]) -> Path:
    """出力パスを確認する。作れない・入力を上書きしてしまう場合は MkciaError。"""
    out = Path(output)
    if out.suffix.lower() != ".cia":
        raise MkciaError(f"出力ファイルの拡張子は .cia にしてください: {out}")
    if out.is_dir():
        raise MkciaError(f"出力先がディレクトリです (ファイル名まで指定してください): {out}")
    try:
        out_resolved = out.resolve()
    except OSError:
        out_resolved = out.absolute()
    for i in inputs:
        try:
            same = i.resolve() == out_resolved
        except OSError:
            same = False
        if same:
            raise MkciaError(f"出力先が入力ファイルと同じです (上書きしてしまいます): {out}")
    parent = out.parent
    # 親が無ければ作れるか、あれば書けるかを確認 (実際に作るのは出力直前)
    probe = parent
    while not probe.exists():
        if probe.parent == probe:
            break
        probe = probe.parent
    if not probe.is_dir():
        raise MkciaError(f"出力先の親がディレクトリではありません: {probe}")
    if not os.access(probe, os.W_OK | os.X_OK):
        raise MkciaError(f"出力先ディレクトリに書き込めません: {probe}")
    return out


REQUIRED_TOOLS = ("ffmpeg", "ffprobe", "bannertool", "3dstool", "makerom")
REQUIRED_ENCODERS = ("libx264", "aac")


def check_tools() -> None:
    """必要な外部ツールと ffmpeg のエンコーダを最初にまとめて確認する (足りないものを全部挙げる)。"""
    missing = []
    for t in REQUIRED_TOOLS:
        try:
            find_tool(t)
        except MkciaError:
            missing.append(t)
    if missing:
        raise MkciaError(
            "必要な外部ツールが見つかりません: " + ", ".join(missing)
            + "\n  bannertool / 3dstool は scripts/setup-tools.sh で用意できます。"
            " makerom と ffmpeg/ffprobe は PATH に置いてください (MKCIA_TOOLS_DIR でも指定可)"
        )
    try:
        enc = run([find_tool("ffmpeg"), "-hide_banner", "-encoders"])
    except MkciaError:
        return  # 実行時に具体的なエラーになる
    names = {line.split()[1] for line in enc.splitlines() if len(line.split()) >= 2 and line.startswith(" ")}
    lacking = [e for e in REQUIRED_ENCODERS if e not in names]
    if lacking:
        raise MkciaError(
            "お使いの ffmpeg に必要なエンコーダがありません: " + ", ".join(lacking)
            + "\n  libx264 付きの ffmpeg を使ってください"
        )
