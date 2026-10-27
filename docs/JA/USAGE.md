# 使い方 (CLI / GUI)

README のクイックスタートの詳細版。

## テンプレート

動画・画像・音声・設定を 1 つのディレクトリにまとめたものがテンプレート。`template/<名前>/` に置くと
名前だけで指定できる (`template/` 配下は `example` 以外コミット対象外)。

```
template/<名前>/
├── video.mp4          元動画 (任意の形式・解像度。ツールが 3DS 向けに再エンコード。mkv/mov/avi/webm/m4v も可)
├── icon.png           ホームメニューのアイコン (省略可。48x48 に自動リサイズ。jpg/bmp/webp/gif も可)
├── bottom.png         下画面に表示する静止画 (省略可。320x240 に自動リサイズ。同上)
├── select_sound.wav   アイコン選択音 (省略可。無ければ既定の音。mp3/ogg/flac/m4a/aac も可。先頭 3 秒を使い末尾をフェードアウト)
├── banner.png         バナー画像 (省略可。省略時は icon.png から生成)
└── meta.json
```

拡張子は上記のどれでもよく、中身は ffmpeg が読めればよい (拡張子と中身が違っていても可)。
同じ種類のファイルが複数あるときは、上に書いた拡張子の順で最初のものを使う。
必須なのは `meta.json` と動画だけ。

### select_sound が無いとき (既定の音)

`select_sound.*` が無ければ、ホームメニューでアイコンを選んだときの音に、**既定の音**を使う (2 音の短いチャイム。このプロジェクトで
合成したもので、`tool/mkcia/default_select_sound.wav`。作り直しは `scripts/make-default-sound.sh`)。homebrew では独自の音を持たず、
既定の音を使うものも多い。独自の音を使いたいときは `select_sound.*` を置く。

**無音にしたいときは、無音の音声ファイルを `select_sound.wav` として置く** (無いときは既定の音が鳴る)。壊れた `select_sound.*` は
既定の音に差し替えず、エラーにする。`--new` で作るテンプレートは、最初から `select_sound` を持たない (= 既定の音)。

### icon / bottom が無いとき (動画から作る)

`icon.*` や `bottom.*` が無ければ、ビルド時に動画から画像を作る。あるものは、そのまま使う (置き換えない)。

1. 動画に**埋め込み画像**があれば、それを使う (mkv の添付画像、mp4 のカバーアートなど。ffmpeg が画像として認識するもの。
   `cover` を含む名前のものを優先)。埋め込み画像が読めない場合は無視する。
2. 無ければ、動画の**途中のフレーム**を使う。秒数は `frame_at` (下記) で指定でき、省略すると動画の長さの 15% の位置
   (最大 30 秒。冒頭の暗転やロゴを避けるため)。

`frame_at` を明示したときは、埋め込み画像があってもそのフレームを使う。回転や、画素が正方形でない動画は補正して取り出す。
作った画像から、アイコンは中央を正方形に切り抜いて、下画面とバナーは縦横比を保って余白付きで作る。
`icon` だけ / `bottom` だけ無い場合は、無いほうだけを作る。

### meta.json

| キー | 必須 | 内容 |
|---|---|---|
| `title` | ○ | ホームメニューに出る名前 (64 文字以内) |
| `publisher` | ○ | 公開者名 (64 文字以内) |
| `title_id` | ○ | 16 桁 hex。`000400000xxxxx00` 形式 (`x` は 16 進 5 桁。範囲 `0004000000000000`〜`000400000FFFFF00`。例 `000400000FF3A000`) |
| `version` | ○ | `メジャー.マイナー.マイクロ` (例 `1.0.0`。各 0-63 / 0-63 / 0-15) |
| `long_title` | | 長いタイトル (128 文字以内。既定は `title`) |
| `product_code` | | `CTR-P-XXXX` (既定 `CTR-P-MPLY`) |
| `loop` | | ループ再生 (既定 `false`。`false` なら最後まで再生して、黒くフェードアウトしてホームへ戻る) |
| `volume` | | 音量 0.0〜1.0 (既定 `1.0`) |
| `preset` | | エンコードプリセット名 (下表。既定 `medium`) |
| `frame_at` | | icon / bottom が無いとき、動画からフレームを取る秒数 (0 以上、動画の長さ未満。既定は埋め込み画像、無ければ長さの 15%) |
| `output` | | 出力ファイル名 (`.cia` は省略可。ディレクトリや `<>:"/\|?*` は不可。既定は `<テンプレート名>.cia`) |

タイトルID は、同じ ID の CIA を 2 つインストールすると上書きし合うので、アプリごとに変える。

## プリセット

ユーザーが上限を超える値は指定できない (3DS の CPU では間に合わないため)。

| preset | 解像度 | fps | 映像 | 音声 | 目安 |
|---|---|---|---|---|---|
| `light` | 320x192 (ROM が全画面に拡大) | 20 | 250 kbps | AAC 48 kbps / 32 kHz | 旧3DS向け。余裕あり (旧3DS実機で確認済み) |
| `medium` (既定) | 360x216 (同上) | 20 | 400 kbps | AAC 48 kbps / 32 kHz | 旧3DS推奨 (旧3DS実機で確認済み) |
| `high` | 400x240 | 20 | 400 kbps | AAC 48 kbps / 32 kHz | New 3DS向け (**New 3DS では未検証**。旧3DSでは音声が少し間延びする) |
| `standard` | 400x240 | 24 | 350 kbps | AAC 64 kbps / 32 kHz | New 3DS向け (**New 3DS では未検証**) |

旧3DS の実機では `light` と `medium` が滑らか。`high` は再生できるがデコードが再生速度ぎりぎりで、音声が少し間延びすることがある。
New 3DS の実機では、どのプリセットも未検証 (New 3DS ではアプリ用の追加コアでデコードする経路が使われるが、まだ試していない)。

## CLI

```bash
scripts/mkcia.sh --new MyMovie            # template/example をコピーして template/MyMovie を作る (下記)
scripts/mkcia.sh MyMovie                  # template/MyMovie → out/<output>.cia
scripts/mkcia.sh --list                   # template/ 配下のテンプレート一覧
scripts/mkcia.sh MyMovie --preset light   # meta.json の preset を一時的に上書き
scripts/mkcia.sh MyMovie --frame-at 45    # icon/bottom が無いとき、動画の 45 秒のフレームから作る
scripts/mkcia.sh MyMovie --output-dir ~/Downloads
scripts/mkcia.sh path/to/dir -o /tmp/x.cia   # パスでも指定できる (-o は出力ファイルを直接指定)
```

- 設定の優先順位は「コマンドライン引数 > meta.json > 既定」。
- テンプレートがパスとしても名前としても見つかる場合は、`meta.json` のある方 (同じならパス) を使う。
- 出力先の既定は `out/`。
- `--new NAME`: `template/example` を `template/NAME` にコピーして (タイトル選択音は引き継がず、既定の音を使う)、`title` を `NAME`、`title_id` を他のテンプレートと重ならない
  有効な値にする (雛形の `long_title` と `output` は引き継がない)。コピーした時点でそのままビルドでき、素材と `meta.json` を
  自分のものに差し替えていける。同じ名前や使えない名前、`template/example` が無い場合はエラー。
- `--frame-at SEC`: icon / bottom が無いときに動画から取るフレームの秒数 (`meta.json` の `frame_at` より優先)。
- オプション: `--elf` (ROM 本体の ELF)、`--keep-work DIR` (中間生成物を残す)、`--no-compress` (ELF コードの圧縮を省いて約 8 秒速い。
  CIA が約 0.7MB 大きくなる。主にテスト用)、`--debug` (想定外のエラー時にトレースバックを表示)。
- 終了コード: `0` 成功 / `1` 入力などユーザーが直せるエラー / `2` 想定外のエラー / `130` 中断。

### 入力の検証

エンコードなどの重い処理の前に、次をまとめて検証し、問題は「どのファイルの何が悪いか」を日本語で表示して終了する
(ffmpeg などの生ログは出さない)。

- 外部ツール (ffmpeg / ffprobe / bannertool / 3dstool / makerom) の有無、ffmpeg に libx264 と aac があるか。
- ROM の ELF が 32bit ARM の ELF か。
- テンプレートの必要ファイル (`meta.json` と動画) の有無、あるファイルの空・ディレクトリ・読み取り権限。
  `frame_at` が動画の長さの範囲内か (icon / bottom が無いときだけ)。
- `meta.json` の JSON / 型 / 長さ / 値の範囲 (タイトルID の範囲、バージョンの範囲、`output` に使えない文字など)。
- 動画に映像があるか・0.5 秒以上か、画像・音声として読めるか、CIA が 4GB (FAT32 の上限) を超えないか。
- 出力が `.cia` で書き込めるか、入力ファイルを上書きしないか。

出力は同じディレクトリの一時ファイルに作ってから置き換えるので、失敗しても既存の出力を壊さない。

## GUI

```bash
scripts/mkcia-gui.sh          # Tkinter の GUI (要: tkinter が使える Python。下記)
PYTHON=python3.14 scripts/mkcia-gui.sh   # 別の Python で起動する (mkcia.sh も同じ環境変数)
```

tkinter の入れ方 (足りないと、使った Python を示すメッセージが出る):

- Debian/Ubuntu 系: `sudo apt install python3-tk` (Fedora 系: `sudo dnf install python3-tkinter`)
- macOS (Homebrew): `brew install python-tk@3.X`。3.X は実行する `python3` のバージョン (`python3 --version`) に合わせる。
  Homebrew の Python は tkinter を単体では含まない。Apple 標準の `/usr/bin/python3` は古い Tk 8.5 で非推奨。
- Windows: python.org のインストーラは既定で tcl/tk を含む。

- テンプレートの選択・新規作成 (タイトルIDは名前から自動採番)、基本情報の編集、素材の差し替え (サムネイルと情報を表示)、
  プリセット・ループ・音量・出力名・出力先の設定、検証・ビルド・中止を 1 つの画面で行う。CLI と同じ処理を呼ぶ。
- 素材の「選択…」は、中身を検証してからテンプレートへコピーする (壊れたファイルは弾き、テンプレートを変えない。
  拡張子違いの古いファイルは消す)。
- 入力欄は編集中に検証され、問題は赤字で出る。タイトルIDが他のテンプレートと重なると警告する。
- 「CIA を作る」「検証」は先に meta.json を保存する。未保存のままテンプレートを切り替える/閉じるときは確認する。
- ビルドは別スレッドで動き、進捗バーとログが出る。「中止」で外部コマンドを止められる (一時ファイルも残さない)。
  外部コマンドの行はログに出さない (「コマンドも表示」で表示)。

## Windows

ツールは素の Python なので Windows (64bit) でも動く。python.org から Python 3 を入れ (GUI を使うなら tcl/tk も。既定で含まれる)、
このリポジトリのクローンで次のようにする。

```bat
REM 初回のみ: makerom / bannertool / 3dstool / ffmpeg を tools\bin\ に取得
powershell -ExecutionPolicy Bypass -File scripts\setup-tools.ps1

REM サンプルをビルド -> out\Example.cia
scripts\mkcia.cmd example

REM 自分のテンプレートと GUI
scripts\mkcia.cmd --new MyMovie
scripts\mkcia.cmd MyMovie
scripts\mkcia-gui.cmd
```


- `scripts\mkcia.cmd` / `scripts\mkcia-gui.cmd` は `mkcia.sh` / `mkcia-gui.sh` の Windows 版 (引数は同じ)。実際に動く最初の Python 3 を使う:
  環境変数 `PYTHON` があればそれ、次に `py -3`、`python`、`python3`。Microsoft Store を開くだけの "python" (「Python」とだけ表示して失敗する) は飛ばし、
  動く Python が無ければその旨を表示して終わる。Python 3 は python.org か `winget install Python.Python.3.12` で入れる。
- `setup-tools.ps1` は動作確認した版の配布バイナリを取得する (`ffmpeg` は `PATH` 上にあれば取得しない。
  [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) の essentials ビルドは libx264 と aac を含む)。手元のツールを使うなら、`PATH` に置くか
  `MKCIA_TOOLS_DIR` で場所を指定する。
- テンプレート名・出力名・出力先に空白や日本語があっても動く (`makerom` は出力先に直接書かず、作業フォルダに作った CIA をコピーする)。
  ただし `makerom` など外部ツールは *入力側* のパスをシステムのコードページで読むので、このリポジトリ (と `%TEMP%`) は、コードページで表せる
  名前のフォルダに置くこと。ASCII だけが最も安全。出力ファイルの権限はフォルダから継承した普通のものになる。
- Windows では使えないもの: ROM 自体のビルド用シェルスクリプト (`build-rom.sh` など。Docker/devkitPro が要るので、ROM を開発するときだけ必要)。

## macOS / arm64

同じ `scripts/setup-tools.sh` / `scripts/mkcia.sh` が **arm64 の Linux** と **Apple Silicon の macOS** でも使える。`bannertool` と `3dstool` の
上流のビルドファイルは x86 しか想定していないので、取得した直後にスクリプトが直す (arm64 のホストを受け付ける。`3dstool` 同梱の x86 専用の
事前ビルド済みライブラリは使わず、システムの OpenSSL / libcurl を使う)。

- Debian/Ubuntu arm64: `sudo apt install git make cmake g++ libssl-dev libcurl4-openssl-dev ffmpeg python3`
- macOS: `brew install cmake openssl@3 ffmpeg` (Homebrew の `openssl@3` はスクリプトが自分で探す。ssh 越しのような非ログインシェルで PATH に無くても見つける。
  別の場所なら `OPENSSL_ROOT_DIR=<prefix>` を付ける)。macOS には OpenSSL のヘッダが標準で無いので、無ければメッセージを出して止まる。
  GUI には `python3 -m tkinter` が動くことが必要 (Homebrew: Python のバージョンに合わせて `brew install python-tk@3.X`。[GUI](#gui) 参照)。
- 確認済み: arm64 の Ubuntu と M4 の Mac で、3 つのツールのビルド、`example` のビルド、全テスト (GUI テストは画面が無くスキップ) が通り、
  CIA の ExHeader / ExeFS は x86_64 の Linux で作ったものとバイト一致。M4 の Mac では GUI も開き、サンプルをビルドできた。arm64 の Ubuntu と macOS で作った CIA も、実機で x86_64 の Linux 産と同じように再生できた。Intel Mac は対象外 (未テスト。必要になれば対応する)。

## 操作 (3DS 側)

- **START**: 再生中いつでも終了してホームメニューに戻る。
- `loop` が `false` なら、最後まで再生した後、上下画面が約 1 秒で黒くフェードアウトして自動で戻る。`true` なら START まで繰り返す。
- HOME ボタンは通常の 3DS と同じ (アプリ側では特別な処理をしていない。中断後の再開は未検証)。
- 音量・一時停止・シークの操作は無い。

## 実機での注意

- インストールした CIA は FBI などで入れる。CFW 環境が前提 (署名は makerom の既定のテスト鍵)。
- 音声は ndsp を使うため、実機では DSP ファームウェア (`sdmc:/3ds/dspfirm.cdc`) が必要。CFW の導入手順でダンプする標準的なファイルなので、
  お使いの CFW の導入手順を参照すること。無い場合は映像だけ再生する (エラーにはならない)。
