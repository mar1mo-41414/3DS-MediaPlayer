"""meta.json の読み込みと検証。

どんな値が来ても traceback にせず、「どのキーがどう悪いか」を MkciaError で返す。
"""

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .errors import MkciaError

REQUIRED = ("title", "title_id", "version", "publisher")
KNOWN_KEYS = REQUIRED + ("long_title", "product_code", "loop", "volume", "preset", "output")

# SMDH の文字数上限 (UTF-16 コード単位): short title 64 / long title 128 / publisher 64
MAX_TITLE = 64
MAX_LONG_TITLE = 128
MAX_PUBLISHER = 64
MAX_META_BYTES = 1_000_000
MAX_OUTPUT_NAME_BYTES = 200
_BAD_FILENAME_CHARS = set('<>:"/\\|?*')  # SD カード (FAT) に置けない文字 + パス区切り

_TID_RE = re.compile(r"^[0-9A-Fa-f]{16}$")
_VER_RE = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")  # \d は全角・アラビア数字も通すので ASCII のみ
_PRODUCT_RE = re.compile(r"^CTR-[A-Z]-[A-Z0-9]{4}$")


@dataclass
class Meta:
    title: str  # SMDH short title (ホームメニューの名前)
    long_title: str  # SMDH long title
    publisher: str
    title_id: str  # 16 桁 hex (大文字)
    version: tuple  # (major, minor, micro)
    product_code: str
    loop: bool
    volume: float
    preset: Optional[str] = None  # エンコードプリセット名 (None なら既定)。名前の妥当性は pipeline で確認
    output: Optional[str] = None  # 出力ファイル名 (必ず .cia で終わる。None ならテンプレート名)
    warnings: List[str] = field(default_factory=list)  # 未知のキーなど。エラーではないが知らせたいこと

    @property
    def unique_id(self) -> int:
        """title_id の bits 8..31 (RSF の TitleInfo/UniqueId)。"""
        return (int(self.title_id, 16) & 0xFFFFFFFF) >> 8


def _type_name(v) -> str:
    return {str: "文字列", bool: "真偽値", int: "整数", float: "小数", list: "配列", dict: "オブジェクト",
            type(None): "null"}.get(type(v), type(v).__name__)


def _get_str(data: dict, key: str, required: bool, default: str = "") -> str:
    v = data.get(key)
    if v is None:
        if required:
            raise MkciaError(f"meta.json の必須項目が不足しています: {key}")
        return default
    if not isinstance(v, str):
        raise MkciaError(f"meta.json の {key} は文字列で指定してください ({_type_name(v)}が渡されました: {v!r})")
    v = v.strip()
    if required and not v:
        raise MkciaError(f"meta.json の必須項目が空です: {key}")
    return v


def _check_text(key: str, text: str, max_units: int) -> None:
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise MkciaError(f"meta.json の {key} に制御文字 (改行・タブなど) は使えません: {text!r}")
    try:
        units = len(text.encode("utf-16-le", errors="strict")) // 2
    except UnicodeEncodeError as e:
        raise MkciaError(f"meta.json の {key} に不正な文字が含まれています: {text!r}") from e
    if units > max_units:
        raise MkciaError(f"meta.json の {key} が長すぎます ({units} 文字。{max_units} 文字以内にしてください)")


def _check_output_name(name: str) -> str:
    """出力ファイル名を検証して返す (.cia が無ければ付ける)。ディレクトリを指す名前は許さない。"""
    if not name:
        raise MkciaError("meta.json の output が空です (出力ファイル名を指定してください)")
    if name in (".", "..") or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise MkciaError(f"meta.json の output が不正なファイル名です: {name!r}")
    bad = sorted(c for c in set(name) if c in _BAD_FILENAME_CHARS)
    if bad:
        raise MkciaError(
            f"meta.json の output にファイル名に使えない文字があります: {' '.join(bad)}"
            " (ディレクトリは指定できません。出力先は --output-dir / -o で指定します)"
        )
    if name.endswith("."):
        raise MkciaError(f"meta.json の output が '.' で終わっています: {name!r}")
    if not name.lower().endswith(".cia"):
        name += ".cia"
    try:
        too_long = len(name.encode("utf-8")) > MAX_OUTPUT_NAME_BYTES
    except UnicodeEncodeError as e:
        raise MkciaError(f"meta.json の output に不正な文字が含まれています: {name!r}") from e
    if too_long:
        raise MkciaError(f"meta.json の output が長すぎます ({MAX_OUTPUT_NAME_BYTES} バイト以内にしてください)")
    if name.lower() == ".cia":
        raise MkciaError("meta.json の output にファイル名がありません (拡張子だけです)")
    return name


def parse_meta(data) -> Meta:
    if not isinstance(data, dict):
        raise MkciaError(f"meta.json の最上位はオブジェクト ({{...}}) にしてください ({_type_name(data)}が渡されました)")

    missing = [k for k in REQUIRED if data.get(k) is None]
    if missing:
        raise MkciaError("meta.json の必須項目が不足しています: " + ", ".join(missing))

    title = _get_str(data, "title", True)
    publisher = _get_str(data, "publisher", True)
    long_title = _get_str(data, "long_title", False, default=title) or title
    _check_text("title", title, MAX_TITLE)
    _check_text("long_title", long_title, MAX_LONG_TITLE)
    _check_text("publisher", publisher, MAX_PUBLISHER)

    raw_tid = data["title_id"]
    if not isinstance(raw_tid, str):
        raise MkciaError(
            f"meta.json の title_id は文字列で指定してください ({_type_name(raw_tid)}が渡されました。"
            ' 例: "000400000FF3A000")'
        )
    tid = raw_tid.strip().upper()
    tid = tid[2:] if tid.startswith("0X") else tid
    if not _TID_RE.match(tid):
        raise MkciaError(f"title_id は 16 桁の 16 進数で指定してください: {raw_tid!r}")
    if not tid.startswith("00040000") or not tid.endswith("00"):
        raise MkciaError(
            "title_id は 00040000xxxxxx00 形式 (アプリ用) にしてください"
            f" (例: 000400000FF3A000): {tid}"
        )

    raw_ver = data["version"]
    if not isinstance(raw_ver, str):
        raise MkciaError(
            f"meta.json の version は文字列で指定してください ({_type_name(raw_ver)}が渡されました。"
            ' 例: "1.0.0")'
        )
    m = _VER_RE.match(raw_ver.strip())
    if not m:
        raise MkciaError(f"version は 'メジャー.マイナー.マイクロ' 形式で指定してください (例: 1.0.0): {raw_ver!r}")
    version = tuple(int(x) for x in m.groups())
    if version[0] > 63 or version[1] > 63 or version[2] > 15:
        raise MkciaError("version の範囲は メジャー/マイナー 0-63、マイクロ 0-15 です")

    product = _get_str(data, "product_code", False, default="CTR-P-MPLY") or "CTR-P-MPLY"
    if not _PRODUCT_RE.match(product):
        raise MkciaError(f"product_code は 'CTR-P-XXXX' 形式にしてください: {product!r}")

    loop = data.get("loop")
    if loop is None:
        loop = False
    elif not isinstance(loop, bool):
        raise MkciaError(f"meta.json の loop は true / false で指定してください ({_type_name(loop)}が渡されました: {loop!r})")

    volume = data.get("volume")
    if volume is None:
        volume = 1.0
    elif isinstance(volume, bool) or not isinstance(volume, (int, float)):
        raise MkciaError(f"meta.json の volume は 0.0〜1.0 の数値で指定してください ({_type_name(volume)}が渡されました: {volume!r})")
    volume = float(volume)
    if not math.isfinite(volume) or not 0.0 <= volume <= 1.0:
        raise MkciaError(f"meta.json の volume は 0.0〜1.0 で指定してください: {volume}")

    preset = _get_str(data, "preset", False) or None
    output = _check_output_name(_get_str(data, "output", False)) if data.get("output") is not None else None

    warnings = [f"meta.json の未知のキーは無視します: {k}" for k in data if k not in KNOWN_KEYS]
    return Meta(
        title=title,
        long_title=long_title,
        publisher=publisher,
        title_id=tid,
        version=version,
        product_code=product,
        loop=loop,
        volume=volume,
        preset=preset,
        output=output,
        warnings=warnings,
    )


def load_meta(path: Path) -> Meta:
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise MkciaError(f"meta.json が見つかりません: {path}") from None
    except OSError as e:
        raise MkciaError(f"meta.json を読めません: {path} ({e.strerror})") from e
    if len(raw) > MAX_META_BYTES:
        raise MkciaError(f"meta.json が大きすぎます ({len(raw)} バイト): {path}")
    try:
        text = raw.decode("utf-8-sig")  # BOM 付きも許す
    except UnicodeDecodeError as e:
        raise MkciaError(f"meta.json は UTF-8 で保存してください: {path}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise MkciaError(f"meta.json の JSON が不正です ({e.lineno} 行 {e.colno} 列): {e.msg}") from e
    except RecursionError:
        raise MkciaError("meta.json の入れ子が深すぎます") from None
    return parse_meta(data)
