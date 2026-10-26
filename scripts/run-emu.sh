#!/bin/bash
# 3DS エミュレータ (Azahar 系) で .3dsx / .cia を動かし、画面を撮る開発用ヘルパー。
# 仮想ディスプレイ (Xvfb) 上で動かすので、画面の無い環境でも使える。
#
# 使い方: scripts/run-emu.sh start [app]       起動 (引数なしならゲーム一覧)。既存のインスタンスは先に停止
#         scripts/run-emu.sh shot <out.png>     スクリーンショット (要 ImageMagick の import)
#         scripts/run-emu.sh stop               このスクリプトが起動したエミュレータを停止
#
# 環境変数:
#   AZAHAR        エミュレータの実行ファイル / AppImage (未指定なら PATH 上の azahar* を探す)
#   EMU_DISPLAY   使う X ディスプレイ (既定 :99。無ければ Xvfb を起動する)
#
# 停止は「起動時に付けた目印の環境変数 (MKCIA_EMU_TAG) を持つプロセス」だけを対象にする
# (timeout だけでは AppImage 配下の本体が残るため。他の Azahar を巻き込まない)。
set -u
export DISPLAY="${EMU_DISPLAY:-:99}"

find_emu() {
    if [ -n "${AZAHAR:-}" ]; then echo "$AZAHAR"; return; fi
    for c in azahar azahar-qt azaharplus; do command -v "$c" && return; done
    ls "$HOME"/.local/AppImage/azahar*.AppImage 2>/dev/null | head -1
}

# /proc/<pid>/environ は他ユーザーのプロセスだと読めない (リダイレクト自体のエラーなので { } ごと 2>/dev/null)
tagged() { { tr '\0' '\n' < "$1/environ"; } 2>/dev/null | grep -q '^MKCIA_EMU_TAG=1$'; }

stop() {
    local p
    for p in /proc/[0-9]*; do
        tagged "$p" || continue
        # AppImage の読み取り専用マウントを担う補助プロセスは、落とすとマウントが残るので触らない
        { tr '\0' ' ' < "$p/cmdline"; } 2>/dev/null | grep -qE '^(dwarfs|squashfuse)' && continue
        kill -KILL "${p#/proc/}" 2>/dev/null
    done
    sleep 1
}

case "${1:-}" in
start)
    emu="$(find_emu)"
    [ -n "$emu" ] || { echo "エミュレータが見つかりません。AZAHAR=/path/to/azahar を指定してください" >&2; exit 1; }
    stop
    pgrep -f "Xvfb $DISPLAY" >/dev/null || { setsid -f Xvfb "$DISPLAY" -screen 0 1280x800x24 >/dev/null 2>&1; sleep 2; }
    MKCIA_EMU_TAG=1 setsid -f "$emu" ${2:+"$2"} >/dev/null 2>&1 ;;
shot) import -window root "${2:?out png}" ;;
stop) stop ;;
*) echo "usage: $0 start [app] | shot <png> | stop" >&2; exit 1 ;;
esac
