"""一時ファイル / 一時ディレクトリを「普通の権限」で作る。

tempfile.mkstemp / mkdtemp は所有者専用 (0600 / 0700) で作る。Python 3.12 以降の Windows では
ACL も所有者だけに絞られ、`os.replace` / `rename` で本来の名前に置き換えた後もそのまま残る
(別の権限のプロセスから読めない、フォルダの権限が親から継承されない)。
最終的な成果物 (CIA / meta.json / 素材 / テンプレート) になる一時物は、ここの関数で作る。
"""

import os
import secrets
from pathlib import Path

_TRIES = 100


def _candidate(directory: Path, prefix: str, suffix: str) -> Path:
    return Path(directory) / f"{prefix}{secrets.token_hex(4)}{suffix}"


def create_tmp_file(directory: Path, prefix: str = "", suffix: str = "") -> Path:
    """directory に空の一時ファイルを排他的に作って、そのパスを返す (権限は通常のファイルと同じ)。"""
    for _ in range(_TRIES):
        p = _candidate(directory, prefix, suffix)
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError:
            continue
        os.close(fd)
        return p
    raise FileExistsError(f"一時ファイルの名前を決められません: {directory}")


def create_tmp_dir(directory: Path, prefix: str = "", suffix: str = "") -> Path:
    """directory に一時ディレクトリを作って、そのパスを返す (権限は通常のディレクトリと同じ)。"""
    for _ in range(_TRIES):
        p = _candidate(directory, prefix, suffix)
        try:
            os.mkdir(p)
        except FileExistsError:
            continue
        return p
    raise FileExistsError(f"一時ディレクトリの名前を決められません: {directory}")
