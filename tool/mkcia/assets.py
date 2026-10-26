"""画像・音声の整形 (icon / banner / 下画面 / 選択音)。いずれも ffmpeg で処理する。"""

from pathlib import Path
from typing import Optional

from .proc import Log, find_tool, run


def _ffmpeg(args, log: Optional[Log]):
    run([find_tool("ffmpeg"), "-v", "error", "-y", *args], log)


def _fit(src: Path, dst: Path, w: int, h: int, bg: str, log: Optional[Log]) -> Path:
    """アスペクト比を保って w x h に収め、余白は bg で埋めた PNG を出力する。"""
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={bg},format=rgba"
    )
    _ffmpeg(["-i", src, "-vf", vf, "-frames:v", "1", dst], log)
    return dst


def make_icon(src: Path, dst: Path, log: Optional[Log] = None, crop_square: bool = False) -> Path:
    """ホームメニュー用アイコン (48x48)。

    crop_square=True なら中央を正方形に切り抜いて拡縮する (動画のフレームから作るときは、横長のまま縮めると
    小さな帯になってしまうため)。False なら余白付きで全体を収める。
    """
    if not crop_square:
        return _fit(src, dst, 48, 48, "black@0", log)
    _ffmpeg(["-i", src, "-vf", "crop='min(iw,ih)':'min(iw,ih)',scale=48:48:flags=lanczos,format=rgba",
             "-frames:v", 1, dst], log)
    return dst


def make_banner_image(src: Path, dst: Path, log: Optional[Log] = None) -> Path:
    """バナー画像 (256x128)。"""
    return _fit(src, dst, 256, 128, "black", log)


def make_bottom_image(src: Path, dst: Path, log: Optional[Log] = None) -> Path:
    """下画面用の静止画 (320x240)。"""
    return _fit(src, dst, 320, 240, "black", log)


BANNER_AUDIO_MAX_SEC = 3
BANNER_AUDIO_FADE_SEC = 0.3


def make_banner_audio(src: Optional[Path], dst: Path, log: Optional[Log] = None) -> Path:
    """アイコン選択音 (16bit PCM WAV, 最大 3 秒)。src が無ければ無音。

    src は ffmpeg が読める音声ならよい (wav / mp3 / ogg / flac ...)。3 秒を超える分は切り捨て、
    切り口のプチ音を避けるため末尾にフェードアウトを掛ける。
    """
    fade = f"afade=t=out:st={BANNER_AUDIO_MAX_SEC - BANNER_AUDIO_FADE_SEC}:d={BANNER_AUDIO_FADE_SEC}"
    common = ["-t", str(BANNER_AUDIO_MAX_SEC), "-af", fade, "-ar", "32000", "-ac", "2", "-c:a", "pcm_s16le", dst]
    if src is None:
        _ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=32000:cl=stereo", "-t", "0.1", "-c:a", "pcm_s16le", dst], log)
    else:
        _ffmpeg(["-i", src, *common], log)
    return dst
