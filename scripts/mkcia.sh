#!/bin/bash
# 生成ツール (tool/mkcia) をどのカレントディレクトリからでも実行するラッパー。
exec env PYTHONPATH="$(dirname "$0")/../tool${PYTHONPATH:+:$PYTHONPATH}" python3 -m mkcia "$@"
