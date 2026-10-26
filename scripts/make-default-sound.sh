#!/bin/bash
# 既定のタイトル選択音 (tool/mkcia/default_select_sound.wav) を ffmpeg で合成して作り直す。
# 他人の素材は使わず、2 音の短いチャイム (E5 → A5、減衰、約 0.7 秒) を数式から作る。同じ ffmpeg なら同じ結果になる。
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=tool/mkcia/default_select_sound.wav
ffmpeg -v error -y -f lavfi -i "aevalsrc='0.45*sin(2*PI*659.25*t)*exp(-7*t) + 0.30*sin(2*PI*1318.5*t)*exp(-12*t) + gt(t,0.13)*(0.45*sin(2*PI*880*(t-0.13))*exp(-5*(t-0.13)) + 0.30*sin(2*PI*1760*(t-0.13))*exp(-10*(t-0.13)))':s=32000:d=0.7" \
    -af "volume=0.85,afade=t=in:d=0.004,afade=t=out:st=0.6:d=0.1" -ac 1 -c:a pcm_s16le "$OUT"
ls -la "$OUT"
