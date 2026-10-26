"""動画の事前エンコード (PC 上の ffmpeg)。

3DS (ARM11 268MHz) のソフトウェアデコードで間に合うよう、解像度・fps・ビットレートは
プリセットで固定する。ユーザー入力は選ぶだけで、上限を超える値は指定できない。
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .errors import MkciaError
from .proc import Log, find_tool, run

@dataclass(frozen=True)
class VideoPreset:
    width: int  # ROM 側は 8 の倍数・512x256 以下を要求。上画面 (400x240) へは ROM が拡大して表示する
    height: int
    fps: int  # 上限 (元動画がこれより低ければ元に合わせる)
    video_kbps: int
    audio_kbps: int
    audio_rate: int
    deblock: bool = False  # True: ストリームのデブロッキングを有効に (ROM 側も config の deblock で有効化)


PRESETS = {
    # 旧3DS向け: 低解像度でデコードして ROM 側で全画面に拡大 (5:3 のまま)
    "light": VideoPreset(width=320, height=192, fps=20, video_kbps=250, audio_kbps=48, audio_rate=32000),
    # 旧3DS向けの中間: ビットレートを上げて画質を改善 (旧3DS・実機で light が滑らかだったのを基準に、
    # エミュレータ上のデコード時間が light 比 +5% / +13% のもの。デブロッキングは負荷に見合わず無効)
    "medium": VideoPreset(width=360, height=216, fps=20, video_kbps=400, audio_kbps=48, audio_rate=32000),
    "high": VideoPreset(width=400, height=240, fps=20, video_kbps=400, audio_kbps=48, audio_rate=32000),
    # New 3DS 向け
    "standard": VideoPreset(width=400, height=240, fps=24, video_kbps=350, audio_kbps=64, audio_rate=32000),
}
DEFAULT_PRESET = "standard"


def probe(src: Path) -> dict:
    """ffprobe で映像 fps と音声有無を調べる。"""
    out = run(
        [find_tool("ffprobe"), "-v", "error", "-show_streams", "-of", "json", src],
    )
    streams = json.loads(out).get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if v is None:
        raise MkciaError(f"動画ストリームが見つかりません: {src}")
    num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    return {
        "fps": fps,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def encode_video(
    src: Path,
    dst: Path,
    preset: str = DEFAULT_PRESET,
    log: Optional[Log] = None,
) -> Path:
    """src を 3DS 向け (400x240 / H.264 Baseline / AAC-LC の MP4) に変換して dst に出力する。"""
    if preset not in PRESETS:
        raise MkciaError(f"不明なプリセット: {preset} ({', '.join(PRESETS)})")
    p = PRESETS[preset]
    info = probe(src)
    fps = p.fps if info["fps"] <= 0 else min(p.fps, round(info["fps"]))

    vf = (
        f"scale={p.width}:{p.height}:force_original_aspect_ratio=decrease:flags=bicubic,"
        f"pad={p.width}:{p.height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={fps},format=yuv420p"
    )
    cmd = [
        find_tool("ffmpeg"), "-v", "error", "-y", "-i", src,
        "-map", "0:v:0", "-vf", vf,
        "-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0",
        "-preset", "slow", "-b:v", f"{p.video_kbps}k",
        "-maxrate", f"{p.video_kbps * 3 // 2}k", "-bufsize", f"{p.video_kbps * 3}k",
        "-refs", "1", "-bf", "0", "-g", str(fps * 2),
        # ROM 側はデブロッキングを省いて軽くするので、エンコード側でも無効にしてドリフトを防ぐ
        "-x264-params", ("" if p.deblock else "no-deblock=1:") + "cabac=0:weightp=0",
    ]
    if info["has_audio"]:
        cmd += [
            "-map", "0:a:0", "-c:a", "aac", "-b:a", f"{p.audio_kbps}k",
            "-ar", str(p.audio_rate), "-ac", "2",
        ]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", dst]
    run(cmd, log)
    return dst
