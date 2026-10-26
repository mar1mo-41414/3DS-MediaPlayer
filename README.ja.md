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
- New 3DS の実機は未確認。
- 生成ツールは Linux で開発・テスト (Python 3.12)。

## 必要なもの

- Python 3 (3.12 で開発・テスト。tkinter は GUI にだけ必要)
- `ffmpeg` / `ffprobe` (libx264 と aac 付き)、[`makerom`](https://github.com/3DSGuy/Project_CTR)
- `bannertool` / `3dstool` (`scripts/setup-tools.sh` でソースからビルドできる。要 git, make, cmake, g++, libssl-dev)
- 実機で音声を鳴らすには、自分の 3DS から吸い出した DSP ファームウェア (`sdmc:/3ds/dspfirm.cdc`)。無ければ映像だけ再生する。

ROM 本体は `prebuilt/mediaplayer.elf` が入っているので、ビルドし直さない限り Docker や devkitPro は不要。

## クイックスタート

```bash
scripts/setup-tools.sh                  # bannertool / 3dstool を tools/bin/ に用意 (初回のみ)
mkdir -p template/MyMovie               # テンプレートを作る (下記)
cp -r template/example/* template/MyMovie/   # 例をコピーして、中身を自分のものに差し替える
scripts/mkcia.sh MyMovie                # → out/<output>.cia
scripts/mkcia-gui.sh                    # GUI で同じことをする (要: python3-tk)
```

### テンプレート

`template/<名前>/` に次のファイルを置く (サンプル: `template/example/`)。

| ファイル | 内容 |
|---|---|
| `video.mp4` | 元動画 (任意の形式・解像度。ツールが 3DS 向けに再エンコードする) |
| `icon.png` | ホームメニューのアイコン |
| `bottom.png` | 下画面に表示する静止画 |
| `select_sound.wav` | アイコン選択音 (省略可。mp3 なども可) |
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
- `preset` は画質と軽さの選択。旧 3DS は `medium` (既定) か `light`、New 3DS は `high` / `standard` も使える。

キーの一覧、プリセット、CLI のオプション、エラーの扱いは [docs/JA/USAGE.md](docs/JA/USAGE.md) を参照。

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
