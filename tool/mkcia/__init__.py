"""3DS 動画再生 CIA の生成ツール。

各段 (動画エンコード / banner+SMDH / romfs / CIA) は独立した関数で、
`pipeline.build_cia` がそれらを順に呼ぶ。将来 GUI からも同じ関数を呼べる。
"""

from .errors import MkciaError
from .pipeline import BuildOptions, build_cia

__all__ = ["MkciaError", "BuildOptions", "build_cia"]
