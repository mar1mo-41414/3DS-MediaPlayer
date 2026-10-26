#!/bin/bash
# 生成ツールの GUI (Tkinter) を起動する。要: python3-tk
exec env PYTHONPATH="$(dirname "$0")/../tool${PYTHONPATH:+:$PYTHONPATH}" python3 -m mkcia.gui "$@"
