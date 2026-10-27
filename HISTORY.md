# HISTORY

作業履歴・調査の経緯・失敗談・未解決事項 (日本語)。確定した最新情報は README.md と docs/ を参照。

## 2026-10-26 初期実装

### 環境構築
- devkitARM はホストに入れず Docker (`devkitpro/devkitarm`) でビルド (環境によっては apt.devkitpro.org に
  接続できないため。Docker Hub 経由)。`devkitpro/devkitarm` には libctru / citro2d / citro3d /
  libpng / zlib は入っているが ffmpeg は無い。
- `bannertool` (Epicpkmn11 版) と `3dstool` はソースからビルド。bannertool の submodule
  (`buildtools`) が `git://github.com/...` で、環境によって接続タイムアウトする
  → `git -c url."https://github.com/".insteadOf=git://github.com/ submodule update` で解決
  (`scripts/setup-tools.sh` に反映)。
- `makerom` v0.19.0 は既に導入済みのものを使用。

### ffmpeg のクロスビルド (`scripts/build-ffmpeg.sh`)
- 3Damnesic の `ffmpeg-configure3ds` を参考に、使うものだけ有効化 (decoder: h264/aac、
  parser: h264/aac、demuxer: mov/h264、protocol: file)。swscale/avfilter は不要
  (色変換は Y2R)。
- ffmpeg 6.1.1 でのビルドは `libavcodec/kbdwin.c` で失敗: newlib の `int32_t` が `long` で、
  新しい GCC が `int*` との不一致をエラー扱いにする。サイズは同じなので
  `-Wno-error=incompatible-pointer-types -Wno-error=int-conversion` で回避。
- 6.1.1 は libavutil の FFT テーブル (`ff_tx_tab_*`、AAC 用) だけで **BSS が約 17MB** になるため
  4.4.6 に変更 (BSS は約 0.9MB に)。`main.c` は新旧どちらの API でもビルドできるようにしてある
  (`LIBAVCODEC_VERSION_MAJOR >= 59` で分岐)。

### ROM 本体で詰まった点 (すべて AzaharPlus 上で調査)
1. **`avformat_open_input("romfs:/video.mp4")` が `AVERROR_PROTOCOL_NOT_FOUND`**:
   `romfs:` を ffmpeg がプロトコル名と解釈する。`file:romfs:/video.mp4` で解決。
2. **`avformat_find_stream_info` で無限に止まる**: 切り分けに手間取った (下記の誤診含む)。
   本当の原因は **メインスレッドのスタックが 32KB (libctru 既定) で、H.264 デコードで溢れた**こと。
   決め手は Azahar のログ (`HW.Memory <Error> unmapped Write32 0x07FFF...`、ヒープ先頭
   0x08000000 の直下への書き込み)。`u32 __stacksize__ = 0x40000;` で解決。CIA 版は RSF の
   `StackSize` で決まる。
   - 誤診1: ffmpeg の pthread 検出 (`--disable-pthreads` を追加。害は無いのでそのまま)。
   - 誤診2: ARM asm の不具合 (`--disable-asm` で試したが無関係。asm は有効に戻した)。
   - 誤診3: BSS 17MB によるヒープ不足 (関係なかったが、4.4.6 化でどのみち解消)。
3. **映像が 90°回転して引き伸ばされて表示される**: citro2d は `Tex3DS_SubTexture` の
   `top < bottom` を「90°回転して詰められた画像」と解釈する (`Tex3DS_SubTextureRotated`)。
   PICA のテクスチャはメモリ先頭行が v=1.0 側なので、反転なしで書いて
   `top=1.0, bottom=1-h/TEX_H` にすれば正しい向きになる。
   - この調査中に Y2R の `BLOCK_8_BY_8` 直書きを疑って、Y2R は線形出力 → `GX_DisplayTransfer`
     でタイル化する方式に変えたが、**これは別の問題を生んだ (次項)**。8x8 直書きが元々正しかった。
4. **上画面が最初の 1 フレームから更新されない (AzaharPlus)**: 線形 Y2R + `GX_DisplayTransfer`
   方式では、`lin` (Y2R 出力) は常に最新なのに、転送先のテクスチャメモリが更新されず最初の
   フレームのまま固まった。開発用の短い動画では最初の 1 秒付近で止まっていたのを見落とし、
   実際の動画 (冒頭が暗転 + ロゴだけ) の変換で発覚した。
   `GSPGPU_InvalidateDataCache` (lin / tex) を呼んでも直らず、デバッグ用に `lin` と `tex.data` を
   CPU で読んで SD に書き出した後だけ直った (エミュレータのラスタライザキャッシュ絡みと推測。未確定)。
   **Y2R の `BLOCK_8_BY_8` でテクスチャへ直接書く方式に戻して解決** (3Damnesic が実機で使っている方式でもあり、
   GPU 転送が 1 回減る)。スクリーンショットの確認は「1 枚が正しい」ではなく
   「時間をおいた複数枚が違う場面になっている」ことまで見ること。
5. **音声が使えない環境で停止**: エミュレータに DSP ファームウェアが無く `ndspInit` が
   `0xD880A7FA` で失敗 → 音声パケットを処理し続けて空きバッファ待ちでデコードスレッドが
   固まった。`ndspInit` 失敗時は音声ストリームを捨てて映像だけ再生するようにした。
   - エミュレータ (HLE DSP) では、ダミーの `sdmc:/3ds/dspfirm.cdc` (0 埋め 256KB。エミュレータの
     SD 領域にだけ置いてある) を置くと `ndspInit` が通る。実機の吸い出し済みファームではない。

### 生成ツール
- ffmpeg の mp4 インターリーブは問題なし (映像/音声パケットが交互に並ぶ)。それでも ROM 側は
  映像キュー 12 フレーム / 音声 48 バッファで余裕を持たせてある。
- title_id の UniqueId は `(下位32bit) >> 8`。例 `000400000FF3A000` → `0xFF3A0`
  (最初のテスト用 ID を取り違えて UniqueId の桁を勘違いしていたのをユニットテストが検出)。
- CIA 化は `makerom -f cia -elf ... -rsf ... -icon ... -banner ... -romfs ... -exefslogo -target t -desc app:4`。
  RSF は `rom` 用に最低限のサービス (APT:U, dsp::DSP, fs:USER, gsp::Gpu, hid:USER, ptm:u, y2r:u など) を許可。
- 生成した CIA を Azahar にインストール (初回は確認ダイアログ) → 起動して、タイトル名・アイコン・
  config (loop/volume)・映像・下画面を確認。

### エミュレータ操作のメモ
- `scripts/run-emu.sh start|shot|stop`。`timeout N AppImage` だけでは本体 (`bin/azahar`) が
  残って何個も溜まる (一時は 11 個残っていた)。`pkill -f` は自分のシェルのコマンドライン
  にもマッチするので、パターンは `[a]zahar` のようにブラケットで書く。
- gdbstub (24689) はゲストが止まっている状態の新規インスタンスには安定して繋がらず、
  古いインスタンスに繋がって誤診の原因になった。ログ (`azahar_log.txt` の
  `HW.Memory <Error>`) とアプリ内 SD ログ (`-DDEBUG_LOG`) の方が確実だった。

### 実機での最初の確認 (2026-10-26) と RSF の修正
- 旧3DS (CFW) で、実動画の CIA / テスト CIA の両方が起動直後に ErrDisp
  「The SD card was removed.」。映像・音声は一瞬も出ず、デバッグ版でも SD にログが出なかった
  (= `main` に入る前に落ちている)。`dspfirm.cdc` は `sdmc:/3ds/dspfirm.cdc` で正しい。
- 最初に疑った `APT_SetAppCpuTimeLimit(80)` は的外れ (起動前に落ちているので無関係)。
  ただし 80→30 に下げたのは安全側として残した。
- **原因 (有力、実機での再確認待ち)**: 生成した CIA の ExHeader の権限不足。実機で動いている
  実績のある CIA (FBI.cia / Universal-Updater.cia) と ExHeader を自作パーサで比較して判明:
  - SVC (システムコール) 許可マスクが f0〜f2 の 3 組しか無い (実績 CIA は f0〜f5)。
    RSF に `SystemCallAccess` を書いておらず、さらに `makerom -desc app:4` がテンプレートで
    サービス一覧・SVC 制限を上書きしていた (出力のサービス一覧に私の指定に無い `dlp:*`、`ldr:ro` が入り、
    `gsp::Lcd`、`ptm:sysm` が欠けていた)。
  - VRAM (`1f000000-1f5fffff:r`) と DSP (`1ff00000-1ff7ffff`) のメモリマッピングが無い
    (citro3d の描画先 VRAM が使えない)。
  - FileSystemAccess が `DirectSdmc` だけ (書き込み用の `DirectSdmcWrite` 無し → デバッグログも書けない)。
  - `Logo: None` (定番は `Nintendo`)。
  AzaharPlus はこれらを一切検査しないので、エミュレータでは動いて実機でだけ落ちた。
- 修正: RSF を定番構成 (SystemCallAccess / MemoryMapping / IORegisterMapping / FileSystemAccess 全部 /
  サービス一覧 / `Logo: Nintendo`) にし、`-desc` を外した。修正後の ExHeader が FBI と同じ構造に
  なったことを確認 (サービス一覧、メモリマッピング、フラグ類)。makerom 0.19 では FS 権限名が
  `TwlCard`→`TwlCardBackup`、`TwlNand`→`TwlNandData` に変わっている点に注意。
- 教訓: **エミュレータで動く ≠ 実機で動く** (権限・SVC・メモリマップは実機のみ検査)。
  既存の実績 CIA があれば ExHeader を比較するのが最も確実。`tool/tests` に RSF の必須項目テストを追加。

### 実機で起動できた後 (2026-10-26)
- RSF 修正後、旧3DS で CIA が起動し、上画面の映像・下画面の画像が出た (権限不足が原因だったことを実機で確認)。
  ただしカクつく。デコードを旧3DSではシステムコア(1)で動かしていて、CPU 時間の 30% しか使えないのが
  有力な原因 → 旧3DS はデコードをアプリコア(0)で動かす (メインは待機が主で、デコードは低優先度スレッド)
  に変更。APT_SetAppCpuTimeLimit は使わなくなった。`light` プリセット (320x192/20fps) で作り直し。
- タイトル (アイコン選択) 音は mp3 等も指定可能に (`select_sound.(wav|mp3|ogg|flac|m4a|aac)`)。
  バナー音の上限 3 秒に合わせて先頭 3 秒を使い、末尾 0.3 秒をフェードアウト。

### 画質の検討 (2026-10-26、実機で light が滑らかに動いた後)
- 方法: 実際の動画の 40 秒クリップを複数の設定でエンコードし、デバッグビルド (`sdmc:/test_video.mp4` と
  `sdmc:/test_config.json` で差し替え可能) の AzaharPlus 上でデコード時間を測定 (20fps の予算は 50ms/フレーム)。
  light (実機で滑らかと確認済み) の 42.8ms を基準に比較。SSIM は時刻合わせがずれて不安定だったので不採用、
  同時刻のフレームを並べて目視。
- 結果 (ms/フレーム): light 320x192/250k 42.8 / 360x216/400k 45.1 (+5%) / 352x208/400k 45.6 /
  400x240/400k 48.4 (+13%) / 400x240/250k 46.5 / 320x192/250k+デブロック 46.4 / 400x240/400k+デブロック 56.0 (+31%)。
- 分かったこと: **画質を左右するのはビットレート** (250→400kbps で輪郭・細部が明確に改善)。解像度を上げる
  コストは小さい (+5〜13%)。デブロッキングフィルタはデコード +24〜31% の割に画質の改善が小さい → 不採用
  (`config.json` の `deblock` と `VideoPreset.deblock` は用意したが、どのプリセットも無効)。
- プリセット `medium` (360x216/20fps/400k) と `high` (400x240/20fps/400k) を追加。実機の評価待ち。

### 入力エラーのハンドリング強化とテスト (2026-10-26)
- 洗い出し (不正入力を一通りかけて現状を確認) で見つかった問題:
  - `volume: "loud"` など型違いの meta で traceback。
  - 300 文字のタイトルが検証なしで通り、SMDH 側で黙って切られる。
  - 出力先が作れないと traceback、ディレクトリを指定すると makerom の生エラー。
  - 偽の ELF で makerom がクラッシュ (`free(): invalid pointer`)。
  - 壊れた動画・画像で ffmpeg の生ログが出て、どのファイルが原因か分からない。
  - 日本語タイトルだと NCCH の製品名が UTF-8 の途中で切れた不正なバイト列になる (ホームメニュー側の SMDH は正常)。
- 対応: `validate.py` を新設して事前検証を集約 (重い処理の前に全部確認)。meta は型・長さ・制御文字・BOM・巨大ファイルまで検証。
  製品名は ASCII のみに (`rsf_title`)。出力は一時ファイル経由で置き換え。ELF はヘッダ (32bit ARM LE) を確認。
  `video.(mp4|mkv|...)`、`icon/bottom.(png|jpg|...)`、`select_sound.(wav|mp3|...)` を受け付ける。非正方画素 (SAR≠1) の動画は表示上の
  縦横比に直してからフィット。終了コード 0/1/2/130、`--debug`、`--no-compress` を追加。
- テストを 16 → 180 件に。ミューテーション確認 (実装を意図的に壊して、対応するテストが落ちるか) を 15 通り実施して全て検出
  (最初の 1 回は ELF 不在でテストが丸ごとスキップされ「OK」に見えたので、環境を揃えて再確認した)。
  その過程でテストが見つけた実バグ: バージョンの正規表現 `\d` がアラビア・インド数字 (`١.٠.٠`) を通していた (ASCII 限定に修正)。
- テストが遅い原因は makerom の ELF コード圧縮 (1 回 約 7.8 秒) → テストでは `--no-compress` 相当で省き、圧縮ありは 1 件だけ確認。

### 終了時フェードアウト・テンプレート運用 (2026-10-26)
- 実機 (旧3DS) の `high`: 処理スピードがふらふらして、1.0x で再生できる時もあるが基本 0.8x ぐらいに聞こえ、
  その間を行き来する。デコードが再生速度ぎりぎりで、音声データの供給が追いつく/追いつかないを繰り返している症状と一致。
  → `high` は New 3DS 向けのまま。デコードが遅れたときに音声を守る仕組み (遅れたら次のキーフレームまで映像のデコードを
  飛ばす等) は未実装。
- ROM: ループなしの動画は、最後まで再生し終えると上下画面を約 1 秒 (60 フレーム) かけて黒くフェードアウトしてから終了。
  上画面は最後のフレームに黒の矩形を重ねて不透明度を上げ、下画面は保持した BGR8 の複製を暗くして書き戻す。
- **見つかった不具合: ループなしだと再生が終わってもアプリが終了しなかった**。音声の再生位置は「再生中のバッファ」から
  求めるため、最後のバッファが再生し終わると時計が総再生時間 (3.008 秒) に届かず (2.995 秒で止まる)、終了条件が
  永久に成立しなかった。今までループなしを試していなかったので気づかなかった。→ 「積んだ音声バッファが全て
  再生し終えた」(`audio_idle`) も終了条件に追加。エミュレータでフェード 8 コマを撮って上下とも滑らかに黒くなることを確認。
- ツール: `meta.json` に `preset` と `output` (出力ファイル名) を追加。優先順位は「引数 > meta.json > 既定」。
  `scripts/mkcia.sh MyMovie` のように名前だけで `template/<名前>/` を解決し、`out/<output>.cia` に出力
  (`--list`、`--output-dir`、`-o` あり)。`output` はディレクトリ・FAT で使えない文字・制御文字・長すぎる名前を拒否。
  出力ファイルの権限が一時ファイル由来の 0600 になっていたのを、通常の umask に従う権限に修正 (テストで検出)。
- 配置: `examples/template` → `template/example`。個人の動画を入れたテンプレートは大きいので、
  `.gitignore` で `template/*` は `example` 以外コミット対象外にした (`out/` も対象外)。
- テスト 222 件 (preset/出力名/解決順の 28 件、テンプレート名解決の 14 件などを追加)。

### GUI (2026-10-26)
- 実機で、終了時のフェードアウトとホームへの復帰が正しく動くことを確認 (ユーザー確認)。
- Tkinter (標準ライブラリ) で GUI を作成 (`scripts/mkcia-gui.sh`)。ロジックを Tk 非依存の `gui_model.py` に置き、
  `gui.py` は画面とイベントだけにした (Tk の無い環境でもモデル層をテストでき、画面はダイアログを差し替えてテストできる)。
- 外部コマンドを中止できるよう `proc.run` を Popen + ポーリングに変更 (`Cancelled`、`set_cancel_event`)。
  副作用で見つかった罠: `_probe` / `encode_video` / `check_tools` の `except MkciaError` が `Cancelled` を「読めません」
  「エンコードに失敗」に言い換えてしまう (中止がエラー扱いになる) → `except Cancelled: raise` を先に置いた (テストで固定)。
  中止時に子プロセスのパイプを閉じ忘れて ResourceWarning が出ていたのも修正 (`-W error::ResourceWarning` で確認)。
- 素材の差し替えは「検証してからコピー」: 壊れたファイルでテンプレートを壊さない。`video.mp4` を `video.mkv` に替えたとき
  古い mp4 が拡張子の優先順で使われ続けないよう、同じ種類の古いファイルを消す。meta.json の保存は未知のキーを保持し、
  一時ファイル経由で置き換える。
- Tk の落とし穴: ウィンドウを閉じるときに `after` で予約した定期処理を取り消さないと `invalid command name "...pump"` が
  出る → `<Destroy>` で取り消す。レイアウトは、ヒントを右の列に置くと入力欄が縮む (列の要求幅が足りなくなる) ので下に置く。
  `event_generate("<Control-s>")` は非表示ウィンドウには届かないので、テストでは deiconify + focus_force してから送る。
- テスト 347 件 (GUI の通し操作 55 件を含む)。ミューテーション確認 8 通りで全て検出。画面が無い環境では GUI のテストはスキップ。
  GUI の実機デスクトップでの使い勝手は手動で確認済み (問題なし)。

### タイトルID の範囲 (2026-10-26、GUI で実機ユーザーが踏んだ)
- 症状: タイトルID `0004000011451400` で、最後の CIA 化 (makerom) になって初めて
  `[ID ERROR] Unique ID is out of range.` で失敗。入力の不備なのにツールは事前に気づけなかった。
- 原因: ユニークID (title_id の bits 8..27、`下位32bit >> 8`) は **20bit (最大 0xFFFFF)** まで。
  実測: `000400000FFFFF00` は OK、`0004000010000000` / `0004000011451400` / `00040000FFFFFF00` は NG。
  私が README・入力ヒント・検証に「`00040000xxxxxx00` (6 桁)」と書いていたのが誤りで、正しくは
  `000400000xxxxx00` (x は 16 進 5 桁、範囲 `0004000000000000`〜`000400000FFFFF00`)。
- 対応: `parse_meta` にユニークID の範囲チェックを追加 (範囲外なら近い有効な ID を例として出す)。GUI の入力中検証でも同じ赤字が出る。
  README / GUI のヒントを修正。誤った上限を前提にしていたテストを直し、実測の境界 (0xFFFFF / 0x100000) のテストを追加。
- 教訓: 外部ツールの制約 (範囲・長さ) は、ドキュメントの記憶ではなく実測してから検証に入れる。最終段まで気づけない検証漏れは
  GUI のように「入力しながら確認する」使い方で特に目立つ。

### 公開に向けた整理 (2026-10-26)
- GUI で生成したテンプレート (実動画 2 本) が旧3DS の実機で正しく再生されることを確認し、一通り完成とした。
- 公開前に、全 11 コミットの全リビジョン (テキストとバイナリ) を、パスワード・トークン・メールアドレス・IP・
  ホスト名・ユーザー名/パスなどの文字列でスキャンして、機密・環境固有の情報が無いことを確認した
  (含まれていたのは、タイトルID のような任意の値と、コミットの作者表記だけ)。履歴は書き換えずにそのまま公開。
- README を英語 (`README.md`) と日本語 (`README.ja.md`) に分けて簡潔にし、技術的な内容は `docs/EN`・`docs/JA`
  (使い方 / 仕組み / 開発) に移した。MIT の `LICENSE` と、同梱 ROM に含まれる FFmpeg (LGPL) などの
  `THIRD_PARTY_NOTICES.md` を追加。
- `scripts/run-emu.sh` から個人環境のパスを除き、エミュレータは環境変数 `AZAHAR` / PATH から探すように変更。
  停止は「このスクリプトが起動したプロセス」(環境変数の目印) だけを対象にして、他のエミュレータを巻き込まない。
  `scripts/mkcia.sh` などは `python3.12` 固定をやめて `python3` にした。

### 公開後のレビューを受けた改善 (2026-10-26)
別の AI による公開リポジトリのレビューのうち、次を取り入れた。
- **テストが外部ツール無しの環境で 3 件落ちる** (実測で再現: クリーンな Docker コンテナで 349 件中 失敗 1・エラー 2・スキップ 180)。
  本体のバグではなく、テストのモック漏れ: ① `cia.run` を差し替えても `cia.find_tool("makerom")` が実物を探す、
  ② `validate.run` を差し替えても `_probe` 内の `find_tool("ffprobe")` が実物を探す、③ 「ffmpeg などは存在する」を暗黙の前提にした
  テスト。→ `find_tool` も差し替え、③ は実物に依存しない偽の探索関数にした。DEVELOPMENT.md の「ツールが無い環境ではスキップ」と
  矛盾していたので、再現と同じクリーン環境 (python:3.9/3.12/3.13-slim) で全件通ることを確認。
  教訓: 「ツールの有無で挙動が変わるコード」のテストは、手元にツールがある環境では落ちない。クリーン環境での確認を CI に入れる。
- **CI を追加** (`.github/workflows/ci.yml`): `unit` (外部ツール無し・Python 3.9/3.12/3.13)、`full` (ツール一式 + xvfb で全テスト +
  サンプル CIA の生成)、`release` (`v*` タグで `Example.cia` を Release に添付)。`actionlint` で検証し、`full` と同じ手順を
  ubuntu:24.04 のコンテナで再現して確認。
- `scripts/setup-tools.sh` が `makerom` もビルドするように (CI で必要。手動導入が不要になる)。3 つのツールとも、動作確認した
  コミット/タグに固定 (再現性)。
- **雛形生成** (`scripts/mkcia.sh --new NAME`): `template/example` をコピーして `title` を NAME、`title_id` を他と重ならない有効な値にする。
  コピーした時点でそのままビルドでき、READMEのクイックスタートは「まず example をそのままビルド → `--new` で自分の分を作る」の順にした。
  コピーは一時ディレクトリで行い、失敗しても何も残さない (テストで固定)。
- README に **操作方法** (START で終了、ループなしは自動でフェードアウトして戻る、HOME は通常どおり、音量などの操作は無い)、
  **音が出ないとき** (DSP ファームは CFW 導入手順でダンプする標準ファイル。手順書を参照)、**New 3DS は未検証** の明記を追加。
- クリーンな ubuntu:24.04 コンテナで `full` ジョブの手順を再現したところ、**`setup-tools.sh` が `zip` の無い環境で失敗**した
  (bannertool の既定の `make` が配布用 zip まで作ろうとする。手元には zip があったので気づかなかった)。必要なのはバイナリだけなので、
  成果物のターゲット `output/linux-x86_64/bannertool` だけをビルドするようにした。再現用スクリプトで最初は `| tail` でパイプしていて、
  ツール作成の失敗が隠れた (後続の「ツールが見つかりません」で発覚)。`set -o pipefail` を付けて再実行し、3 ツールのビルド・
  全 372 テスト・サンプル CIA の生成が通ることを確認。
- 見送ったもの: `main.c` の分割、ビルドの完全な再現性 (Docker イメージのダイジェスト固定・FFmpeg の sha256 検証)、
  `prebuilt/` を Release 添付にすること、`pyproject.toml` 化。必要になったら対応する。

### icon / bottom を動画から作る (2026-10-26)
- 要望: テンプレートに `icon.*` / `bottom.*` が無ければ動画から作る。あれば作らない。mkv は埋め込み画像があるかもしれないので、
  それを優先し、無ければ任意の秒数のフレームを抜く。
- 実装 (`extract.py`): ① 動画の埋め込み画像 (ffprobe で `disposition.attached_pic == 1` の映像ストリーム。mkv の添付画像も mp4 の
  カバーアートも、この形で見える。`-map 0:<番号> -frames:v 1` で取り出せる) → ② 無ければ指定秒数のフレーム。
  秒数は `meta.json` の `frame_at` / CLI の `--frame-at` (引数 > meta)。**明示したときは埋め込み画像より優先**。省略時は長さの 15%
  (最大 30 秒。冒頭の暗転やロゴを避ける。実動画で 15% は 30 秒地点になり、ダンサーが映った)。
- アイコンは中央を正方形に切り抜く (横長のフレームをそのまま 48px に収めると小さな帯になる)。ユーザーが用意したアイコンは従来どおり
  余白付きで全体を収める。バナーは「バナー画像 → ユーザーのアイコン → 動画から作った画像」の順。
- 必須ファイルは `meta.json` と動画だけになった。あるのに壊れている/空/ディレクトリの `icon` は、黙って動画から作り直さずエラーにする。
  `frame_at` が動画の長さ以上なら、エンコード前に弾く (icon / bottom が両方あるときは使われないので警告だけ)。
- GUI: icon / bottom を任意にし (削除できる)、未設定のときは「ビルド時に動画から作る」と表示。抽出位置の入力欄を追加。
- 既存の `-map 0:v:0` は、カバー画像 (attached_pic) が先に来るコンテナだと、カバーを動画として選びうるので `0:V:0` (カバーを除く) にした。
  ただし ffmpeg で作れる mp4 / mkv ではカバーは必ず後ろの番号になるため、この違いはテストで再現できない (ミューテーションで
  検出できない唯一の変更。保険として残している)。
- ミューテーション確認で、最初「アイコンの切り抜きを外しても通る」テストの穴 (サイズ 48x48 しか見ていなかった) が見つかり、
  中央だけ赤い横長画像で内容を確認するテストを追加した。全角の数字 (`５`) は float() が読めるので、`--frame-at` も受け付ける。

### 既定のタイトル選択音 (2026-10-26)
- 要望: homebrew には、タイトル選択音に独自の音ではなく既定の音を使い回すものがある。`select_sound.*` が無いときは既定の音を載せる。
  `--new` で作るテンプレートは最初からそれで。
- それまでは、無いと 0.1 秒の無音だった。→ 既定の音に変更。権利の問題を避けるため、他人の素材ではなく ffmpeg の `aevalsrc` で
  **自分で合成した 2 音のチャイム** (E5 → A5、減衰、約 0.7 秒、32kHz モノラル、ピーク約 −3dB) を `tool/mkcia/default_select_sound.wav`
  として同梱 (`scripts/make-default-sound.sh` で再生成できる)。実機 (旧3DS) のホームメニューで、アイコンを選んだときに正しく鳴ることを確認済み。
- 「無い = 無音」でなくなったので、無音にしたい人は無音の `select_sound.wav` を置く (ドキュメントに明記)。壊れた `select_sound.*` は
  黙って既定に差し替えず、エラー (icon と同じ方針)。
- `--new` は雛形の `select_sound.*` を引き継がない (`select_sound_notes.txt` のような似た名前は対象外)。`template/example` からも
  独自の音声を外したので、Release の `Example.cia` も既定の音になる。
- GUI は未設定のとき「既定のタイトル選択音を使う」と表示。

### Windows 対応の確認 (2026-10-26)
- 要望: Windows でも動くか。Windows 11 の VM (OpenSSH 接続) で、ツール一式を **ユーザー領域の一時フォルダに展開するだけ**
  (インストールなし: NuGet の Python、gyan.dev の ffmpeg essentials、makerom 0.19.0 / bannertool 1.2.2 / 3dstool 1.2.6 の配布 exe) で検証した。
- 結論: **CLI も GUI も動く**。同じ example から作った CIA は、ExHeader と ExeFS が Linux の CI 産とバイト一致 (差は RomFS = ffmpeg の版違いによる動画だけ)。
  実機の起動可否を左右する権限まわりが同一であることの確認になる。実機 (3DS) での再生確認は Linux 産のみ。
- 見つかった問題と対処:
  - `find_tool` が `ffmpeg` → `ffmpeg.exe` を補わず、全ツールが「見つからない」扱いだった → PATHEXT で拡張子を補う。
  - **`tempfile.mkstemp` / `mkdtemp` が作る一時物は、Python 3.12 以降の Windows では ACL まで所有者専用になり、`os.replace` / `rename` で
    本来の名前にしても残る**。ssh 経由 (昇格トークン) で `--new` したテンプレートを、デスクトップ側 (非昇格トークン) の GUI が
    `PermissionError` で開けず、起動直後に落ちた。→ 最終的な成果物になるもの (CIA、`meta.json`、素材、`--new` のテンプレート)
    は `fsutil.create_tmp_file` / `create_tmp_dir` (排他的に作るだけ。umask / 親の継承に従う) で作る。Linux でも素材のコピーが 0600 だった点が直った。
  - テストが POSIX 前提 (`bash` / `sleep` / `echo` を子プロセスに使う、`os.geteuid`、権限ビットと umask、シンボリックリンク作成) だった →
    子プロセスは Python 自身にし、Windows / root では権限系を、リンクを作れない環境ではリンク系をスキップ。`read_text()` の既定エンコーディング
    (cp932) 依存もテスト側にあった。
  - ssh 越しの (デスクトップに繋がっていない) セッションでは Tk にフォーカスが渡らず、`<Control-s>` のテストだけ落ちる。
    その場合はスキップにした。デスクトップ側 (スケジュールタスクで対話セッションへ起動) では GUI テスト 56 件が全て通る。
  - **makerom は Windows で、出力先のパスをシステムのコードページで扱う**。日本語ロケールの VM では通ったが、GitHub の windows ランナー
    (英語ロケール) の CI で「出力名/出力先に日本語」の 2 テストが `Failed to create ...` で落ちて発覚 (ローカルの VM だけでは見逃した)。
    → CIA は ASCII の作業ディレクトリ (`app.cia`) に作り、Python (Unicode 対応) で出力先の一時ファイルへコピー → `os.replace`。
    回帰テストは makerom に渡る出力先が出力フォルダでないことを見る (直書きに戻すと落ちることをミューテーションで確認)。
    入力側 (リポジトリや `%TEMP%` のパス) は makerom の仕様でどうにもならないのでドキュメントに明記した。
- 追加: `scripts/setup-tools.ps1` (配布 exe を `tools\bin` に取得)、`scripts/mkcia.cmd` / `mkcia-gui.cmd` (ラッパー)、`.gitattributes`
  (`.cmd` / `.ps1` は CRLF)、CI の `windows` ジョブ。`.ps1` は PowerShell 5.1 が BOM 無し UTF-8 を ANSI として読むので BOM 付きにした。
- 画面のスクリーンショットは、VM のデスクトップセッションが切断状態で `CopyFromScreen` が失敗したため撮れていない (GUI の起動と生存、
  GUI テスト 56 件の成功までは確認)。macOS は未確認。

### arm64 Linux / Apple Silicon macOS に対応 (2026-10-27)
- きっかけ: Ubuntu arm64 と M4 Mac で `scripts/setup-tools.sh` を実行すると、bannertool のビルドが
  `buildtools/make_base:171: "Unsupported host architecture."` で止まるとユーザーが報告。Mac も原因は同じで、OS は Darwin を認識できても、
  アーキテクチャ (arm64) が x86_64 / i686 以外として弾かれる (ユーザーの推測どおり)。bannertool の README の Docker 手順も、
  arm64 のホストでは arm64 のコンテナになるので同じ所で止まる。
- 一度は「非対応」と明記して事前に止める対処を入れたが、ネイティブビルドはコンパイラ任せなので `make_base` の判定に
  `arm64 aarch64` を足すだけで通ると分かり、取り下げた (最初に実機/コンテナで試さず書いたのが間違い)。
- 直した所 (すべて `setup-tools.sh` が取得直後に当てる。上流のリポジトリは触らない):
  - bannertool の `buildtools/make_base`: `arm64` / `aarch64` を受け付ける。
  - 3dstool の `CMakeLists.txt`: arm64 のコンパイラは `-m64` を受け付けないので、arm64 では付けない。同梱の `dep/lib` は x86 専用の
    事前ビルド済みライブラリなので `-DUSE_DEP=OFF` にしてシステムの OpenSSL / libcurl を使う。
  - macOS: `nproc` が無いので `sysctl -n hw.ncpu`。OpenSSL のヘッダが標準で無いので、`OPENSSL_ROOT_DIR` > Homebrew の `openssl@3` を探し、
    無ければ案内を出して止まる。
  - 出力先 (`output/<os>-<arch>/bannertool`) を実行環境から決める。
- 検証 (すべてネイティブ): arm64 Ubuntu 実機と M4 Mac の両方で、3 ツールのビルド、`example` の CIA 生成、全 440 テスト (GUI 56 件は画面が無くスキップ)
  が通った。CIA の ExHeader / ExeFS は x86_64 Linux の CI 産とバイト一致 (arm64 Ubuntu 産はサイズも同一)。
- Mac での嵌り: ssh の非ログインシェルは `/opt/homebrew/bin` が PATH に無く、Homebrew が入っていても `which brew` で見つからない
  (cmake / ffmpeg / openssl も同様)。スクリプトは `/opt/homebrew/bin/brew` と `/usr/local/bin/brew` も直接見るようにした。
- macOS の GUI は、後日ユーザーが M4 Mac で開いてサンプルをビルドし、問題なしと確認 (その CIA は ExHeader / ExeFS が x86 産と一致、動画は H.264 baseline 360x216 20fps で復号OK)。
- 後日、ユーザーが arm64 Ubuntu 産と Mac 産の CIA を 3DS 実機で再生し、x86_64 Linux 産と違いなく再生できたと確認した
  (ExHeader / ExeFS が一致しているので予想どおり)。
- Intel Mac は対象外とした (GitHub Actions の Intel Mac ランナーも無くなり、Intel Mac だけの人も減っているため。必要になったら対応する)。
- 同日、Windows の GUI で素材ごとにコンソールが一瞬開く問題 (下) も、直した後にユーザーが解消を確認した。

### Mac で GUI が起動しない: tkinter (2026-10-27)
- 報告: Mac で `scripts/mkcia-gui.sh` が「tkinter が必要」で終わる (入れ方は Debian の `python3-tk` しか書いてなかった)。
- 原因: Homebrew の `python3` (3.15) は tkinter を単体で含まない (`ModuleNotFoundError: Unsupported platform for standard library module '_tkinter'`)。
  別プロジェクト用の `python-tk@3.14` は入っていたが、`python3` は 3.15 を指すので使われない。Apple 標準の `/usr/bin/python3` (3.9) は Tk 8.5 で動くが古い。
- 対応: 案内文を、使った Python のパス/版と OS ごとの入れ方 (macOS: `brew install python-tk@<その版>`) を出すものに変更
  (`gui_model.tkinter_missing_message`。Tk 無しでテストできる)。`scripts/mkcia.sh` / `mkcia-gui.sh` は環境変数 `PYTHON` で Python を切り替えられるようにした
  (tkinter 入りの別の版が既にあるとき用)。USAGE に入れ方を追記。

### Windows で mkcia-gui.cmd が「Python」とだけ表示して終わる (2026-10-27)
- 報告: Windows VM で `mkcia-gui.cmd` を実行すると「Python」としか出ない。
- 原因: その VM には本物の Python が無く、`python` は Microsoft Store を開くだけのスタブ (`%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe`) だった。
  スタブは「Python」とだけ出して終了コード 9009 で終わる。旧ラッパーは `py` / `pyw` が無ければ `python` を呼ぶだけで、失敗も見分けなかった。
  VM で再現できた (私が検証後に Python を消したので、結果的に報告と同じ状態になっていた)。
- 対応: ラッパーは候補 (`%PYTHON%`、`py -3`、`python`、`python3`) を実際に `-c` で動かして、動いた最初のものを使う。無ければ
  「動く Python 3 が見つからない。Store のショートカットかも。python.org / winget で入れる」と表示して終了コード 1。
  GUI は、コンソールの無い `pythonw` で起動する前に、このコンソールで tkinter を確認する (起動後のエラーは見えないため)。
  `.cmd` は ASCII のみ (cmd がコードページで読むため日本語は文字化けする) なので、メッセージは英語。
  VM で、Store スタブだけの状態 (メッセージと終了コード 1)、本物の Python が PATH にある状態、`PYTHON` 指定のいずれも期待どおり、
  デスクトップのセッションでは GUI が `pythonw -m mkcia.gui` で起動することを確認した。

### Mac の GUI で「新規作成」が落ちる (2026-10-27)
- 報告: Mac (Homebrew の python 3.12 + python-tk@3.12、Tk 9.1) で「新規作成」を押すと
  `TclError: invalid command name "::tk::unsupported::MacWindowStyle"` (Linux では問題なし)。
- 原因: 標準ライブラリの `tkinter.simpledialog` が、aqua (macOS) のとき開く瞬間に `::tk::unsupported::MacWindowStyle` を呼ぶ。
  Tk 9 にはこのコマンドが無い。`filedialog` / `messagebox` はネイティブのダイアログを使うので影響しない。
- 対応: `simpledialog.askstring` をやめ、自前の `StringDialog` (Toplevel + Entry + OK/キャンセル。Enter / Esc / 閉じるボタン対応) にした。
  Linux の Xvfb でテスト (OK・キャンセル・閉じる・空文字・初期値)。再発防止に、gui.py が `simpledialog` を使わないことを見るテストも入れた。
- ssh 越しの Mac では、Homebrew の Python (Tk 9) が `Tk()` で例外ではなく **segfault (exit 139)** するので、GUI テストは macOS の ssh では
  試さずスキップするようにした (Mac のターミナルからなら動く)。Mac の実画面でダイアログが開くかは、ユーザーの確認待ち。

### Windows の GUI でテンプレートを選ぶと、コンソールが一瞬いくつも開く (2026-10-27)
- 報告: Windows で GUI のテンプレートを選ぶと、ターミナルが複数一瞬だけ開いて閉じる。直後にサムネイルが出る。Mac では起きない。
- 原因: GUI は `pythonw` (コンソール無し) で動く。コンソールの無いプロセスが子プロセス (サムネイル用の ffmpeg、素材の確認用の ffprobe) を起こすと、
  Windows は既定で子のためにコンソールウィンドウを新しく開く。素材ごとに 1 回ずつなので「複数」になる。ユーザーの推測どおり。
- 対応: 子プロセスの起動に共通の引数 `proc.SUBPROCESS_KWARGS` を作り、Windows では `creationflags=CREATE_NO_WINDOW` を付ける。
  `stdin` も `DEVNULL` にする (コンソールが無いと標準入力のハンドルが無効で起動に失敗することがある。ffmpeg が端末入力を読みに行くのも防ぐ)。
  `proc.run` と、`subprocess.run` を直接呼んでいたサムネイル (`gui_model.make_thumbnail`) の 2 か所に適用。
- 検証: 引数が Popen / run まで渡ることを、Linux でも通るテスト (引数を差し替えて見る) で確認し、外すと落ちることをミューテーションで確認。
  Windows では pythonw から `proc.run` で子を起こせる (`creationflags=134217728`、stdin 塞ぎ) ことを確認。ウィンドウが開かないことの目視は、
  VM のデスクトップセッションが切断状態で画面を撮れないため未実施 (ユーザーの確認待ち)。

## 未解決・今後
- 旧3DS: `light` / `medium` は映像・音声とも滑らか、タイトル音・終了時のフェードアウトも確認済み。
  `high` は再生できるが、デコードが再生速度ぎりぎりで音声が少し間延びする。デコードが遅れたときに
  音声を守る仕組み (遅れたら次のキーフレームまで映像のデコードを飛ばす等) は未実装。
- **New 3DS は未確認**。コア 2 の使用 (RSF の `AffinityMask` / `CanAccessCore2`) と、`high` / `standard` が動くか。
- 音声同期の厳密な評価 (リップシンクのずれ) と、ループ時のタイムライン継ぎ目の長時間確認は未実施。
- 旧3DS 向けに `light` でも足りない場合のプリセット追加 (解像度/fps をさらに下げる)。
