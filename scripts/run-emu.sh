#!/bin/bash
# .3dsx を AzaharPlus (仮想ディスプレイ :99) で動かす。
# 使い方: scripts/run-emu.sh start [app]       起動 (引数なしならゲーム一覧) (既存インスタンスは先に停止)
#         scripts/run-emu.sh shot <out.png>     スクリーンショット
#         scripts/run-emu.sh stop               停止
# 注意: timeout だけでは AppImage 配下の本体が残るので pkill で本体ごと落とす。
set -u
EMU="${AZAHAR_APPIMAGE:-$HOME/.local/AppImage/azaharplus-2126.0-A-linux.AppImage}"
export DISPLAY=:99
stop() { pkill -KILL -f '[m]ount_azahar.*/bin/azahar' 2>/dev/null; pkill -KILL -f '[a]zaharplus-2126.*AppImage' 2>/dev/null; sleep 1; }
case "${1:-}" in
start)
    stop
    pgrep -f 'Xvfb :99' >/dev/null || { setsid -f Xvfb :99 -screen 0 1280x800x24 >/dev/null 2>&1; sleep 2; }
    setsid -f "$EMU" ${2:+"$2"} >/dev/null 2>&1 ;;
shot) import -window root "${2:?out png}" ;;
stop) stop ;;
*) echo "usage: $0 start [app] | shot <png> | stop" >&2; exit 1 ;;
esac
