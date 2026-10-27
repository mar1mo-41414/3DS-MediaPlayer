# 開発

## ディレクトリ構成

```
rom/            ROM 本体 (C)。rom/romfs は開発用の romfs
prebuilt/       生成ツールが使う汎用 ROM (mediaplayer.elf)
tool/mkcia/     生成ツール (Python) と GUI
tool/tests/     テスト
scripts/        ビルド・実行用スクリプト
template/       テンプレート置き場 (example 以外はコミットしない)
out/            生成した CIA (コミットしない)
docs/           ドキュメント
```

## 生成ツールだけ使う場合

`prebuilt/mediaplayer.elf` が入っているので、ROM のビルドは不要。必要なのは Python 3、ffmpeg/ffprobe (libx264 付き)、
makerom、bannertool、3dstool。

```bash
scripts/setup-tools.sh        # tools/bin/ に bannertool, 3dstool, makerom をビルド (要 git, make, cmake, g++, libssl-dev, python3。arm64 / macOS は USAGE 参照)
```

ソースは動作確認した版 (コミット/タグ) に固定してある。`makerom` は PATH 上や `tools/bin/` に既にあればビルドしない。
外部ツールは `MKCIA_TOOLS_DIR` → `tools/bin/` → `PATH` の順に探す。

## ROM 本体のビルド

Docker (`devkitpro/devkitarm`) 経由でビルドする。ホストに devkitPro は不要。

```bash
scripts/build-ffmpeg.sh       # ARM 向け ffmpeg 最小構成を deps/ffmpeg-3ds/ に (初回のみ、数分)
scripts/make-prebuilt.sh      # ROM をビルドし、デバッグ情報を除いて prebuilt/mediaplayer.elf を更新
scripts/build-rom.sh          # rom/mediaplayer.3dsx のみビルド (エミュレータ確認用)
scripts/build-rom.sh EXTRA_CFLAGS=-DDEBUG_LOG   # SD カードに mediaplayer.log を出すデバッグビルド
```

- `rom/romfs/` の中身を差し替えたら、`scripts/build-rom.sh clean` してからビルドし直す (romfs は依存関係に入っていない)。
- ffmpeg は 4.4.6 を使う。6.x は AAC 用の FFT テーブルだけでメモリ (BSS) が約 17MB 増える。

## テスト

```bash
cd tool && python3 -m unittest discover -s tests
```

約 370 件、約 2 分。外部ツールと `prebuilt/mediaplayer.elf` が無い環境では、それを使うテストは自動でスキップされる。
GUI のテストは画面 (`DISPLAY`) が必要で、無ければスキップされる (Xvfb 上でも動く)。

| ファイル | 内容 |
|---|---|
| `test_meta.py` / `test_meta_edge.py` | meta.json の検証 (型・長さ・範囲・不正な JSON・BOM など) |
| `test_template.py` | テンプレートの構成 (欠落・空ファイル・リンク・拡張子) |
| `test_media.py` | 壊れた/種類違いの動画・画像・音声 |
| `test_environment.py` | ELF・出力先・外部ツールの検証 |
| `test_cli.py` / `test_resolution.py` | CLI の終了コード、テンプレート名の解決、preset/出力名の優先順位 |
| `test_cancel.py` | 外部コマンドの中止 |
| `test_gui_model.py` / `test_gui.py` | GUI のロジック層 / Tk を実際に動かす操作テスト |
| `test_default_sound.py` | select_sound が無いときの既定の音 (同梱ファイル・無音の指定・壊れた指定はエラー) |
| `test_extract.py` | icon/bottom が無いときの動画からの画像生成 (埋め込み画像・フレーム・優先順位・範囲チェック) |
| `test_fsutil.py` | 一時ファイル/ディレクトリを (mkstemp の所有者専用ではなく) 通常の権限で作ること |
| `test_scaffold.py` | 雛形生成 (`--new`): コピー・タイトルID の重複回避・失敗時に何も残さない・そのままビルドできる |
| `test_e2e.py` | 実際に CIA を作る通しテスト (形式違いの入力、日本語タイトル、失敗時に出力を壊さない、fps・縦横比) |

POSIX の権限ビット・umask・シンボリックリンクが要るテストは、Windows (とリンクを作れない環境) ではスキップする。

通しテストが遅いのは makerom の ELF コード圧縮 (1 回約 8 秒) のため。テストでは `compress_code=False` で省く。

## CI (GitHub Actions)

`.github/workflows/ci.yml`:

- `unit`: 外部ツール無し・Python 3.9 / 3.12 / 3.13 でテストを回す (ツールが無い環境でテストがスキップされ、落ちないことの保証)。
- `full`: Ubuntu でツール一式 (`scripts/setup-tools.sh`) と仮想ディスプレイ (xvfb) をそろえ、全テストと、`template/example` からの CIA の生成まで行う。
  生成した `Example.cia` は成果物 (artifact) として残る。
- `windows`: Windows のランナーで `scripts/setup-tools.ps1` でツールを取得し、全テスト (GUI テスト含む) と、`scripts\mkcia.cmd` でのサンプルの生成まで行う。
- `release`: `v*` のタグを push したとき、`Example.cia` を Release に添付する (Release が無ければ作る)。

```bash
git tag v1.0.0 && git push github v1.0.0     # Release に Example.cia が付く
```

ワークフローは `actionlint` で検証でき、`full` と同じ手順はクリーンな Docker コンテナ (ubuntu:24.04) でも再現できる。

## エミュレータでの確認

`scripts/run-emu.sh` は、Azahar 系のエミュレータを仮想ディスプレイ (Xvfb) 上で起動してスクリーンショットを撮る。

```bash
AZAHAR=/path/to/azahar scripts/run-emu.sh start rom/mediaplayer.3dsx
scripts/run-emu.sh shot /tmp/shot.png
scripts/run-emu.sh stop
```

- `.cia` は初回に「インストールが必要」と聞かれる。
- 音声を確認するには、エミュレータの SD 領域の `3ds/dspfirm.cdc` にダミーのファイル (0 埋めなど) を置くと HLE DSP で `ndspInit` が通る。
  無いと音声は無効になり、映像だけ再生する。
- **エミュレータは CIA の権限 (RSF) やメモリマップを検査しない**。エミュレータで動いても実機で動くとは限らない。
  実機で試すこと。実績のある既存の CIA があれば、ExHeader を比較するのが確実。
- スクリーンショットの確認は、1 枚が正しいだけでなく、時間をおいた複数枚が違う場面になっていることまで見る
  (映像が最初の 1 枚で固まる不具合を見逃した経験があるため)。

## 経緯と落とし穴

調査の経緯・失敗談・未解決事項は [HISTORY.md](../../HISTORY.md) (日本語)。主な落とし穴:

- メインスレッドのスタック 32KB (libctru 既定) は H.264 デコードで溢れる。症状は「デコードで止まる」。
- `Tex3DS_SubTexture` は `top < bottom` だと citro2d が「90° 回転した画像」と解釈する。`top > bottom` にする。
- ffmpeg に `romfs:/...` を渡すとプロトコル名と解釈されて失敗する。`file:romfs:/...` とする。
- RSF の権限不足は実機でだけ起動直後に落ちる (上記)。`makerom` の FS 権限名はバージョンで変わる (`TwlCardBackup` など)。
- 外部ツールの制約 (範囲・長さ) は、ドキュメントの記憶ではなく実測してから検証に入れる (タイトルID の上限 0xFFFFF など)。
