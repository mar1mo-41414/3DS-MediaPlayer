"""動画の事前エンコード (PC 上の ffmpeg)。

3DS (ARM11 268MHz) のソフトウェアデコードで間に合うよう、解像度・fps・ビットレートは
プリセットで固定する。ユーザー入力は選ぶだけで、上限を超える値は指定できない。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .errors import MkciaError
from .proc import Cancelled, Log, find_tool, run
from .validate import VideoInfo, validate_video


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
    # 旧3DS向けの中間: ビットレートを上げて画質を改善 (エミュレータ上のデコード時間が light 比 +5% / +13%。
    # デブロッキングは負荷に見合わず無効)。実機 (旧3DS): medium は滑らか、high は再生できるが
    # デコードが再生速度ぎりぎりで音声が少し間延びする → high は New 3DS 向け
    "medium": VideoPreset(width=360, height=216, fps=20, video_kbps=400, audio_kbps=48, audio_rate=32000),
    "high": VideoPreset(width=400, height=240, fps=20, video_kbps=400, audio_kbps=48, audio_rate=32000),
    # New 3DS 向け
    "standard": VideoPreset(width=400, height=240, fps=24, video_kbps=350, audio_kbps=64, audio_rate=32000),
}
DEFAULT_PRESET = "medium"  # 旧3DS の実機で滑らかに再生できることを確認済みの最上位


def get_preset(name: str) -> VideoPreset:
    if name not in PRESETS:
        raise MkciaError(f"不明なプリセット: {name!r} (選べるのは {', '.join(PRESETS)})")
    return PRESETS[name]


def probe(src: Path) -> VideoInfo:
    """動画を検証して映像 fps・音声有無などを返す。読めない・動画でない場合は MkciaError。"""
    return validate_video(src)


def video_filter(p: VideoPreset, fps: int) -> str:
    """スケール・余白埋めのフィルタ文字列。

    画素が正方形でない動画 (SAR != 1) は、先に表示上の幅に直してからフィットさせる。
    """
    return (
        "scale='trunc(iw*sar/2)*2':ih,setsar=1,"
        f"scale={p.width}:{p.height}:force_original_aspect_ratio=decrease:flags=bicubic,"
        f"pad={p.width}:{p.height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={fps},format=yuv420p"
    )


def encode_video(
    src: Path,
    dst: Path,
    preset: str = DEFAULT_PRESET,
    log: Optional[Log] = None,
    info: Optional[VideoInfo] = None,
) -> Path:
    """src を 3DS 向け (H.264 Baseline / AAC-LC の MP4) に変換して dst に出力する。"""
    p = get_preset(preset)
    info = info or probe(src)
    fps = p.fps if info.fps <= 0 else max(1, min(p.fps, round(info.fps)))

    cmd = [
        find_tool("ffmpeg"), "-v", "error", "-y", "-i", src,
        "-map", "0:v:0", "-vf", video_filter(p, fps),
        "-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0",
        "-preset", "slow", "-b:v", f"{p.video_kbps}k",
        "-maxrate", f"{p.video_kbps * 3 // 2}k", "-bufsize", f"{p.video_kbps * 3}k",
        "-refs", "1", "-bf", "0", "-g", str(fps * 2),
        # ROM 側は (deblock=false のとき) デブロッキングを省いて軽くするので、エンコード側でも無効にしてドリフトを防ぐ
        "-x264-params", ("" if p.deblock else "no-deblock=1:") + "cabac=0:weightp=0",
    ]
    if info.has_audio:
        cmd += [
            "-map", "0:a:0", "-c:a", "aac", "-b:a", f"{p.audio_kbps}k",
            "-ar", str(p.audio_rate), "-ac", "2",
        ]
    else:
        cmd += ["-an"]
    cmd += ["-movflags", "+faststart", dst]
    try:
        run(cmd, log)
    except Cancelled:
        raise
    except MkciaError as e:
        raise MkciaError(f"{Path(src).name} のエンコードに失敗しました:\n{e}") from e
    if not Path(dst).is_file() or Path(dst).stat().st_size == 0:
        raise MkciaError(f"{Path(src).name} のエンコード結果が空です (映像データを読み出せませんでした)")
    return dst
