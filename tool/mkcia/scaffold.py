"""テンプレートの雛形生成 (`mkcia --new NAME`)。

`template/example` をコピーして、名前とタイトルIDだけを新しいものにする。タイトル選択音はコピーしない (既定の音になる)。
コピーした時点でそのままビルドできるので、動かしながら素材と meta.json を差し替えていける。
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from .errors import MkciaError
from .gui_model import _all_forms, check_template_name, suggest_title_id
from .meta import parse_meta

EXAMPLE_NAME = "example"
# 新しいテンプレートでは使わない (雛形の名前・出力名のままだと紛らわしい) キー
_DROP_KEYS = ("long_title", "output")


def create_from_example(name: str, root: Path, example: str = EXAMPLE_NAME) -> Path:
    """root/example を root/<name> にコピーし、title と title_id を新しくして、作ったディレクトリを返す。"""
    root = Path(root)
    n = check_template_name(name, root)
    src = root / example
    if not (src / "meta.json").is_file():
        raise MkciaError(
            f"雛形のテンプレートが見つかりません: {src}\n"
            "  (template/example をコピーして作るので、template/example が必要です)"
        )
    dest = root / n

    taken = [form.title_id for _, form in _all_forms(root)]
    tmp = Path(tempfile.mkdtemp(prefix=f".{n}-", suffix=".tmp", dir=root))
    try:
        work = tmp / "new"
        # リンクは中身をコピーする (雛形の外を指さない)。タイトル選択音 (select_sound.*) は引き継がず、既定の音を使わせる
        shutil.copytree(src, work, ignore=shutil.ignore_patterns("select_sound.*"))
        raw = json.loads((work / "meta.json").read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise MkciaError(f"雛形の meta.json の最上位がオブジェクトではありません: {src / 'meta.json'}")
        raw["title"] = n
        raw["title_id"] = suggest_title_id(n, taken)
        for k in _DROP_KEYS:
            raw.pop(k, None)
        parse_meta(raw)  # 雛形が壊れていたら、作る前に気づく
        (work / "meta.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if dest.exists():  # check_template_name の後に作られた場合の競合も拒否する
            raise MkciaError(f"同じ名前のテンプレートが既にあります: {n}")
        os.rename(work, dest)
    except MkciaError:
        raise
    except (OSError, ValueError) as e:  # ValueError: 雛形の meta.json が JSON として壊れている
        raise MkciaError(f"テンプレートを作れません: {dest} ({getattr(e, 'strerror', None) or e})") from e
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dest
