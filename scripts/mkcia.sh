#!/bin/bash
# 生成ツール (tool/mkcia) をどのカレントディレクトリからでも実行するラッパー。
# 使う Python は環境変数 PYTHON で変えられる (既定: python3)。
exec env PYTHONPATH="$(dirname "$0")/../tool${PYTHONPATH:+:$PYTHONPATH}" "${PYTHON:-python3}" -m mkcia "$@"
