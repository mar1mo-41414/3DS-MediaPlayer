"""GUI のロジック層 (Tk に依存しない)。

テンプレートの一覧・作成・読み書き、素材の差し替え、バックグラウンドでの検証/ビルド実行を担う。
画面 (gui.py) はこの層を呼ぶだけの薄い作りにして、Tk 無しでテストできるようにしている。
"""

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import video
from .errors import MkciaError
from .meta import parse_meta
from .pipeline import BuildOptions, Resolved, build_cia, validate_inputs
from .proc import TEMPLATE_ROOT, Cancelled, find_tool, set_cancel_event
from .validate import (
    IMAGE_EXTS,
    SOUND_EXTS,
    VIDEO_EXTS,
    estimate_cia_bytes,
    validate_audio,
    validate_image,
    validate_video,
)


# ---------------------------------------------------------------- 素材の種類

@dataclass(frozen=True)
class AssetSpec:
    stem: str  # テンプレート内のファイル名 (拡張子を除く)
    label: str
    exts: Tuple[str, ...]
    required: bool
    kind: str  # "video" | "image" | "audio"


ASSETS: Tuple[AssetSpec, ...] = (
    AssetSpec("video", "動画", VIDEO_EXTS, True, "video"),
    AssetSpec("icon", "アイコン", IMAGE_EXTS, False, "image"),  # 無ければ動画から作る
    AssetSpec("bottom", "下画面の画像", IMAGE_EXTS, False, "image"),  # 同上
    AssetSpec("select_sound", "タイトル音", SOUND_EXTS, False, "audio"),
    AssetSpec("banner", "バナー画像", IMAGE_EXTS, False, "image"),
)
ASSET_BY_STEM: Dict[str, AssetSpec] = {a.stem: a for a in ASSETS}


# ---------------------------------------------------------------- プリセットの説明

PRESET_NOTES = {
    "light": "旧3DS向け。軽い (余裕あり)",
    "medium": "旧3DS推奨 (既定)。実機で滑らか",
    "high": "New 3DS向け。旧3DSでは音声が不安定",
    "standard": "New 3DS向け (24fps)",
}


def preset_label(name: str) -> str:
    p = video.PRESETS[name]
    return f"{name} — {p.width}x{p.height} / {p.fps}fps / {p.video_kbps}kbps ({PRESET_NOTES.get(name, '')})"


def preset_choices() -> List[Tuple[str, str]]:
    """[(プリセット名, 表示用ラベル)]。軽い順 (light < medium < high < standard)。"""
    order = ["light", "medium", "high", "standard"]
    names = [n for n in order if n in video.PRESETS] + [n for n in video.PRESETS if n not in order]
    return [(n, preset_label(n)) for n in names]


# ---------------------------------------------------------------- テンプレートのフォーム

@dataclass
class TemplateForm:
    """meta.json の編集用の値 (画面の入力欄に対応。文字列は未検証)。"""

    title: str = ""
    long_title: str = ""
    publisher: str = ""
    title_id: str = ""
    version: str = "1.0.0"
    product_code: str = ""
    loop: bool = False
    volume: float = 1.0
    preset: str = ""  # "" = 指定なし (既定のプリセット)
    output: str = ""  # "" = テンプレート名
    frame_at: str = ""  # "" = 自動 (埋め込み画像、無ければ長さの 15% の位置)。icon / bottom が無いときだけ使う

    def to_meta_dict(self) -> dict:
        """meta.json に書く辞書。空の任意項目は書かない。"""
        d = {
            "title": self.title.strip(),
            "publisher": self.publisher.strip(),
            "title_id": self.title_id.strip(),
            "version": self.version.strip(),
            "loop": bool(self.loop),
            "volume": round(float(self.volume), 3),
        }
        for key in ("long_title", "product_code", "preset", "output"):
            v = getattr(self, key).strip()
            if v:
                d[key] = v
        fa = self.frame_at.strip()
        if fa:
            try:
                d["frame_at"] = float(fa)
            except ValueError:
                d["frame_at"] = fa  # 文字列のまま渡して、parse_meta に「数値で」とエラーにさせる
        return d


_OPTIONAL_KEYS = ("long_title", "product_code", "preset", "output", "frame_at")


def validate_form(form: TemplateForm):
    """フォームの値を検証して Meta を返す。不正なら MkciaError (どの項目かを含む)。"""
    meta = parse_meta(form.to_meta_dict())
    if meta.preset and meta.preset not in video.PRESETS:
        raise MkciaError(f"preset が不正です: {meta.preset!r} (選べるのは {', '.join(video.PRESETS)})")
    return meta


def suggest_title_id(name: str, taken=()) -> str:
    """名前から、ホームブリュー用の範囲 (0x0F0000〜0x0FFFFF) の title_id を決める。使用済みは避ける。"""
    h = int(hashlib.sha1(name.encode("utf-8")).hexdigest(), 16)
    taken = {t.upper() for t in taken}
    for i in range(0x10000):
        unique = 0x0F0000 | ((h + i) & 0xFFFF)
        tid = f"00040000{unique << 8:08X}"
        if tid not in taken:
            return tid
    raise MkciaError("使える title_id がありません")


_BAD_NAME_CHARS = set('<>:"/\\|?*')


def check_template_name(name: str, root: Optional[Path] = None) -> str:
    """新規テンプレートのディレクトリ名を検証して返す。"""
    n = (name or "").strip()
    if not n:
        raise MkciaError("テンプレート名を入力してください")
    if n in (".", "..") or n.startswith(".") or any(ord(c) < 32 or ord(c) == 127 for c in n):
        raise MkciaError(f"テンプレート名が不正です: {n!r}")
    bad = sorted(c for c in set(n) if c in _BAD_NAME_CHARS)
    if bad:
        raise MkciaError(f"テンプレート名に使えない文字があります: {' '.join(bad)}")
    if len(n.encode("utf-8")) > 120:
        raise MkciaError("テンプレート名が長すぎます")
    if root is not None and (Path(root) / n).exists():
        raise MkciaError(f"同じ名前のテンプレートが既にあります: {n}")
    return n


# ---------------------------------------------------------------- テンプレートディレクトリ

def list_templates(root: Optional[Path] = None) -> List[str]:
    root = Path(root or TEMPLATE_ROOT)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "meta.json").exists())


def _read_json_dict(path: Path) -> Tuple[dict, Optional[str]]:
    """meta.json を辞書として読む。読めない場合は ({}, 理由)。"""
    try:
        raw = path.read_bytes().decode("utf-8-sig")
    except FileNotFoundError:
        return {}, None
    except (OSError, UnicodeDecodeError) as e:
        return {}, f"meta.json を読めません: {e}"
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, RecursionError) as e:
        return {}, f"meta.json が壊れています: {e}"
    if not isinstance(data, dict):
        return {}, "meta.json の最上位がオブジェクトではありません"
    return data, None


def _fmt_seconds(v) -> str:
    """meta.json の frame_at (数値) を入力欄用の文字列にする。数値でなければ空。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return ""
    return f"{v:g}"


def _as_text(v) -> str:
    return v if isinstance(v, str) else ("" if v is None else str(v))


class TemplateDir:
    def __init__(self, path: Path):
        self.path = Path(path)

    @property
    def name(self) -> str:
        return self.path.resolve().name

    @classmethod
    def create(cls, name: str, root: Optional[Path] = None) -> "TemplateDir":
        root = Path(root or TEMPLATE_ROOT)
        n = check_template_name(name, root)
        taken = [f.title_id for _, f in _all_forms(root)]
        d = root / n
        try:
            d.mkdir(parents=True)
        except OSError as e:
            raise MkciaError(f"テンプレートを作れません: {d} ({e.strerror})") from e
        t = cls(d)
        t.save_form(TemplateForm(title=n, publisher="", title_id=suggest_title_id(n, taken)), _skip_validation=True)
        return t

    # ---- meta.json
    def load_form(self) -> Tuple[TemplateForm, List[str]]:
        """meta.json をフォームとして読む (壊れていても既定値で開き、理由を返す)。"""
        data, problem = _read_json_dict(self.path / "meta.json")
        warnings = [problem] if problem else []
        vol = data.get("volume", 1.0)
        form = TemplateForm(
            title=_as_text(data.get("title")),
            long_title=_as_text(data.get("long_title")),
            publisher=_as_text(data.get("publisher")),
            title_id=_as_text(data.get("title_id")),
            version=_as_text(data.get("version")) or "1.0.0",
            product_code=_as_text(data.get("product_code")),
            loop=data.get("loop") if isinstance(data.get("loop"), bool) else False,
            volume=float(vol) if isinstance(vol, (int, float)) and not isinstance(vol, bool) else 1.0,
            preset=_as_text(data.get("preset")),
            output=_as_text(data.get("output")),
            frame_at=_fmt_seconds(data.get("frame_at")),
        )
        return form, warnings

    def save_form(self, form: TemplateForm, _skip_validation: bool = False) -> None:
        """検証して meta.json に保存する。GUI が知らないキーは保持する。"""
        if not _skip_validation:
            validate_form(form)
        raw, _ = _read_json_dict(self.path / "meta.json")
        new = form.to_meta_dict()
        for k in _OPTIONAL_KEYS:  # 空にした任意項目は消す
            if k not in new:
                raw.pop(k, None)
        raw.update(new)
        text = json.dumps(raw, ensure_ascii=False, indent=2) + "\n"
        fd, tmp = tempfile.mkstemp(prefix=".meta-", suffix=".tmp", dir=self.path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            umask = os.umask(0)
            os.umask(umask)
            os.chmod(tmp, 0o666 & ~umask)
            os.replace(tmp, self.path / "meta.json")
        except OSError as e:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise MkciaError(f"meta.json を保存できません: {e.strerror}") from e

    # ---- 素材
    def asset_candidates(self, stem: str) -> List[Path]:
        spec = ASSET_BY_STEM[stem]
        return [self.path / f"{stem}{e}" for e in spec.exts if (self.path / f"{stem}{e}").exists()
                or (self.path / f"{stem}{e}").is_symlink()]

    def find_asset(self, stem: str) -> Optional[Path]:
        """パイプラインが実際に使うファイル (拡張子の優先順で最初のもの)。"""
        c = self.asset_candidates(stem)
        return c[0] if c else None

    def set_asset(self, stem: str, src: Path) -> Path:
        """素材を差し替える。src を検証してからテンプレートへコピーし、同じ種類の古いファイルを消す。"""
        spec = ASSET_BY_STEM[stem]
        src = Path(src)
        if not src.exists():
            raise MkciaError(f"ファイルが見つかりません: {src}")
        if not src.is_file():
            raise MkciaError(f"ファイルを選んでください (ディレクトリです): {src}")
        ext = src.suffix.lower()
        if ext not in spec.exts:
            raise MkciaError(f"{spec.label}に使えない拡張子です ({ext or 'なし'})。使えるのは {' '.join(spec.exts)}")
        if src.stat().st_size == 0:
            raise MkciaError(f"{src.name} が空 (0 バイト) です")
        dest = self.path / f"{stem}{ext}"
        try:
            if dest.exists() and src.resolve() == dest.resolve():
                return dest  # 既にそのファイル
        except OSError:
            pass
        describe_file(spec.kind, src)  # 読めないファイルはコピー前に弾く (テンプレートを壊さない)
        fd, tmp = tempfile.mkstemp(prefix=f".{stem}-", suffix=".tmp", dir=self.path)
        os.close(fd)
        try:
            shutil.copyfile(src, tmp)
            for old in self.asset_candidates(stem):  # 拡張子違いの古い素材が優先されないよう消す
                old.unlink()
            os.replace(tmp, dest)
        except OSError as e:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise MkciaError(f"{src.name} をコピーできません: {e.strerror}") from e
        return dest

    def remove_asset(self, stem: str) -> None:
        if ASSET_BY_STEM[stem].required:
            raise MkciaError(f"{ASSET_BY_STEM[stem].label}は必須なので削除できません")
        for p in self.asset_candidates(stem):
            p.unlink()

    def describe_asset(self, stem: str) -> str:
        p = self.find_asset(stem)
        if p is None:
            if ASSET_BY_STEM[stem].required:
                return "未設定 (必須)"
            if stem in ("icon", "bottom"):
                return "未設定 (ビルド時に動画から作る)"
            if stem == "select_sound":
                return "未設定 (既定のタイトル選択音を使う)"
            return "未設定"
        try:
            return f"{p.name} — " + describe_file(ASSET_BY_STEM[stem].kind, p)
        except MkciaError as e:
            return f"{p.name} — 問題あり: {e}"


def _all_forms(root: Path):
    for n in list_templates(root):
        yield n, TemplateDir(Path(root) / n).load_form()[0]


def title_id_conflicts(title_id: str, root: Optional[Path] = None, exclude: Optional[str] = None) -> List[str]:
    """同じ title_id を使っている他のテンプレート名 (同時にインストールすると上書きし合う)。"""
    tid = (title_id or "").strip().upper()
    if not tid:
        return []
    return [n for n, f in _all_forms(Path(root or TEMPLATE_ROOT)) if n != exclude and f.title_id.strip().upper() == tid]


def _fmt_duration(sec: Optional[float]) -> str:
    if sec is None:
        return "長さ不明"
    if sec < 10:
        return f"{sec:.1f}秒"
    s = int(round(sec))
    return f"{s // 60}:{s % 60:02d}"


def describe_file(kind: str, path: Path) -> str:
    """素材の簡単な説明 (読めないファイルは MkciaError)。"""
    if kind == "video":
        v = validate_video(path)
        fps = f" / {v.fps:.1f}fps" if v.fps > 0 else ""
        return f"{v.width}x{v.height}{fps} / {_fmt_duration(v.duration)} / {'音声あり' if v.has_audio else '音声なし'}"
    if kind == "image":
        w, h = validate_image(path)
        return f"{w}x{h}"
    return f"{_fmt_duration(validate_audio(path))}"


def estimate_size_text(duration: Optional[float], preset_name: str) -> str:
    p = video.PRESETS.get(preset_name or video.DEFAULT_PRESET)
    est = estimate_cia_bytes(duration, p.video_kbps, p.audio_kbps) if p else None
    return "不明" if est is None else f"約 {est / 1_000_000:.1f} MB"


# ---------------------------------------------------------------- サムネイル

def make_thumbnail(path: Path, max_side: int = 96, seek: float = 0.0) -> Optional[bytes]:
    """画像/動画の 1 コマを PNG のバイト列で返す (失敗は None)。Tk の PhotoImage(data=...) に渡せる。"""
    try:
        cmd = [find_tool("ffmpeg"), "-v", "error"]
        if seek:
            cmd += ["-ss", str(seek)]
        cmd += ["-i", str(path), "-frames:v", "1", "-vf",
                f"scale={max_side}:{max_side}:force_original_aspect_ratio=decrease",
                "-f", "image2pipe", "-c:v", "png", "-"]
        r = subprocess.run(cmd, capture_output=True, timeout=30)
    except (MkciaError, OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 and r.stdout.startswith(b"\x89PNG") else None


# ---------------------------------------------------------------- バックグラウンド実行

_STAGE_RE = re.compile(r"^\[(\d+)/(\d+)\]\s*(.*)")


class Job:
    """検証/ビルドを別スレッドで走らせ、進捗を queue に流す (GUI が定期的に取り出す)。

    イベント: ("log", 文字列) / ("stage", 現在, 全体, 説明) /
              ("done", 結果) / ("cancelled",) / ("error", メッセージ) / ("crash", トレースバック)
    同時に走らせるのは 1 つだけ (中止要求がモジュール全体の状態のため)。
    """

    def __init__(self, target: Callable[[Callable[[str], None]], object]):
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self._target = target
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "Job":
        self._thread.start()
        return self

    def cancel(self) -> None:
        self._cancel.set()

    def is_running(self) -> bool:
        return self._thread.is_alive()

    def join(self, timeout: Optional[float] = None) -> None:
        self._thread.join(timeout)

    def _log(self, msg: str) -> None:
        self.events.put(("log", msg))
        m = _STAGE_RE.match(msg)
        if m:
            self.events.put(("stage", int(m.group(1)), int(m.group(2)), m.group(3)))

    def _run(self) -> None:
        set_cancel_event(self._cancel)
        try:
            self.events.put(("done", self._target(self._log)))
        except Cancelled:
            self.events.put(("cancelled",))
        except MkciaError as e:
            self.events.put(("error", str(e)))
        except BaseException:  # スレッドを黙って落とさず、GUI に伝える
            self.events.put(("crash", traceback.format_exc()))
        finally:
            set_cancel_event(None)


def start_build(options: BuildOptions) -> Job:
    return Job(lambda log: build_cia(options, log)).start()


def summarize_validation(r: Resolved) -> str:
    v = r.video_info
    p = video.PRESETS[r.preset]
    return "\n".join([
        f"テンプレート: {r.files.root.name}",
        f"プリセット: {r.preset} ({p.width}x{p.height} / {p.fps}fps / {p.video_kbps}kbps)",
        f"動画: {v.width}x{v.height} / {_fmt_duration(v.duration)} / {'音声あり' if v.has_audio else '音声なし'}",
        f"出力: {r.output}",
        f"CIA サイズの見積もり: {estimate_size_text(v.duration, r.preset)}",
    ])


def start_validation(options: BuildOptions) -> Job:
    """ビルドせず、入力・出力先・ツールの検証だけ行う (結果は summarize_validation の文字列)。"""
    return Job(lambda log: summarize_validation(validate_inputs(options, log))).start()


def open_folder(path: Path) -> bool:
    """ファイルマネージャでフォルダを開く。開けなければ False。"""
    path = Path(path)
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
