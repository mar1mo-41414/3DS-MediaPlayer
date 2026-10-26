# HISTORY

作業履歴・調査の経緯・失敗談・未解決事項。確定した最新情報は README.md を参照。

## 2026-10-26 初期実装 (start-note.md に基づく)

### 環境構築
- devkitARM はホストに入れず Docker (`devkitpro/devkitarm`) でビルド (apt.devkitpro.org が
  ブロックされるため。Docker Hub 経由)。`devkitpro/devkitarm` には libctru / citro2d / citro3d /
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
   Twinkle Night (冒頭が暗転 + ロゴだけ) の変換で発覚した。
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
- 旧3DS (CFW) で、Twinkle Night / テスト CIA の両方が起動直後に ErrDisp
  「The SD card was removed.」。映像・音声は一瞬も出ず、デバッグ版でも SD にログが出なかった
  (= `main` に入る前に落ちている)。`dspfirm.cdc` は `sdmc:/3ds/dspfirm.cdc` で正しい。
- 最初に疑った `APT_SetAppCpuTimeLimit(80)` は的外れ (起動前に落ちているので無関係)。
  ただし 80→30 に下げたのは安全側として残した。
- **原因 (有力、実機での再確認待ち)**: 生成した CIA の ExHeader の権限不足。ユーザーの実機から取った
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
- 方法: Twinkle Night の 40 秒クリップを複数の設定でエンコードし、デバッグビルド (`sdmc:/test_video.mp4` と
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

## 未解決・今後
- **実機未確認**。旧3DS での性能 (デコードが間に合うか)、New 3DS でのコア 2 使用 (RSF の
  `AffinityMask`/`CanAccessCore2` が足りているか)、HOME メニューから戻ったときの下画面の再描画。
- 旧3DS 向けに `light` でも足りない場合のプリセット追加 (解像度/fps をさらに下げる)。
- 音声同期は ndsp の再生位置ベースの実装をエミュレータ (HLE DSP) 上でログ確認したのみ。
  実際の耳での確認、リップシンクのずれ評価は未実施。
- ループ時のタイムライン継ぎ目 (音声サンプル数でオフセット) の長時間確認は未実施。
