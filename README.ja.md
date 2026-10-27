# 3DS-MediaPlayer

[English](README.md) | **日本語**

**動画 1 本と画像だけで作る、3DS 用の動画再生専用アプリ (`.cia`) と、その生成ツール。**
改造済み (CFW) の 3DS に FBI などでインストールして使う。

- 上画面で動画を再生 (H.264 + AAC)、下画面は好きな静止画 1 枚。
- 動画・アイコン・タイトル名・アイコン選択音などを指定するだけで `.cia` を作れる (CLI と GUI)。
- 音声の再生位置に映像を合わせるので、音ズレしにくい。ループ再生にも対応。
  ループしない動画は、最後に黒くフェードアウトしてホームに戻る。

## 動作確認状況

- 旧 3DS の実機で、映像・音声・タイトル音・フェードアウトまで確認済み (`medium` まで滑らか)。
- **New 3DS の実機は未確認** (`high` / `standard` プリセットと、追加コアでのデコードは New 3DS では未検証)。
- 生成ツールは Linux (Python 3.12) で開発し、**Windows** (64bit) でも動く (CLI も GUI も。[Windows](docs/JA/USAGE.md#windows) 参照)。**arm64 の Linux** と **Apple Silicon の macOS** でも CLI で CIA を作れる (`scripts/setup-tools.sh` が、arm64 を弾く上流のビルドファイルを直してからビルドする。macOS では GUI も開いてビルドできる。arm64 の Ubuntu と macOS で作った CIA は、x86_64 の Linux で作ったものと同じように実機で再生できた)。[macOS / arm64](docs/JA/USAGE.md#macos--arm64) 参照。

## 必要なもの

- Python 3 (3.12 で開発・テスト。tkinter は GUI にだけ必要)
- `ffmpeg` / `ffprobe` (libx264 と aac 付き。多くのディストリビューションの標準の ffmpeg でよい)
- `bannertool` / `3dstool` / [`makerom`](https://github.com/3DSGuy/Project_CTR) (`scripts/setup-tools.sh` で、動作確認した版をソースからビルドして `tools/bin/` に置く。
  要 git, make, cmake, g++, libssl-dev。`makerom` が PATH 上にあればビルドしない)
- 実機で音声を鳴らすには、自分の 3DS から吸い出した DSP ファームウェア (`sdmc:/3ds/dspfirm.cdc`)。無ければ映像だけ再生する。

### ROM を自分でビルドし直したいときだけ

ROM 本体は `prebuilt/mediaplayer.elf` が入っているので、CIA を作るだけなら下記は何も要らない。

- Docker (ROM は `devkitpro/devkitarm` イメージの中でビルドするので、ホストに devkitPro 自体を入れる必要はない)
- 詳細とビルド用スクリプト: [docs/JA/DEVELOPMENT.md](docs/JA/DEVELOPMENT.md)

## クイックスタート

Windows では `scripts/setup-tools.sh` と `scripts/mkcia.sh` の代わりに `scripts\setup-tools.ps1` と `scripts\mkcia.cmd` を使う (詳細: [docs/JA/USAGE.md](docs/JA/USAGE.md#windows))。

```bash
scripts/setup-tools.sh                  # bannertool / 3dstool / makerom を tools/bin/ に用意 (初回のみ)
scripts/mkcia.sh example                # まず同梱のサンプルをそのままビルド → out/Example.cia
scripts/mkcia.sh --new MyMovie          # サンプルをコピーして自分のテンプレート template/MyMovie を作る
                                        #   (タイトル = MyMovie、タイトルID は重ならない有効な値を自動で付ける。選択音は既定の音)
#  → template/MyMovie の動画・画像・音声と meta.json を自分のものに差し替える
scripts/mkcia.sh MyMovie                # → out/<output>.cia
scripts/mkcia-gui.sh                    # GUI で同じことをする (要: tkinter。docs/JA/USAGE.md の GUI 参照)
```

ビルド済みのサンプル (`Example.cia`) は [Releases](https://github.com/mar1mo-41414/3DS-MediaPlayer/releases) にあるので、
ツールを用意する前に、まず実機で動くか試せる。

### テンプレート

`template/<名前>/` に次のファイルを置く (サンプル: `template/example/`)。

| ファイル | 内容 |
|---|---|
| `video.mp4` | 元動画 (任意の形式・解像度。ツールが 3DS 向けに再エンコードする) |
| `icon.png` | ホームメニューのアイコン (省略可。無ければ動画から作る) |
| `bottom.png` | 下画面に表示する静止画 (省略可。無ければ動画から作る) |
| `select_sound.wav` | アイコンを選んだときの音 (省略可。無ければ既定の音。mp3 なども可) |
| `meta.json` | タイトル名・公開者・タイトルID・バージョンなど |

`meta.json` の例:

```json
{
  "title": "My Movie",
  "publisher": "me",
  "title_id": "000400000FF3A000",
  "version": "1.0.0",
  "loop": false,
  "volume": 1.0,
  "preset": "medium",
  "output": "My-Movie"
}
```

- `title_id` は `000400000xxxxx00` 形式 (`x` は 16 進 5 桁)。アプリごとに変える (同じ ID の CIA は上書きし合う)。
- `icon.png` / `bottom.png` が無いときは、動画の埋め込み画像 (mkv の添付画像など)、無ければ動画の途中のフレームから自動で作る
  (`frame_at` で秒数を指定できる)。あれば、そのまま使う。
- `preset` は画質と軽さの選択。旧 3DS は `medium` (既定) か `light`。`high` / `standard` は New 3DS 向けだが、**New 3DS では未検証**。

キーの一覧、プリセット、CLI のオプション、エラーの扱いは [docs/JA/USAGE.md](docs/JA/USAGE.md) を参照。

## 操作方法 (3DS 側)

- ホームメニューから起動すると、すぐ再生が始まる。
- **START**: 再生中いつでも終了してホームメニューに戻る。
- ループしない動画 (`"loop": false`) は、最後まで再生すると、上下画面が約 1 秒で黒くフェードアウトして、自動でホームメニューに戻る。
- ループする動画 (`"loop": true`) は、START を押すまで繰り返す。
- HOME ボタンは通常の 3DS と同じようにホームメニューを開ける (アプリ側では特別な処理をしていない。中断後の再開の挙動は未検証)。
- 音量・一時停止・シークの操作は無い (音量は `meta.json` の `volume` で決める)。

## 音が出ないとき

実機で音声を鳴らすには、**DSP ファームウェア** (`sdmc:/3ds/dspfirm.cdc`) が SD カードに必要。これは CFW を導入するときに
ダンプしておく標準的なファイルなので、お使いの CFW の導入手順 (例: [3DS Hacks Guide](https://3ds.hacks.guide/)) を参照すること。
無い場合、このアプリは映像だけを再生する (エラーにはならない)。

## ドキュメント

- [使い方 (CLI / GUI / meta.json / プリセット)](docs/JA/USAGE.md)
- [仕組み (ROM 本体と生成ツールの設計)](docs/JA/ARCHITECTURE.md)
- [開発 (ビルド・テスト・エミュレータ)](docs/JA/DEVELOPMENT.md)
- [HISTORY.md](HISTORY.md) — 調査の経緯・失敗談・未解決事項 (日本語)

## 注意

- 自分で用意した動画・画像など、**自分が扱ってよいコンテンツ**で使うこと。Nintendo とは無関係の非公式ツールです。
- CFW 環境が前提です。インストール・利用は自己責任でお願いします。

## ライセンス

MIT ([LICENSE](LICENSE))。事前ビルド済みの ROM には FFmpeg (LGPL v2.1 以降) などが含まれます。
詳細と再ビルド手順は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
