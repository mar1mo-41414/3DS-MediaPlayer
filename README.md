# 3DS-MediaPlayer

改造済み (CFW) 3DS に FBI などでインストールできる、**動画再生専用の `.cia`** と、
動画・アイコン・タイトル名などを指定するだけでその `.cia` を作る **生成ツール**。

- **ROM 本体** (`rom/`): 上画面で動画再生 (H.264 + AAC)、下画面は静止画 1 枚。
  devkitARM + libctru + citro2d/citro3d、ffmpeg (最小構成・自前クロスビルド)、Y2R、ndsp。
  音声の再生位置を基準に映像を同期 (遅れたらフレームスキップ、進みすぎたら待機)。
  テンプレートが変わっても ROM 本体は共通 (romfs 内の決まったファイル名を読むだけ)。
- **生成ツール** (`tool/`): Python 3 (標準ライブラリのみ) の CLI。処理ごとに関数を分離
  (`mkcia.video` / `assets` / `banner` / `romfs` / `cia`) してあり、GUI から同じ関数を呼べる。

署名は不要 (CFW 前提。`makerom` の既定テスト鍵で CIA 化)。

## 使い方 (生成ツール)

必要な外部ツール: `ffmpeg` / `ffprobe` (libx264 付き)、`makerom`、`bannertool`、`3dstool`。
`bannertool` と `3dstool` はソースから用意できる:

```bash
scripts/setup-tools.sh        # tools/bin/ に bannertool, 3dstool をビルド (要 cmake, g++, libssl-dev)
```

`makerom` は PATH 上に置く (<https://github.com/3DSGuy/Project_CTR>)。外部ツールは
`MKCIA_TOOLS_DIR` → `tools/bin/` → `PATH` の順に探す。

テンプレートディレクトリを用意する (サンプル: `examples/template/`):

```
template/
├── video.mp4          元動画 (任意の形式・解像度。ツールが 3DS 向けに再エンコード)
├── icon.png           ホームメニューのアイコン (48x48 に自動リサイズ)
├── bottom.png         下画面に表示する静止画 (320x240 に自動リサイズ)
├── select_sound.wav   アイコン選択音 (省略可。mp3/ogg/flac/m4a も可。先頭 3 秒を使い末尾をフェードアウト)
├── banner.png         バナー画像 (省略可。省略時は icon.png から生成)
└── meta.json
```

`meta.json`:

| キー | 必須 | 内容 |
|---|---|---|
| `title` | ○ | ホームメニューに出る名前 |
| `publisher` | ○ | 公開者名 |
| `title_id` | ○ | 16 桁 hex。`00040000xxxxxx00` 形式 (例 `000400000FF3A000`) |
| `version` | ○ | `メジャー.マイナー.マイクロ` (例 `1.0.0`) |
| `long_title` | | 長いタイトル (既定は `title`) |
| `product_code` | | `CTR-P-XXXX` (既定 `CTR-P-MPLY`) |
| `loop` | | ループ再生 (既定 `false`) |
| `volume` | | 音量 0.0〜1.0 (既定 `1.0`) |

生成:

```bash
scripts/mkcia.sh path/to/template -o out.cia
scripts/mkcia.sh path/to/template -o out.cia --preset light
```

エンコードプリセット (ユーザーが上限を超える値は指定できない):

| preset | 解像度 | fps | 映像 | 音声 |
|---|---|---|---|---|
| `standard` (既定) | 400x240 | 24 | 350 kbps | AAC 64 kbps / 32 kHz |
| `light` | 320x192 (ROM が全画面に拡大) | 20 | 250 kbps | AAC 48 kbps / 32 kHz |

テスト: `cd tool && python3 -m unittest discover -s tests`

## ROM 本体のビルド

Docker (`devkitpro/devkitarm`) 経由でビルドする。ホストに devkitPro は不要。

```bash
scripts/build-ffmpeg.sh       # ARM 向け ffmpeg 最小構成を deps/ffmpeg-3ds/ に (初回のみ、数分)
scripts/make-prebuilt.sh      # ROM をビルドし、生成ツールが使う prebuilt/mediaplayer.elf を更新
scripts/build-rom.sh          # rom/mediaplayer.3dsx のみビルド (エミュレータ確認用)
scripts/build-rom.sh EXTRA_CFLAGS=-DDEBUG_LOG   # SD カードに mediaplayer.log を出すデバッグビルド
```

`rom/romfs/` は開発用の romfs (`video.mp4` / `bottom.png` / `config.json`)。
romfs を差し替えたら `scripts/build-rom.sh clean` してからビルドし直す。

## 動作確認状況

- AzaharPlus (3DS エミュレータ) で、`.3dsx` と生成した `.cia` のインストール・起動・
  上画面の映像・下画面の画像・タイトル/アイコン表示・ループを確認済み。
  エミュレータでは `scripts/run-emu.sh` (仮想ディスプレイ上で起動・スクショ) を使う。
- **実機 (旧3DS / New 3DS) は未確認**。特に旧3DS では `standard` がデコードに間に合わない
  可能性が高い (エミュレータ上の計測で 400x240 が約 39 ms/フレーム、320x192 が約 31 ms/フレーム)。
  旧3DS では `light` を使い、それでも厳しければプリセットの調整が必要。
- 音声は ndsp を使うため、実機では DSP ファームウェア (`sdmc:/3ds/dspfirm.cdc`) が必要。
  無い場合は映像だけ再生する。
- 経緯・失敗談・未解決事項は [HISTORY.md](HISTORY.md)。
