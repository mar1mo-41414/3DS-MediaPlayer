// 3DS 動画プレイヤー ROM 本体。
// romfs:/ の決まったファイル名だけを読む (テンプレートが変わってもコードは共通):
//   video.mp4   H.264 + AAC (生成ツールが 3DS 向けに事前エンコード)
//   bottom.png  下画面に表示する静止画
//   config.json {"loop": true, "volume": 1.0}
//
// 同期方針: ndsp の再生位置 (オーディオクロック) を正とし、映像側が遅れたら
// フレームを捨て、進みすぎなら待つ。

#include <3ds.h>
#include <citro2d.h>
#include <png.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/channel_layout.h>
#include <libavutil/opt.h>
#include <libswresample/swresample.h>

#define TOP_W 400
#define TOP_H 240
#define TEX_W 512
#define TEX_H 256

#define VQ_SIZE 12  // デコード済み映像フレームのキュー長
#define ABUF_NUM 48 // ndsp に積む波形バッファ数
#define ABUF_SAMPLES 4096

#ifdef DEBUG_LOG
static void dbg(const char *fmt, ...)
{
    FILE *f = fopen("sdmc:/mediaplayer.log", "a");
    if (!f)
        return;
    va_list ap;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}
#else
#define dbg(...) ((void)0)
#endif

// "romfs:" を ffmpeg がプロトコル名と解釈するので file: を前置する
#define ROMFS_VIDEO "file:romfs:/video.mp4"
#define ROMFS_BOTTOM "romfs:/bottom.png"
#define ROMFS_CONFIG "romfs:/config.json"

// 3dsx のメインスレッドのスタックは既定 32KB で、ffmpeg の H.264 デコードでは足りない。
// (CIA 化したときのスタックは RSF の StackSize で決まる)
u32 __stacksize__ = 0x40000;

// ---------------------------------------------------------------- config

typedef struct {
    bool loop;
    float volume;
} Config;

// 平坦な {"key": value} だけを想定した最小スキャナ。
static const char *json_find(const char *buf, const char *key)
{
    char pat[48];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(buf, pat);
    if (!p)
        return NULL;
    p = strchr(p + strlen(pat), ':');
    if (!p)
        return NULL;
    p++;
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')
        p++;
    return p;
}

static void config_load(Config *cfg)
{
    cfg->loop = false;
    cfg->volume = 1.0f;

    FILE *f = fopen(ROMFS_CONFIG, "rb");
    if (!f)
        return;
    char buf[1024];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    buf[n] = 0;

    const char *v;
    if ((v = json_find(buf, "loop")))
        cfg->loop = (strncmp(v, "true", 4) == 0) || (*v == '1');
    if ((v = json_find(buf, "volume"))) {
        cfg->volume = (float)atof(v);
        if (cfg->volume < 0.0f)
            cfg->volume = 0.0f;
        if (cfg->volume > 1.0f)
            cfg->volume = 1.0f;
    }
}

// ---------------------------------------------------------------- bottom screen

// bottom.png を 320x240 に最近傍で拡縮して下画面フレームバッファへ直接書く。
// (下画面は citro3d のターゲットに繋がないので生の BGR8 フレームバッファを使える)
static void bottom_show(const char *path)
{
    gfxSetDoubleBuffering(GFX_BOTTOM, false);

    FILE *fp = fopen(path, "rb");
    if (!fp)
        return;
    png_structp png = png_create_read_struct(PNG_LIBPNG_VER_STRING, NULL, NULL, NULL);
    png_infop info = png ? png_create_info_struct(png) : NULL;
    if (!png || !info || setjmp(png_jmpbuf(png))) {
        png_destroy_read_struct(&png, &info, NULL);
        fclose(fp);
        return;
    }
    png_init_io(png, fp);
    png_read_info(png, info);

    png_uint_32 w = png_get_image_width(png, info);
    png_uint_32 h = png_get_image_height(png, info);
    int ctype = png_get_color_type(png, info);
    int depth = png_get_bit_depth(png, info);
    if (depth == 16)
        png_set_strip_16(png);
    if (ctype == PNG_COLOR_TYPE_PALETTE)
        png_set_palette_to_rgb(png);
    if (ctype == PNG_COLOR_TYPE_GRAY && depth < 8)
        png_set_expand_gray_1_2_4_to_8(png);
    if (png_get_valid(png, info, PNG_INFO_tRNS))
        png_set_tRNS_to_alpha(png);
    if (ctype == PNG_COLOR_TYPE_GRAY || ctype == PNG_COLOR_TYPE_GRAY_ALPHA)
        png_set_gray_to_rgb(png);
    png_set_filler(png, 0xFF, PNG_FILLER_AFTER); // 常に RGBA 8bit
    png_read_update_info(png, info);

    u8 *pix = malloc((size_t)w * h * 4);
    png_bytep *rows = malloc(sizeof(png_bytep) * h);
    if (!pix || !rows)
        longjmp(png_jmpbuf(png), 1);
    for (png_uint_32 y = 0; y < h; y++)
        rows[y] = pix + (size_t)y * w * 4;
    png_read_image(png, rows);
    png_destroy_read_struct(&png, &info, NULL);
    fclose(fp);

    u16 fw, fh; // フレームバッファは 240(幅)x320(高さ) の列優先
    u8 *fb = gfxGetFramebuffer(GFX_BOTTOM, GFX_LEFT, &fw, &fh);
    for (int x = 0; x < 320; x++) {
        const u32 sx = (u32)((u64)x * w / 320);
        for (int y = 0; y < 240; y++) {
            const u32 sy = (u32)((u64)y * h / 240);
            const u8 *s = pix + ((size_t)sy * w + sx) * 4;
            u8 *d = fb + ((size_t)x * 240 + (239 - y)) * 3;
            d[0] = s[2];
            d[1] = s[1];
            d[2] = s[0];
        }
    }
    free(rows);
    free(pix);
    gfxFlushBuffers();
    gfxSwapBuffers();
}

// ---------------------------------------------------------------- player state

typedef struct {
    AVFrame *frame;
    double pts; // 秒 (ループ分のオフセット込み)
} VFrame;

typedef struct {
    ndspWaveBuf wb;
    s16 *data;
    u64 base; // この波形バッファ先頭の通算サンプル位置
} ABuf;

typedef struct {
    Config cfg;

    AVFormatContext *fmt;
    AVCodecContext *vctx, *actx;
    int vidx, aidx;
    SwrContext *swr;
    int arate;

    // 映像キュー (デコードスレッド -> メイン)
    LightLock vlock;
    VFrame vq[VQ_SIZE];
    int vq_head, vq_count;

    // 音声
    ABuf ab[ABUF_NUM];
    volatile u64 a_submitted; // 通算で ndsp に積んだサンプル数

    // ループ時にタイムラインを連続させるためのオフセット (秒)
    double loop_offset;
    double last_vpts, vdur;

    volatile int dbg_state; // デバッグ用: デコードスレッドの現在位置
    volatile int dbg_vpush, dbg_apush;
    volatile bool eof;     // (非ループ時) 末尾まで読み切った
    volatile bool quit;
    volatile double end_time; // eof 時点の総再生時間
} Player;

static Player P;

// ---------------------------------------------------------------- decode thread

static bool vq_push(AVFrame *src, double pts)
{
    while (!P.quit) {
        LightLock_Lock(&P.vlock);
        if (P.vq_count < VQ_SIZE) {
            VFrame *s = &P.vq[(P.vq_head + P.vq_count) % VQ_SIZE];
            s->frame = av_frame_alloc();
            av_frame_move_ref(s->frame, src);
            s->pts = pts;
            P.vq_count++;
            P.dbg_vpush++;
            LightLock_Unlock(&P.vlock);
            return true;
        }
        LightLock_Unlock(&P.vlock);
        P.dbg_state = 3;
        svcSleepThread(2 * 1000 * 1000);
    }
    return false;
}

#ifdef DEBUG_LOG
static u64 dec_ticks;
static int dec_frames;
static int timed_receive(AVFrame *f)
{
    u64 t = svcGetSystemTick();
    int r = avcodec_receive_frame(P.vctx, f);
    dec_ticks += svcGetSystemTick() - t;
    if (r == 0 && ++dec_frames == 24) {
        dbg("decode avg %.1f ms/frame (24f, キュー待ち除く)", (double)dec_ticks / dec_frames / (SYSCLOCK_ARM11 / 1000.0));
        dec_ticks = 0;
        dec_frames = 0;
    }
    return r;
}
static int timed_send(AVPacket *pkt)
{
    u64 t = svcGetSystemTick();
    int r = avcodec_send_packet(P.vctx, pkt);
    dec_ticks += svcGetSystemTick() - t;
    return r;
}
#else
#define timed_receive(f) avcodec_receive_frame(P.vctx, (f))
#define timed_send(p) avcodec_send_packet(P.vctx, (p))
#endif

static void video_receive(AVFrame *tmp)
{
    while (timed_receive(tmp) == 0) {
        int64_t ts = tmp->best_effort_timestamp;
        double pts = (ts == AV_NOPTS_VALUE) ? P.last_vpts + P.vdur
                                            : ts * av_q2d(P.fmt->streams[P.vidx]->time_base);
        pts += P.loop_offset;
        P.last_vpts = pts;
        if (!vq_push(tmp, pts))
            return;
    }
}

static ABuf *abuf_acquire(void)
{
    while (!P.quit) {
        for (int i = 0; i < ABUF_NUM; i++) {
            u8 st = P.ab[i].wb.status;
            if (st == NDSP_WBUF_FREE || st == NDSP_WBUF_DONE)
                return &P.ab[i];
        }
        P.dbg_state = 5;
        svcSleepThread(2 * 1000 * 1000);
    }
    return NULL;
}

static void audio_receive(AVFrame *tmp)
{
    while (avcodec_receive_frame(P.actx, tmp) == 0) {
        ABuf *b = abuf_acquire();
        if (!b)
            return;
        int n = swr_convert(P.swr, (uint8_t **)&b->data, ABUF_SAMPLES,
                            (const uint8_t **)tmp->extended_data, tmp->nb_samples);
        if (n <= 0)
            continue;
        b->wb.nsamples = n;
        b->wb.status = NDSP_WBUF_FREE;
        b->base = P.a_submitted;
        DSP_FlushDataCache(b->data, n * 4);
        ndspChnWaveBufAdd(0, &b->wb);
        P.a_submitted += n;
        P.dbg_apush++;
    }
}

static void drain_and_flush(void)
{
    AVFrame *tmp = av_frame_alloc();
    avcodec_send_packet(P.vctx, NULL);
    video_receive(tmp);
    avcodec_flush_buffers(P.vctx);
    if (P.actx)
        avcodec_flush_buffers(P.actx);
    av_frame_free(&tmp);
}

static void decode_thread(void *arg)
{
    (void)arg;
    AVPacket *pkt = av_packet_alloc();
    AVFrame *vf = av_frame_alloc();
    AVFrame *af = av_frame_alloc();

    while (!P.quit) {
        P.dbg_state = 1;
        int r = av_read_frame(P.fmt, pkt);
        if (r < 0) {
            drain_and_flush();
            if (P.cfg.loop) {
                // 音声があればサンプル数、なければ最終映像 pts でタイムラインを繋ぐ
                P.loop_offset = P.actx ? (double)P.a_submitted / P.arate : P.last_vpts + P.vdur;
                av_seek_frame(P.fmt, -1, 0, AVSEEK_FLAG_BACKWARD);
                continue;
            }
            P.end_time = P.actx ? (double)P.a_submitted / P.arate : P.last_vpts + P.vdur;
            P.eof = true;
            break;
        }
        P.dbg_state = (pkt->stream_index == P.vidx) ? 2 : 4;
        if (pkt->stream_index == P.vidx) {
            if (timed_send(pkt) == 0)
                video_receive(vf);
        } else if (P.actx && pkt->stream_index == P.aidx) {
            if (avcodec_send_packet(P.actx, pkt) == 0)
                audio_receive(af);
        }
        av_packet_unref(pkt);
    }
    av_packet_free(&pkt);
    av_frame_free(&vf);
    av_frame_free(&af);
}

// ---------------------------------------------------------------- open / init

#ifdef DEBUG_LOG
static void av_log_cb(void *avcl, int level, const char *fmt, va_list vl)
{
    if (level > AV_LOG_DEBUG)
        return;
    char line[256];
    vsnprintf(line, sizeof(line), fmt, vl);
    size_t n = strlen(line);
    while (n && (line[n - 1] == '\n'))
        line[--n] = 0;
    dbg("[av%d] %s", level, line);
}
#endif

static bool open_media(void)
{
#ifdef DEBUG_LOG
    av_log_set_level(AV_LOG_DEBUG);
    av_log_set_callback(av_log_cb);
#endif
    int r = avformat_open_input(&P.fmt, ROMFS_VIDEO, NULL, NULL);
    dbg("open_input r=%d", r);
    if (r < 0)
        return false;
    r = avformat_find_stream_info(P.fmt, NULL);
    dbg("find_stream_info r=%d", r);
    if (r < 0)
        return false;

    P.vidx = av_find_best_stream(P.fmt, AVMEDIA_TYPE_VIDEO, -1, -1, NULL, 0);
    P.aidx = av_find_best_stream(P.fmt, AVMEDIA_TYPE_AUDIO, -1, -1, NULL, 0);
    if (P.vidx < 0)
        return false;

    AVStream *vs = P.fmt->streams[P.vidx];
    const AVCodec *vc = avcodec_find_decoder(vs->codecpar->codec_id);
    P.vctx = avcodec_alloc_context3(vc);
    avcodec_parameters_to_context(P.vctx, vs->codecpar);
    P.vctx->thread_count = 1;
    P.vctx->skip_loop_filter = AVDISCARD_ALL; // デブロッキングを省いて軽くする
    if (avcodec_open2(P.vctx, vc, NULL) < 0)
        return false;
    dbg("vcodec open ok %dx%d", P.vctx->width, P.vctx->height);
    if (P.vctx->width > TEX_W || P.vctx->height > TEX_H || (P.vctx->width % 8) || (P.vctx->height % 8))
        return false; // Y2R/テクスチャの制約 (生成ツールが保証する)

    AVRational fr = vs->avg_frame_rate.num ? vs->avg_frame_rate : av_make_q(24, 1);
    P.vdur = 1.0 / av_q2d(fr);

    if (P.aidx >= 0) {
        AVStream *as = P.fmt->streams[P.aidx];
        const AVCodec *ac = avcodec_find_decoder(as->codecpar->codec_id);
        P.actx = avcodec_alloc_context3(ac);
        avcodec_parameters_to_context(P.actx, as->codecpar);
        if (avcodec_open2(P.actx, ac, NULL) < 0) {
            avcodec_free_context(&P.actx);
        } else {
            P.arate = P.actx->sample_rate;
#if LIBAVCODEC_VERSION_MAJOR >= 59
            AVChannelLayout stereo = AV_CHANNEL_LAYOUT_STEREO;
            if (swr_alloc_set_opts2(&P.swr, &stereo, AV_SAMPLE_FMT_S16, P.arate, &P.actx->ch_layout,
                                    P.actx->sample_fmt, P.arate, 0, NULL) < 0 ||
                swr_init(P.swr) < 0)
                avcodec_free_context(&P.actx);
#else
            int64_t inlayout = P.actx->channel_layout
                                   ? (int64_t)P.actx->channel_layout
                                   : av_get_default_channel_layout(P.actx->channels);
            P.swr = swr_alloc_set_opts(NULL, AV_CH_LAYOUT_STEREO, AV_SAMPLE_FMT_S16, P.arate, inlayout,
                                       P.actx->sample_fmt, P.arate, 0, NULL);
            if (!P.swr || swr_init(P.swr) < 0)
                avcodec_free_context(&P.actx);
#endif
        }
    }
    return true;
}

static bool audio_init(void)
{
    Result rc = ndspInit();
    dbg("ndspInit rc=0x%08lX", (unsigned long)rc);
    if (R_FAILED(rc))
        return false;
    ndspSetOutputMode(NDSP_OUTPUT_STEREO);
    ndspChnReset(0);
    ndspChnSetInterp(0, NDSP_INTERP_LINEAR);
    ndspChnSetRate(0, (float)P.arate);
    ndspChnSetFormat(0, NDSP_FORMAT_STEREO_PCM16);
    float mix[12] = {0};
    mix[0] = mix[1] = P.cfg.volume;
    ndspChnSetMix(0, mix);
    ndspChnSetPaused(0, true); // 映像の準備ができるまで鳴らさない

    for (int i = 0; i < ABUF_NUM; i++) {
        P.ab[i].data = linearAlloc(ABUF_SAMPLES * 4);
        if (!P.ab[i].data)
            return false;
        memset(&P.ab[i].wb, 0, sizeof(ndspWaveBuf));
        P.ab[i].wb.data_vaddr = P.ab[i].data;
        P.ab[i].wb.status = NDSP_WBUF_FREE;
    }
    return true;
}

// オーディオクロック (秒)。再生中の波形バッファと、その中の再生位置から求める。
static double audio_clock(void)
{
    static double last = 0.0;
    u16 seq = ndspChnGetWaveBufSeq(0);
    for (int i = 0; i < ABUF_NUM; i++) {
        if (P.ab[i].wb.status == NDSP_WBUF_PLAYING && P.ab[i].wb.sequence_id == seq) {
            double t = (double)(P.ab[i].base + ndspChnGetSamplePos(0)) / P.arate;
            if (t > last)
                last = t;
            break;
        }
    }
    return last;
}

// ---------------------------------------------------------------- main

int main(void)
{
    osSetSpeedupEnable(true);
    gfxInitDefault();
    romfsInit();

    config_load(&P.cfg);
    dbg("start loop=%d vol=%.2f", P.cfg.loop, P.cfg.volume);
    bottom_show(ROMFS_BOTTOM);
    dbg("bottom done");

    C3D_Init(C3D_DEFAULT_CMDBUF_SIZE);
    C2D_Init(C2D_DEFAULT_MAX_OBJECTS);
    C2D_Prepare();
    dbg("c2d init done");
    C3D_RenderTarget *top = C2D_CreateScreenTarget(GFX_TOP, GFX_LEFT);

    if (!open_media()) {
        consoleInit(GFX_BOTTOM, NULL);
        printf("Cannot open video.mp4\n(Press START to exit)\n");
        while (aptMainLoop()) {
            hidScanInput();
            if (hidKeysDown() & KEY_START)
                break;
            gspWaitForVBlank();
        }
        goto out;
    }

    dbg("opened %dx%d audio=%d rate=%d", P.vctx->width, P.vctx->height, P.actx != NULL, P.arate);
    const int vw = P.vctx->width, vh = P.vctx->height;
    bool have_audio = P.actx && audio_init();
    if (P.actx && !have_audio) {
        // DSP ファームウェア (sdmc:/3ds/dspfirm.cdc) が無い等で音声を使えない場合は、
        // 音声ストリームを捨てて映像だけ再生する (音声パケットで詰まらないようにする)
        avcodec_free_context(&P.actx);
        swr_free(&P.swr);
        P.aidx = -1;
    }

    // Y2R: YUV420 -> RGB565 を線形バッファへ出力し、GX 表示転送でタイル化してテクスチャへ入れる
    // (Y2R の 8x8 ブロック出力を直接テクスチャにする方式は、エミュレータ側で配置が崩れた)
    u16 *lin = linearAlloc((size_t)vw * vh * 2);
    C3D_Tex tex;
    C3D_TexInit(&tex, TEX_W, TEX_H, GPU_RGB565);
    C3D_TexSetFilter(&tex, GPU_LINEAR, GPU_LINEAR);
    memset(tex.data, 0, TEX_W * TEX_H * 2);
    // PICA のテクスチャはメモリ先頭行が v=1.0 側。転送は反転せず、最上行を先頭に置く。
    // (citro2d は top<bottom のサブテクスチャを「90度回転した画像」と解釈するので top>bottom にする)
    Tex3DS_SubTexture sub = {(u16)vw, (u16)vh, 0.0f, 1.0f, (float)vw / TEX_W, 1.0f - (float)vh / TEX_H};
    C2D_Image img = {&tex, &sub};

    y2rInit();
    Y2RU_ConversionParams yp = {0};
    yp.input_format = INPUT_YUV420_INDIV_8;
    yp.output_format = OUTPUT_RGB_16_565;
    yp.rotation = ROTATION_NONE;
    yp.block_alignment = BLOCK_LINE;
    yp.input_line_width = vw;
    yp.input_lines = vh;
    yp.standard_coefficient = COEFFICIENT_ITU_R_BT_601;
    yp.alpha = 0xFF;
    Y2RU_SetConversionParams(&yp);
    Y2RU_SetTransferEndInterrupt(true);
    Handle y2r_done = 0;
    Y2RU_GetTransferEndEvent(&y2r_done);

    LightLock_Init(&P.vlock);

    s32 prio = 0;
    svcGetThreadPriority(&prio, CUR_THREAD_HANDLE);
    bool n3ds = false;
    APT_CheckNew3DS(&n3ds);
    int core = 1;
    if (n3ds)
        core = 2;
    else
        APT_SetAppCpuTimeLimit(80); // 旧3DSはシステムコア(1)を最大80%まで使う
    Thread th = threadCreate(decode_thread, NULL, 256 * 1024, prio - 1, core, false);

    dbg("thread started core=%d", core);
    // 先読み: キューが埋まる (または EOF) まで待ってから音声を開始する
    while (aptMainLoop()) {
        LightLock_Lock(&P.vlock);
        int cnt = P.vq_count;
        LightLock_Unlock(&P.vlock);
        if (cnt >= VQ_SIZE / 2 || P.eof)
            break;
        svcSleepThread(5 * 1000 * 1000);
    }
    if (have_audio)
        ndspChnSetPaused(0, false);
    const u64 t0 = svcGetSystemTick();
    dbg("prebuffer done");

    // 低解像度の動画は GPU で上画面いっぱいに拡大して表示する (アスペクト比は維持)
    float scale = (float)TOP_W / vw;
    if ((float)TOP_H / vh < scale)
        scale = (float)TOP_H / vh;
    const float dw = vw * scale, dh = vh * scale;

    bool first = true;
    while (aptMainLoop()) {
        hidScanInput();
        if (hidKeysDown() & KEY_START)
            break;

        double clock = have_audio ? audio_clock() : (double)(svcGetSystemTick() - t0) / SYSCLOCK_ARM11;

        // clock に追いついた最新フレームを選ぶ (それより古いものは捨てる = フレームスキップ)
        AVFrame *show = NULL;
        LightLock_Lock(&P.vlock);
        while (P.vq_count > 0 && P.vq[P.vq_head].pts <= clock) {
            if (show)
                av_frame_free(&show);
            show = P.vq[P.vq_head].frame;
            P.vq_head = (P.vq_head + 1) % VQ_SIZE;
            P.vq_count--;
        }
        int remain = P.vq_count;
        LightLock_Unlock(&P.vlock);

        static int dbgn;
        if (dbgn < 40 || (dbgn % 60) == 0)
            dbg("t=%.3f show=%d remain=%d st=%d vpush=%d apush=%d", clock, show != NULL, remain, P.dbg_state, P.dbg_vpush, P.dbg_apush);
        dbgn++;
        if (show) {
            Y2RU_SetSendingY(show->data[0], vw * vh, vw, show->linesize[0] - vw);
            Y2RU_SetSendingU(show->data[1], vw * vh / 4, vw / 2, show->linesize[1] - vw / 2);
            Y2RU_SetSendingV(show->data[2], vw * vh / 4, vw / 2, show->linesize[2] - vw / 2);
            Y2RU_SetReceiving(lin, vw * vh * 2, vw * 2, 0);
            GSPGPU_FlushDataCache(show->data[0], show->linesize[0] * vh);
            GSPGPU_FlushDataCache(show->data[1], show->linesize[1] * vh / 2);
            GSPGPU_FlushDataCache(show->data[2], show->linesize[2] * vh / 2);
            Y2RU_StartConversion();
            svcWaitSynchronization(y2r_done, 100 * 1000 * 1000);
            C3D_SyncDisplayTransfer((u32 *)lin, GX_BUFFER_DIM(vw, vh), (u32 *)tex.data,
                                    GX_BUFFER_DIM(TEX_W, TEX_H),
                                    GX_TRANSFER_FLIP_VERT(0) | GX_TRANSFER_OUT_TILED(1) |
                                        GX_TRANSFER_RAW_COPY(0) |
                                        GX_TRANSFER_IN_FORMAT(GX_TRANSFER_FMT_RGB565) |
                                        GX_TRANSFER_OUT_FORMAT(GX_TRANSFER_FMT_RGB565) |
                                        GX_TRANSFER_SCALING(GX_TRANSFER_SCALE_NO));
            av_frame_free(&show);
        } else if (!first) {
            // 新しいフレームがなければ描画も省いて vsync を待つだけ
            if (P.eof && remain == 0 && clock >= P.end_time)
                break;
            gspWaitForVBlank();
            continue;
        }
        first = false;

        C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
        C2D_TargetClear(top, C2D_Color32(0, 0, 0, 255));
        C2D_SceneBegin(top);
        C2D_DrawImageAt(img, (TOP_W - dw) / 2, (TOP_H - dh) / 2, 0.0f, NULL, scale, scale);
        C3D_FrameEnd(0);
    }

    P.quit = true;
    threadJoin(th, U64_MAX);
    threadFree(th);

    if (have_audio) {
        ndspChnReset(0);
        for (int i = 0; i < ABUF_NUM; i++)
            linearFree(P.ab[i].data);
        ndspExit();
    }
    Y2RU_StopConversion();
    y2rExit();
    C3D_TexDelete(&tex);
    linearFree(lin);

out:
    C2D_Fini();
    C3D_Fini();
    romfsExit();
    gfxExit();
    return 0;
}
