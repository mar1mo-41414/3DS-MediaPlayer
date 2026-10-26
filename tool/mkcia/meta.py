"""meta.json の読み込みと必須項目チェック。"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .errors import MkciaError

REQUIRED = ("title", "title_id", "version", "publisher")

_TID_RE = re.compile(r"^[0-9A-Fa-f]{16}$")
_VER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
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

    @property
    def unique_id(self) -> int:
        """title_id の bits 8..31 (RSF の TitleInfo/UniqueId)。"""
        return (int(self.title_id, 16) & 0xFFFFFFFF) >> 8


def parse_meta(data: dict) -> Meta:
    missing = [k for k in REQUIRED if not str(data.get(k, "")).strip()]
    if missing:
        raise MkciaError("meta.json の必須項目が不足しています: " + ", ".join(missing))

    tid = str(data["title_id"]).strip().upper().removeprefix("0X")
    if not _TID_RE.match(tid):
        raise MkciaError(f"title_id は 16 桁の 16 進数で指定してください: {data['title_id']!r}")
    if not tid.startswith("00040000") or not tid.endswith("00"):
        raise MkciaError(
            "title_id は 00040000xxxxxx00 形式 (アプリ用) にしてください"
            f" (例: 000400000FF3A000): {tid}"
        )

    m = _VER_RE.match(str(data["version"]).strip())
    if not m:
        raise MkciaError(f"version は 'メジャー.マイナー.マイクロ' 形式で指定してください (例: 1.0.0): {data['version']!r}")
    version = tuple(int(x) for x in m.groups())
    if version[0] > 63 or version[1] > 63 or version[2] > 15:
        raise MkciaError("version の範囲は メジャー/マイナー 0-63、マイクロ 0-15 です")

    title = str(data["title"]).strip()
    product = str(data.get("product_code", "CTR-P-MPLY")).strip()
    if not _PRODUCT_RE.match(product):
        raise MkciaError(f"product_code は 'CTR-P-XXXX' 形式にしてください: {product!r}")

    volume = float(data.get("volume", 1.0))
    if not 0.0 <= volume <= 1.0:
        raise MkciaError("volume は 0.0〜1.0 で指定してください")

    return Meta(
        title=title,
        long_title=str(data.get("long_title") or title).strip(),
        publisher=str(data["publisher"]).strip(),
        title_id=tid,
        version=version,
        product_code=product,
        loop=bool(data.get("loop", False)),
        volume=volume,
    )


def load_meta(path: Path) -> Meta:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise MkciaError(f"meta.json が見つかりません: {path}") from None
    except json.JSONDecodeError as e:
        raise MkciaError(f"meta.json の JSON が不正です: {e}") from e
    if not isinstance(data, dict):
        raise MkciaError("meta.json の最上位はオブジェクトにしてください")
    return parse_meta(data)
