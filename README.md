# 3DS-MediaPlayer

改造済み (CFW) 3DS に FBI などでインストールできる、**動画再生専用の `.cia`** と、
動画・アイコン・タイトル名などを指定するだけでその `.cia` を作る **生成ツール**。

- **ROM 本体** (`rom/`): 上画面で動画再生 (H.264 + AAC)、下画面は静止画 1 枚。
  devkitARM + libctru + citro2d/citro3d、ffmpeg (最小構成・自前クロスビルド)、Y2R、ndsp。
  音声の再生位置を基準に映像を同期 (遅れたらフレームスキップ、進みすぎたら待機)。
  ループ再生でない動画は、最後まで再生し終えると上下画面を約 1 秒かけて黒くフェードアウトしてホームに戻る。
  テンプレートが変わっても ROM 本体は共通 (romfs 内の決まったファイル名を読むだけ)。
- **生成ツール** (`tool/`): Python 3 (標準ライブラリのみ) の CLI と Tkinter の GUI。処理ごとに関数を分離
  (`mkcia.video` / `assets` / `banner` / `romfs` / `cia`) してあり、GUI (`gui_model` / `gui`) も同じ関数を呼ぶ。

署名は不要 (CFW 前提。`makerom` の既定テスト鍵で CIA 化)。

## 使い方 (生成ツール)

必要な外部ツール: `ffmpeg` / `ffprobe` (libx264 付き)、`makerom`、`bannertool`、`3dstool`。
`bannertool` と `3dstool` はソースから用意できる:

```bash
scripts/setup-tools.sh        # tools/bin/ に bannertool, 3dstool をビルド (要 cmake, g++, libssl-dev)
```

`makerom` は PATH 上に置く (<https://github.com/3DSGuy/Project_CTR>)。外部ツールは
`MKCIA_TOOLS_DIR` → `tools/bin/` → `PATH` の順に探す。

テンプレートディレクトリを `template/<名前>/` に置く (サンプル: `template/example/`。
`template/` 配下は `example` 以外コミット対象外):

```
template/<名前>/
├── video.mp4          元動画 (任意の形式・解像度。ツールが 3DS 向けに再エンコード。mkv/mov/avi/webm/m4v も可)
├── icon.png           ホームメニューのアイコン (48x48 に自動リサイズ。jpg/bmp/webp/gif も可)
├── bottom.png         下画面に表示する静止画 (320x240 に自動リサイズ。同上)
├── select_sound.wav   アイコン選択音 (省略可。mp3/ogg/flac/m4a/aac も可。先頭 3 秒を使い末尾をフェードアウト)
├── banner.png         バナー画像 (省略可。省略時は icon.png から生成)
└── meta.json

ファイル名の拡張子は上記のどれでもよく、中身は ffmpeg が読めればよい (拡張子と中身が違っていても可)。
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
| `preset` | | エンコードプリセット名 (下表。既定 `medium`) |
| `output` | | 出力ファイル名 (`.cia` は省略可。ディレクトリや `<>:"/\|?*` は不可。既定は `<テンプレート名>.cia`) |

生成 (テンプレート名を指定すると `template/<名前>/` を使い、`out/<output>.cia` に出力する):

```bash
scripts/mkcia.sh Twinkle_Night                  # template/Twinkle_Night → out/Twinkle-Night.cia
scripts/mkcia.sh --list                         # template/ 配下のテンプレート一覧
scripts/mkcia.sh Twinkle_Night --preset light   # meta.json の preset を一時的に上書き
scripts/mkcia.sh Twinkle_Night --output-dir ~/ダウンロード
scripts/mkcia.sh path/to/dir -o /tmp/x.cia      # パスでも指定できる (-o は出力ファイルを直接指定)
```

設定の優先順位は「コマンドライン引数 > meta.json > 既定」。テンプレートがパスとしても名前としても
見つかる場合は、`meta.json` のある方 (同じならパス) を使う。

エンコードプリセット (ユーザーが上限を超える値は指定できない):

| preset | 解像度 | fps | 映像 | 音声 |
|---|---|---|---|---|
| `standard` (New 3DS 向け) | 400x240 | 24 | 350 kbps | AAC 64 kbps / 32 kHz |
| `light` | 320x192 (ROM が全画面に拡大) | 20 | 250 kbps | AAC 48 kbps / 32 kHz |
| `medium` (既定) | 360x216 (同上) | 20 | 400 kbps | AAC 48 kbps / 32 kHz |
| `high` (New 3DS 向け) | 400x240 | 20 | 400 kbps | AAC 48 kbps / 32 kHz |

### GUI

```bash
scripts/mkcia-gui.sh          # Tkinter の GUI (要: python3-tk。Debian/Ubuntu 系は sudo apt install python3-tk)
```

テンプレートの選択・新規作成、基本情報 (meta.json) の編集、素材 (動画・画像・音声) の差し替えとサムネイル/情報の確認、
プリセット・ループ・音量・出力名・出力先の設定、検証・ビルド・中止をひとつの画面で行う。CLI と同じ処理を呼ぶ。

- テンプレートは `template/<名前>/` から選ぶ (「フォルダを選ぶ…」で任意のフォルダも開ける)。「新規作成…」で空のテンプレートと
  既定の meta.json (タイトルIDは名前から自動採番) を作る。
- 素材の「選択…」は、中身を検証してからテンプレートへコピーする (拡張子違いの古いファイルは消す。壊れたファイルは弾いてテンプレートを変えない)。
- 入力欄は編集中に検証され、問題は赤字で出る。タイトルIDが他のテンプレートと重なると警告する (両方インストールすると上書きし合うため)。
- 「CIA を作る」「検証」は先に meta.json を保存する。未保存のままテンプレートを切り替える/閉じるときは確認する。
- ビルドは別スレッドで動き、進捗バーとログが出る。「中止」で外部コマンドを止められる (途中の一時ファイルも残さない)。
- 外部コマンドの行はログに出さない (「コマンドも表示」で表示)。

### 入力の検証とエラー

エンコードなどの重い処理の前に、テンプレート・メディア・出力先・ROM の ELF・外部ツールをまとめて検証し、
問題は「どのファイルの何が悪いか」を日本語で表示して終了する (ffmpeg などの生ログは出さない)。

- 検証するもの: 必要ファイルの有無・空ファイル・ディレクトリ・読み取り権限、meta.json の JSON/型/長さ/値の範囲
  (タイトル 64 文字、長いタイトル 128 文字、公開者 64 文字など)、動画に映像があるか・0.5 秒以上か、
  画像・音声として読めるか、CIA が 4GB (FAT32 の上限) を超えないか、出力が `.cia` で書き込めるか・入力を上書きしないか。
- 出力は一時ファイルに作ってから置き換えるので、失敗しても既存の出力を壊さない。
- 終了コード: `0` 成功 / `1` 入力などユーザーが直せるエラー / `2` 想定外のエラー (`--debug` で詳細) / `130` 中断。
- `--no-compress`: ELF コードの圧縮を省く (約 8 秒速い。CIA が約 0.7MB 大きくなる。主にテスト用)。

### テスト

```bash
cd tool && python3 -m unittest discover -s tests     # 約 2 分 / 347 件 (画面が無い環境では GUI のテストはスキップ)
```

外部ツール (ffmpeg / bannertool / 3dstool / makerom) と `prebuilt/mediaplayer.elf` が無い環境では、
それを使うテストは自動でスキップされる。`test_meta*.py` (meta 検証)、`test_template.py` (テンプレート構成)、
`test_media.py` (壊れた/違う種類のメディア)、`test_environment.py` (ELF・出力先・ツール)、`test_cli.py` (終了コード)、`test_resolution.py` (preset/出力名の優先順位)、`test_cancel.py` (外部コマンドの中止)、
`test_gui_model.py` (GUI のロジック層)、`test_gui.py` (Tk を実際に動かす GUI 操作テスト。画面 `DISPLAY` が無ければスキップ。Xvfb 上でも動く)、
`test_e2e.py` (実際に CIA を作る通しテスト: 形式違いの入力、日本語タイトル、失敗時に出力を壊さない、fps・縦横比など)。

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
- **実機 (旧3DS) で確認済み**: `light` と `medium` は映像・音声とも滑らか (タイトル音も鳴る)。
  `high` は再生できるが音声が少し間延びする (デコードが再生速度ぎりぎり)。`standard` (24fps) は未確認で、
  旧3DS では間に合わない可能性が高い。New 3DS は未確認。
- 音声は ndsp を使うため、実機では DSP ファームウェア (`sdmc:/3ds/dspfirm.cdc`) が必要。
  無い場合は映像だけ再生する。
- 経緯・失敗談・未解決事項は [HISTORY.md](HISTORY.md)。
