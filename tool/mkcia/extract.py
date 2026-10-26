"""テンプレートに icon / bottom が無いとき、動画から画像を作る。

優先順位: 動画に埋め込まれた画像 (カバーアート。mkv の添付画像や mp4 のカバーなど) → 指定した秒数のフレーム。
`frame_at` (秒) を明示したときは、埋め込み画像があってもその秒数のフレームを使う。
"""

from pathlib import Path
from typing import List, Optional, Tuple

from .errors import MkciaError
from .proc import Log, find_tool, run
from .validate import VideoInfo, probe_json, validate_image

AUTO_RATIO = 0.15  # 自動のときは動画の長さのこの割合の位置 (冒頭の暗転やロゴを避ける)
AUTO_MAX_SEC = 30.0
FALLBACK_SEC = 1.0  # 長さが分からない動画のときの位置


def auto_frame_time(duration: Optional[float]) -> float:
    if duration is None:
        return FALLBACK_SEC
    return min(duration * AUTO_RATIO, AUTO_MAX_SEC)


def embedded_image_indexes(video: Path) -> List[int]:
    """動画の中の埋め込み画像 (attached_pic) のストリーム番号。名前に cover を含むものを先にする。"""
    info = probe_json(video)
    cands = []
    for s in info.get("streams", []):
        if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") == 1:
            name = (s.get("tags") or {}).get("filename", "").lower()
            cands.append((0 if "cover" in name else 1, int(s["index"])))
    return [i for _, i in sorted(cands)]


def extract_embedded(video: Path, work: Path, log: Optional[Log] = None) -> Optional[Path]:
    """埋め込み画像を取り出す。無い・読めないなら None。"""
    for idx in embedded_image_indexes(video):
        dst = work / f"embedded{idx}.png"
        try:
            run([find_tool("ffmpeg"), "-v", "error", "-y", "-i", video, "-map", f"0:{idx}", "-frames:v", 1, dst], log)
            validate_image(dst)
        except MkciaError:
            continue  # 壊れた埋め込み画像は無視して、次の候補 / フレーム抽出に進む
        return dst
    return None


def extract_frame(video: Path, at_sec: float, dst: Path, log: Optional[Log] = None) -> Path:
    """動画の at_sec 秒のフレームを PNG にする (回転・非正方画素は補正済み)。"""
    run([find_tool("ffmpeg"), "-v", "error", "-y", "-ss", f"{at_sec:.3f}", "-i", video, "-map", "0:V:0",
         "-frames:v", 1, "-vf", "scale='trunc(iw*sar/2)*2':ih,setsar=1", dst], log)
    if not dst.is_file() or dst.stat().st_size == 0:
        raise MkciaError(f"動画の {at_sec:g} 秒のフレームを取り出せませんでした (動画の長さを超えていませんか?)")
    return dst


def check_frame_at(frame_at: Optional[float], info: VideoInfo) -> None:
    """frame_at が動画の長さの範囲内か確認する (長さが不明なら確認できないので通す)。"""
    if frame_at is not None and info.duration is not None and frame_at >= info.duration:
        raise MkciaError(
            f"frame_at ({frame_at:g} 秒) が動画の長さ ({info.duration:.1f} 秒) 以上です。"
            " 動画の途中の秒数を指定してください"
        )


def source_image(video: Path, info: VideoInfo, frame_at: Optional[float], work: Path,
                 log: Optional[Log] = None) -> Tuple[Path, str]:
    """icon / bottom の元にする画像と、その説明 (ログ用) を返す。"""
    if frame_at is None:
        emb = extract_embedded(video, work, log)
        if emb is not None:
            return emb, "動画の埋め込み画像"
    at = auto_frame_time(info.duration) if frame_at is None else frame_at
    check_frame_at(at, info)
    path = extract_frame(video, at, work / "frame.png", log)
    validate_image(path)
    return path, f"動画の {at:.1f} 秒のフレーム" + ("" if frame_at is not None else " (自動)")
