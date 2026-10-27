#!/bin/bash
# 生成ツールの GUI (Tkinter) を起動する。要: tkinter が使える Python (入れ方: docs/JA/USAGE.md の GUI)。
# 使う Python は環境変数 PYTHON で変えられる (既定: python3)。例: PYTHON=python3.14 scripts/mkcia-gui.sh
exec env PYTHONPATH="$(dirname "$0")/../tool${PYTHONPATH:+:$PYTHONPATH}" "${PYTHON:-python3}" -m mkcia.gui "$@"
