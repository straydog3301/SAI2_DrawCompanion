/*
 * sai2mod.c — PaintTool SAI Ver.2 Native Filter Expansion Mod (dwmapi.dll proxy)
 *
 * 將「效果 (Effects)」子選單（「二值化 ...」、「色調分離 ...」）直接注入 SAI2 原生「濾鏡」選單，
 * 並對接 SAI2 內部原生濾鏡引擎 (FilterDescriptor / 16-bit Tile Engine)：
 *   - 100% 原生 SAI2 濾鏡對話框（自動套用 sai2S 深色/自訂主題）
 *   - 16-bit BGRA 磚塊多執行緒畫布即時預覽（支援選取範圍、保護不透明度、圖層資料夾、剪裁遮罩）
 *   - 點擊「確定」直接寫入圖層並建立原生 Undo/Redo 歷史步驟（完整支援 Ctrl+Z / Ctrl+Y）
 *
 * 由 SAI2_DrawCompanion 控制開關與 sai2_filters_mod.ini 設定檔，於下次啟動 SAI2 時生效。
 */

#include <windows.h>
#include <intrin.h>
#include <stdint.h>
#include <string.h>
#include <stddef.h>
#include <stdio.h>
#include <stdarg.h>
#include <wchar.h>

#define MENU_ID_EFFECT_SEP      0x28FFF
#define MENU_ID_EFFECT_SUBMENU  0x29000
#define MENU_ID_BINARIZE        0x29001
#define MENU_ID_POSTERIZE       0x29002
#define MENU_ID_PIXELATE        0x29003
#define MENU_ID_SHARPEN         0x29004

#define STR_BIN_TITLE           0x40001
#define STR_BIN_LBL             0x40002
#define STR_BIN_SLIDER          0x40003
#define STR_BIN_CHK             0x40004
#define STR_POS_TITLE           0x40005
#define STR_POS_LBL             0x40006
#define STR_POS_SLIDER          0x40007
#define STR_PIX_TITLE           0x40008
#define STR_PIX_LBL             0x40009
#define STR_PIX_SLIDER          0x4000A
#define STR_SHP_TITLE           0x4000B
#define STR_SHP_LBL             0x4000C
#define STR_SHP_SLIDER          0x4000D

typedef struct {
    const wchar_t *key;
    const wchar_t *text;
    const wchar_t *sub;
    uint64_t       pad1;
    uint64_t       pad2;
    uint64_t       flags;
} Sai2StrEntry; // 48 bytes (0x30)

static Sai2StrEntry g_mod_strings[16] = {
    { NULL, (const wchar_t *)16, NULL, 0, 0, 0 },
    { L"Mod_Binarize_Title",    L"二值化",                     NULL, 0, 0, 0 },
    { L"Mod_Binarize_ThresLbl", L"閾值 :",                     NULL, 0, 0, 0 },
    { L"Mod_Binarize_ThresCtl", L"",                           NULL, 0, 0, 0 },
    { L"Mod_Binarize_TransChk", L"將白色轉為透明（提取線稿）", NULL, 0, 0, 0 },
    { L"Mod_Posterize_Title",   L"色調分離",                   NULL, 0, 0, 0 },
    { L"Mod_Posterize_LvLbl",   L"色階數 :",                   NULL, 0, 0, 0 },
    { L"Mod_Posterize_LvCtl",   L"",                           NULL, 0, 0, 0 },
    { L"Mod_Pixelate_Title",    L"像素化",                     NULL, 0, 0, 0 },
    { L"Mod_Pixelate_SzLbl",    L"強度 :",                     NULL, 0, 0, 0 },
    { L"Mod_Pixelate_SzCtl",    L"",                           NULL, 0, 0, 0 },
    { L"Mod_Sharpen_Title",     L"銳化",                       NULL, 0, 0, 0 },
    { L"Mod_Sharpen_AmtLbl",    L"強度 :",                     NULL, 0, 0, 0 },
    { L"Mod_Sharpen_AmtCtl",    L"",                           NULL, 0, 0, 0 },
};

typedef struct {
    uint32_t timestamp;
    int      ver_type;          // 2023 (0x64ace695) or 2026 (0x6ad549f7)
    uint32_t menu_id_filter;    // 0x20077 (2023) or 0x2008b (2026)
    uint32_t menu_id_flt_color; // 0x20100 (2023) or 0x20168 (2026)
    uint32_t cmd_id_lumcon;     // 0x20109 (2023) or 0x20172 (2026)

    uintptr_t rva_active_doc;
    uintptr_t rva_glob_str_tbl;
    uintptr_t rva_alloc;
    uintptr_t rva_free;
    uintptr_t rva_strcpy;
    uintptr_t rva_reg_filter;
    uintptr_t rva_run_filter;
    uintptr_t rva_ret1;
    uintptr_t rva_ret0;

    uintptr_t rva_create_vbox;
    uintptr_t rva_create_grid;
    uintptr_t rva_set_col_w;
    uintptr_t rva_add_row;
    uintptr_t rva_add_label;
    uintptr_t rva_add_slider;
    uintptr_t rva_add_checkbox;
    uintptr_t rva_add_spacer;
    uintptr_t rva_find_ctrl;
    uintptr_t rva_set_slider;
    uintptr_t rva_set_checkbox;
    uintptr_t rva_get_userdata;

    uintptr_t rva_prev_drag_begin;
    uintptr_t rva_prev_drag_move;
    uintptr_t rva_prev_drag_end;
    uintptr_t rva_prev_imm;

    uint32_t  ev_slider_begin;
    uint32_t  ev_checkbox_click;
    uint32_t  slider_val_off;

    // 介面字串查找：SAI2 依 (id >> 16) & 3 選字串表，表從「UI context + 0x90」讀，
    // 只有拿不到 context 時才用全域表 rva_glob_str_tbl。context 在 SAI2 啟動時就複製好全域表，
    // 所以只改全域表不夠，還要把 slot 0 寫進每個 context（見 ensure_string_table_installed）
    uintptr_t rva_default_ctx;  // 沒有視窗資訊時用的預設 context 指標（0 = 未知）
} Sai2Offsets;

static const Sai2Offsets k_profiles[] = {
    // SAI2 Ver.2 Preview.2023.07.11 (64-bit) — TimeDateStamp 0x64ace695
    {
        .timestamp          = 0x64ace695,
        .ver_type           = 2023,
        .menu_id_filter     = 0x20077,
        .menu_id_flt_color  = 0x20100,
        .cmd_id_lumcon      = 0x20109,
        .rva_active_doc     = 0x31bc18,
        .rva_glob_str_tbl   = 0x3412c0,
        .rva_alloc          = 0x1a1a30,
        .rva_free           = 0x0c9ad0,
        .rva_strcpy         = 0x1bea30,
        .rva_reg_filter     = 0x06af80,
        .rva_run_filter     = 0x06acf0,
        .rva_ret1           = 0x074060,
        .rva_ret0           = 0x00dc10,
        .rva_create_vbox    = 0x1cec70,
        .rva_create_grid    = 0x1ca990,
        .rva_set_col_w      = 0x1caa90,
        .rva_add_row        = 0x1cecb0,
        .rva_add_label      = 0x1cf210,
        .rva_add_slider     = 0x1d0100,
        .rva_add_checkbox   = 0x1cf890,
        .rva_add_spacer     = 0x1ce460,
        .rva_find_ctrl      = 0x1bcdd0,
        .rva_set_slider     = 0x1ef460,
        .rva_set_checkbox   = 0x1c4b70,
        .rva_get_userdata   = 0x1cd560,
        .rva_prev_drag_begin= 0x06a7f0,
        .rva_prev_drag_move = 0x06a870,
        .rva_prev_drag_end  = 0x06a8b0,
        .rva_prev_imm       = 0x06a790,
        .ev_slider_begin    = 0x53e,
        .ev_checkbox_click  = 0x522,
        .slider_val_off     = 0x20,
    },
    // SAI2 Ver.2 Alpha 2026.10.19 (64-bit) — TimeDateStamp 0x6ad549f7
    {
        .timestamp          = 0x6ad549f7,
        .ver_type           = 2026,
        .menu_id_filter     = 0x200a2,
        .menu_id_flt_color  = 0x20168,
        .cmd_id_lumcon      = 0x20171,
        .rva_active_doc     = 0x47a1d8,
        .rva_glob_str_tbl   = 0x4a2340,
        .rva_alloc          = 0x25ccc0,
        .rva_free           = 0x23a400,
        .rva_strcpy         = 0x2522d0,
        .rva_reg_filter     = 0x096740,
        .rva_run_filter     = 0x098490,
        .rva_ret1           = 0x0d0950,
        .rva_ret0           = 0x2bd7b0,
        .rva_create_vbox    = 0x287550,
        .rva_create_grid    = 0x2848e0,
        .rva_set_col_w      = 0x2849f0,
        .rva_add_row        = 0x287590,
        .rva_add_label      = 0x287b40,
        .rva_add_slider     = 0x2890b0,
        .rva_add_checkbox   = 0x2886e0,
        .rva_add_spacer     = 0x286e90,
        .rva_find_ctrl      = 0x256140,
        .rva_set_slider     = 0x2ad620,
        .rva_set_checkbox   = 0x2c6040,
        .rva_get_userdata   = 0x2866a0,
        .rva_prev_drag_begin= 0x097c60,
        .rva_prev_drag_move = 0x097c70,
        .rva_prev_drag_end  = 0x097c80,
        .rva_prev_imm       = 0x097c90,
        .ev_slider_begin    = 0x544,
        .ev_checkbox_click  = 0x523,
        .slider_val_off     = 0xc8,
        .rva_default_ctx    = 0x483d58,
    },
};

static uintptr_t g_base = 0;
static const Sai2Offsets *g_off = NULL;
static HWND g_main_hwnd = NULL;
static WNDPROC g_orig_wndproc = NULL;

static int g_cfg_enabled   = 1;
static int g_cfg_binarize  = 1;
static int g_cfg_posterize = 1;
static int g_cfg_pixelate  = 1;
static int g_cfg_sharpen   = 1;
static int g_cfg_debug     = 0;    // [FiltersMod] debug=1 才寫 sai2mod.log（預設關閉）

// Function pointer types
typedef void *(*fn_alloc_t)(size_t sz);
typedef void (*fn_free_t)(void *p);
typedef void (*fn_strcpy_t)(char *dst, size_t cap, const char *src);
typedef void *(*fn_reg_filter_t)(void *desc, void *user_data);
typedef int (*fn_run_filter_2023_t)(void *filter_obj, void *doc);
typedef int (*fn_run_filter_2026_t)(void *filter_obj);

typedef void *(*fn_create_vbox_t)(void *parent, int a2, int a3, int a4);
typedef void *(*fn_create_grid_t)(void *vbox, int cols, int a3);
typedef void (*fn_set_col_w_t)(void *grid, int col, int w);
typedef void *(*fn_add_row_t)(void *vbox, void *grid, int a3, int a4);
typedef void *(*fn_add_label_t)(void *row, int col, int flags, uint32_t str_id);
typedef void *(*fn_add_slider_t)(void *row, int col, int flags, uint32_t ctrl_id,
                                 void *cb, int a6, int a7, int width, int height,
                                 void *unit, int min_v, int dec, int max_v);
typedef void *(*fn_add_checkbox_t)(void *row, int col, int flags, uint32_t ctrl_id,
                                   void *cb, int a6, int a7);
typedef void (*fn_add_spacer_t)(void *vbox, int a2, int height);
typedef void *(*fn_find_ctrl_t)(void *dlg, uint32_t ctrl_id);
typedef void (*fn_set_slider_t)(void *ctrl, int val, int notify);
typedef void (*fn_set_checkbox_t)(void *ctrl, int val, int notify);
typedef void *(*fn_get_userdata_t)(void *ctx);
typedef void (*fn_preview_act_t)(void);

// 前向宣告（定義在後面的「字串表」與「濾鏡執行」段落）
static void log_pixel_call(const char *name, int count, const void *dst, const void *src, void *ret);
static void install_for_dialog(void *dlg, const char *who);
static void log_prep(const char *name, const char *phase, void *rect);

// ─────────────────────────────────────────────────────────────────────────
// Filter 1: 二值化 (Binarize / Threshold)
// ─────────────────────────────────────────────────────────────────────────

typedef struct {
    int32_t  r_threshold;
    int32_t  r_trans_white;
    uint8_t  pad0[0x40 - 8];
    void    *ctrl_slider;
    void    *ctrl_check;
    void    *ctrl_unused;
    int32_t  ui_threshold;
    int32_t  ui_trans_white;
    uint8_t  pad1[0x80 - 0x60];
} BinarizeState;

typedef struct {
    int32_t threshold;
    int32_t trans_white;
    int64_t pad;
} BinarizeParams;

static BinarizeState *g_cur_bin_state = NULL;

static void *bin_slider_cb(void *ctrl, uint32_t ctrl_id, uint32_t ev, void *a4, void *a5, void *a6, void *a7) {
    BinarizeState *st = (BinarizeState *)((fn_get_userdata_t)(g_base + g_off->rva_get_userdata))(a7);
    if (!st) st = g_cur_bin_state;
    uint32_t ev0 = g_off->ev_slider_begin;
    if (st && ev >= ev0 && ev <= ev0 + 2 && ctrl_id == STR_BIN_SLIDER) {
        st->ui_threshold = *(int32_t *)((char *)a5 + g_off->slider_val_off);
        if (ev == ev0)          ((fn_preview_act_t)(g_base + g_off->rva_prev_drag_begin))();
        else if (ev == ev0 + 1) ((fn_preview_act_t)(g_base + g_off->rva_prev_drag_move))();
        else                    ((fn_preview_act_t)(g_base + g_off->rva_prev_drag_end))();
    }
    return 0;
}

static void *bin_check_cb(void *ctrl, uint32_t ctrl_id, uint32_t ev, void *a4, void *a5, void *a6, void *a7) {
    BinarizeState *st = (BinarizeState *)((fn_get_userdata_t)(g_base + g_off->rva_get_userdata))(a7);
    if (!st) st = g_cur_bin_state;
    if (st && ev == g_off->ev_checkbox_click && ctrl_id == STR_BIN_CHK) {
        st->ui_trans_white = !st->ui_trans_white;
        ((fn_set_checkbox_t)(g_base + g_off->rva_set_checkbox))(ctrl, st->ui_trans_white, 0);
        ((fn_preview_act_t)(g_base + g_off->rva_prev_imm))();
    }
    return 0;
}

static void bin_build_ui(BinarizeState *st, void *dlg, void *parent_box, void *a4) {
    install_for_dialog(dlg, "binarize");
    void *vbox = ((fn_create_vbox_t)(g_base + g_off->rva_create_vbox))(parent_box, 0, 0, 0);
    void *grid = ((fn_create_grid_t)(g_base + g_off->rva_create_grid))(vbox, 2, 3);
    ((fn_set_col_w_t)(g_base + g_off->rva_set_col_w))(grid, 1, 0x200);
    ((fn_set_col_w_t)(g_base + g_off->rva_set_col_w))(grid, 2, 0);

    void *row1 = ((fn_add_row_t)(g_base + g_off->rva_add_row))(vbox, grid, 0, 0);
    ((fn_add_label_t)(g_base + g_off->rva_add_label))(row1, 1, 0, STR_BIN_LBL);
    ((fn_add_slider_t)(g_base + g_off->rva_add_slider))(
        row1, 2, 0, STR_BIN_SLIDER, (void *)bin_slider_cb, 0, 0, 0x169, 0, NULL, 1, 0, 255);

    ((fn_add_spacer_t)(g_base + g_off->rva_add_spacer))(vbox, 0, 2);
    void *row2 = ((fn_add_row_t)(g_base + g_off->rva_add_row))(vbox, grid, 0, 0);
    ((fn_add_checkbox_t)(g_base + g_off->rva_add_checkbox))(
        row2, 2, 0, STR_BIN_CHK, (void *)bin_check_cb, 0, 0);

    st->ctrl_slider = ((fn_find_ctrl_t)(g_base + g_off->rva_find_ctrl))(dlg, STR_BIN_SLIDER);
    st->ctrl_check  = ((fn_find_ctrl_t)(g_base + g_off->rva_find_ctrl))(dlg, STR_BIN_CHK);
    if (st->ui_threshold < 1 || st->ui_threshold > 255) st->ui_threshold = 128;
    ((fn_set_slider_t)(g_base + g_off->rva_set_slider))(st->ctrl_slider, st->ui_threshold, 0);
    ((fn_set_checkbox_t)(g_base + g_off->rva_set_checkbox))(st->ctrl_check, st->ui_trans_white, 0);
}

static void *bin_create_params_2023(BinarizeState *st) {
    BinarizeParams *p = (BinarizeParams *)((fn_alloc_t)(g_base + g_off->rva_alloc))(sizeof(BinarizeParams));
    if (p) {
        p->threshold   = (st->ui_threshold >= 1 && st->ui_threshold <= 255) ? st->ui_threshold : 128;
        p->trans_white = st->ui_trans_white;
        p->pad         = 0;
    }
    return p;
}

static void bin_copy_params_2026(BinarizeState *st, BinarizeParams *p) {
    if (p) {
        p->threshold   = (st->ui_threshold >= 1 && st->ui_threshold <= 255) ? st->ui_threshold : 128;
        p->trans_white = st->ui_trans_white;
        p->pad         = 0;
    }
}

static uint8_t bin_prep_preview(BinarizeState *st, uint8_t flag, BinarizeParams *p, void *rect) {
    st->r_threshold   = p->threshold;
    st->r_trans_white = p->trans_white;
    return 1;
}

static uint8_t bin_prep_commit(BinarizeState *st, BinarizeParams *p, void *rect) {
    st->r_threshold   = p->threshold;
    st->r_trans_white = p->trans_white;
    return 1;
}

static void bin_process_pixels(BinarizeState *st, int count, uint16_t *dst, const uint16_t *src) {
    log_pixel_call("binarize", count, dst, src, _ReturnAddress());
    int32_t th = st->r_threshold;
    int32_t tw = st->r_trans_white;
    if (th < 1) th = 1;
    if (th > 255) th = 255;

    for (int i = 0; i < count; i++) {
        uint32_t b = src[i * 4 + 0];
        uint32_t g = src[i * 4 + 1];
        uint32_t r = src[i * 4 + 2];
        uint32_t a = src[i * 4 + 3];
        if (a == 0) {
            *(uint64_t *)(&dst[i * 4]) = 0;
            continue;
        }
        uint64_t lum = (299ULL * r + 587ULL * g + 114ULL * b) / 1000ULL;
        int is_white = (lum * 255ULL >= (uint64_t)th * (uint64_t)a);
        if (is_white) {
            if (tw) {
                *(uint64_t *)(&dst[i * 4]) = 0;
            } else {
                dst[i * 4 + 0] = (uint16_t)a;
                dst[i * 4 + 1] = (uint16_t)a;
                dst[i * 4 + 2] = (uint16_t)a;
                dst[i * 4 + 3] = (uint16_t)a;
            }
        } else {
            dst[i * 4 + 0] = 0;
            dst[i * 4 + 1] = 0;
            dst[i * 4 + 2] = 0;
            dst[i * 4 + 3] = (uint16_t)a;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Filter 2: 色調分離 (Posterize)
// ─────────────────────────────────────────────────────────────────────────

typedef struct {
    int32_t  r_levels;
    uint8_t  pad0[0x40 - 4];
    void    *ctrl_slider;
    void    *ctrl_unused1;
    void    *ctrl_unused2;
    int32_t  ui_levels;
    uint8_t  pad1[0x80 - 0x5c];
} PosterizeState;

typedef struct {
    int32_t levels;
    int32_t pad0;
    int64_t pad1;
} PosterizeParams;

static PosterizeState *g_cur_pos_state = NULL;

static void *pos_slider_cb(void *ctrl, uint32_t ctrl_id, uint32_t ev, void *a4, void *a5, void *a6, void *a7) {
    PosterizeState *st = (PosterizeState *)((fn_get_userdata_t)(g_base + g_off->rva_get_userdata))(a7);
    if (!st) st = g_cur_pos_state;
    uint32_t ev0 = g_off->ev_slider_begin;
    if (st && ev >= ev0 && ev <= ev0 + 2 && ctrl_id == STR_POS_SLIDER) {
        st->ui_levels = *(int32_t *)((char *)a5 + g_off->slider_val_off);
        if (ev == ev0)          ((fn_preview_act_t)(g_base + g_off->rva_prev_drag_begin))();
        else if (ev == ev0 + 1) ((fn_preview_act_t)(g_base + g_off->rva_prev_drag_move))();
        else                    ((fn_preview_act_t)(g_base + g_off->rva_prev_drag_end))();
    }
    return 0;
}

static void pos_build_ui(PosterizeState *st, void *dlg, void *parent_box, void *a4) {
    install_for_dialog(dlg, "posterize");
    void *vbox = ((fn_create_vbox_t)(g_base + g_off->rva_create_vbox))(parent_box, 0, 0, 0);
    void *grid = ((fn_create_grid_t)(g_base + g_off->rva_create_grid))(vbox, 2, 3);
    ((fn_set_col_w_t)(g_base + g_off->rva_set_col_w))(grid, 1, 0x200);
    ((fn_set_col_w_t)(g_base + g_off->rva_set_col_w))(grid, 2, 0);

    void *row1 = ((fn_add_row_t)(g_base + g_off->rva_add_row))(vbox, grid, 0, 0);
    ((fn_add_label_t)(g_base + g_off->rva_add_label))(row1, 1, 0, STR_POS_LBL);
    ((fn_add_slider_t)(g_base + g_off->rva_add_slider))(
        row1, 2, 0, STR_POS_SLIDER, (void *)pos_slider_cb, 0, 0, 0x169, 0, NULL, 2, 0, 64);

    st->ctrl_slider = ((fn_find_ctrl_t)(g_base + g_off->rva_find_ctrl))(dlg, STR_POS_SLIDER);
    if (st->ui_levels < 2 || st->ui_levels > 64) st->ui_levels = 4;
    ((fn_set_slider_t)(g_base + g_off->rva_set_slider))(st->ctrl_slider, st->ui_levels, 0);
}

static void *pos_create_params_2023(PosterizeState *st) {
    PosterizeParams *p = (PosterizeParams *)((fn_alloc_t)(g_base + g_off->rva_alloc))(sizeof(PosterizeParams));
    if (p) {
        p->levels = (st->ui_levels >= 2 && st->ui_levels <= 64) ? st->ui_levels : 4;
        p->pad0   = 0;
        p->pad1   = 0;
    }
    return p;
}

static void pos_copy_params_2026(PosterizeState *st, PosterizeParams *p) {
    if (p) {
        p->levels = (st->ui_levels >= 2 && st->ui_levels <= 64) ? st->ui_levels : 4;
        p->pad0   = 0;
        p->pad1   = 0;
    }
}

static uint8_t pos_prep_preview(PosterizeState *st, uint8_t flag, PosterizeParams *p, void *rect) {
    log_prep("posterize", "preview", rect);
    st->r_levels = p->levels;
    return 1;
}

static uint8_t pos_prep_commit(PosterizeState *st, PosterizeParams *p, void *rect) {
    log_prep("posterize", "commit", rect);
    st->r_levels = p->levels;
    return 1;
}

static inline uint16_t posterize_chan(uint32_t c, uint32_t a, uint32_t lv) {
    if (c >= a) return (uint16_t)a;
    // Quantize c/a into lv levels [0 .. lv-1]:
    // idx = floor((c * (lv - 1)) / a + 0.5) = (2 * c * (lv - 1) + a) / (2 * a)
    uint64_t lvm1 = (uint64_t)(lv - 1);
    uint64_t idx  = (2ULL * (uint64_t)c * lvm1 + (uint64_t)a) / (2ULL * (uint64_t)a);
    if (idx > lvm1) idx = lvm1;
    // Map back to premultiplied [0 .. a]:
    uint64_t out = (2ULL * idx * (uint64_t)a + lvm1) / (2ULL * lvm1);
    return (uint16_t)(out > a ? a : out);
}

static void pos_process_pixels(PosterizeState *st, int count, uint16_t *dst, const uint16_t *src) {
    log_pixel_call("posterize", count, dst, src, _ReturnAddress());
    int32_t lv = st->r_levels;
    if (lv < 2) lv = 2;
    if (lv > 64) lv = 64;
    uint32_t ulv = (uint32_t)lv;

    for (int i = 0; i < count; i++) {
        uint32_t b = src[i * 4 + 0];
        uint32_t g = src[i * 4 + 1];
        uint32_t r = src[i * 4 + 2];
        uint32_t a = src[i * 4 + 3];
        if (a == 0) {
            *(uint64_t *)(&dst[i * 4]) = 0;
            continue;
        }
        dst[i * 4 + 0] = posterize_chan(b, a, ulv);
        dst[i * 4 + 1] = posterize_chan(g, a, ulv);
        dst[i * 4 + 2] = posterize_chan(r, a, ulv);
        dst[i * 4 + 3] = (uint16_t)a;
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Filter 3: 像素化 (Pixelate / Mosaic)
//
// 逐點濾鏡引擎一次給一塊 32x32、對齊 32 像素邊界的磚塊（count=1024）。只要區塊大小取
// 32 的因數（2/4/8/16/32），每個區塊就完整落在單一磚塊內、且邊界對齊，不會有接縫。
// ─────────────────────────────────────────────────────────────────────────

#define PIX_TILE_W 32

typedef struct {
    int32_t  r_block;
    uint8_t  pad0[0x40 - 4];
    void    *ctrl_slider;
    void    *ctrl_unused1;
    void    *ctrl_unused2;
    int32_t  ui_block;
    uint8_t  pad1[0x80 - 0x5c];
} PixelateState;

typedef struct {
    int32_t block;
    int32_t pad0;
    int64_t pad1;
} PixelateParams;

static PixelateState *g_cur_pix_state = NULL;

// 滑桿是 1~5 的強度等級，對應 5 種無接縫的區塊大小（都是 32 的因數）
static int pix_level_to_block(int level) {
    static const int blocks[] = {2, 4, 8, 16, 32};
    if (level < 1) level = 1;
    if (level > 5) level = 5;
    return blocks[level - 1];
}

static void *pix_slider_cb(void *ctrl, uint32_t ctrl_id, uint32_t ev, void *a4, void *a5, void *a6, void *a7) {
    PixelateState *st = (PixelateState *)((fn_get_userdata_t)(g_base + g_off->rva_get_userdata))(a7);
    if (!st) st = g_cur_pix_state;
    uint32_t ev0 = g_off->ev_slider_begin;
    if (st && ev >= ev0 && ev <= ev0 + 2 && ctrl_id == STR_PIX_SLIDER) {
        st->ui_block = *(int32_t *)((char *)a5 + g_off->slider_val_off);
        if (ev == ev0)          ((fn_preview_act_t)(g_base + g_off->rva_prev_drag_begin))();
        else if (ev == ev0 + 1) ((fn_preview_act_t)(g_base + g_off->rva_prev_drag_move))();
        else                    ((fn_preview_act_t)(g_base + g_off->rva_prev_drag_end))();
    }
    return 0;
}

static void pix_build_ui(PixelateState *st, void *dlg, void *parent_box, void *a4) {
    install_for_dialog(dlg, "pixelate");
    void *vbox = ((fn_create_vbox_t)(g_base + g_off->rva_create_vbox))(parent_box, 0, 0, 0);
    void *grid = ((fn_create_grid_t)(g_base + g_off->rva_create_grid))(vbox, 2, 3);
    ((fn_set_col_w_t)(g_base + g_off->rva_set_col_w))(grid, 1, 0x200);
    ((fn_set_col_w_t)(g_base + g_off->rva_set_col_w))(grid, 2, 0);

    void *row1 = ((fn_add_row_t)(g_base + g_off->rva_add_row))(vbox, grid, 0, 0);
    ((fn_add_label_t)(g_base + g_off->rva_add_label))(row1, 1, 0, STR_PIX_LBL);
    ((fn_add_slider_t)(g_base + g_off->rva_add_slider))(
        row1, 2, 0, STR_PIX_SLIDER, (void *)pix_slider_cb, 0, 0, 0x169, 0, NULL, 1, 0, 5);

    st->ctrl_slider = ((fn_find_ctrl_t)(g_base + g_off->rva_find_ctrl))(dlg, STR_PIX_SLIDER);
    if (st->ui_block < 1 || st->ui_block > 5) st->ui_block = 3;
    ((fn_set_slider_t)(g_base + g_off->rva_set_slider))(st->ctrl_slider, st->ui_block, 0);
}

static void *pix_create_params_2023(PixelateState *st) {
    PixelateParams *p = (PixelateParams *)((fn_alloc_t)(g_base + g_off->rva_alloc))(sizeof(PixelateParams));
    if (p) {
        p->block = (st->ui_block >= 1 && st->ui_block <= 5) ? st->ui_block : 3;  // 強度等級 1~5
        p->pad0  = 0;
        p->pad1  = 0;
    }
    return p;
}

static void pix_copy_params_2026(PixelateState *st, PixelateParams *p) {
    if (p) {
        p->block = (st->ui_block >= 1 && st->ui_block <= 5) ? st->ui_block : 3;  // 強度等級 1~5
        p->pad0  = 0;
        p->pad1  = 0;
    }
}

static uint8_t pix_prep_preview(PixelateState *st, uint8_t flag, PixelateParams *p, void *rect) {
    log_prep("pixelate", "preview", rect);
    st->r_block = p->block;
    return 1;
}

static uint8_t pix_prep_commit(PixelateState *st, PixelateParams *p, void *rect) {
    log_prep("pixelate", "commit", rect);
    st->r_block = p->block;
    return 1;
}

static void pix_process_pixels(PixelateState *st, int count, uint16_t *dst, const uint16_t *src) {
    log_pixel_call("pixelate", count, dst, src, _ReturnAddress());
    int b = pix_level_to_block(st->r_block);
    const int W = PIX_TILE_W;
    if (count != W * W) {
        // 不是預期的 32x32 磚塊（例如邊緣磚塊）：原樣複製，寧可不處理也不要破圖
        memcpy(dst, src, (size_t)count * 4 * sizeof(uint16_t));
        return;
    }
    for (int by = 0; by < W; by += b) {
        for (int bx = 0; bx < W; bx += b) {
            uint64_t sb = 0, sg = 0, sr = 0, sa = 0;
            for (int y = 0; y < b; y++) {
                const uint16_t *row = src + ((by + y) * W + bx) * 4;
                for (int x = 0; x < b; x++) {
                    sb += row[x * 4 + 0];
                    sg += row[x * 4 + 1];
                    sr += row[x * 4 + 2];
                    sa += row[x * 4 + 3];
                }
            }
            uint32_t n = (uint32_t)(b * b);
            uint16_t ab = (uint16_t)(sb / n), ag = (uint16_t)(sg / n),
                     ar = (uint16_t)(sr / n), aa = (uint16_t)(sa / n);
            for (int y = 0; y < b; y++) {
                uint16_t *row = dst + ((by + y) * W + bx) * 4;
                for (int x = 0; x < b; x++) {
                    row[x * 4 + 0] = ab;
                    row[x * 4 + 1] = ag;
                    row[x * 4 + 2] = ar;
                    row[x * 4 + 3] = aa;
                }
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Filter 4: 銳化 (Sharpen / Unsharp Mask)
//
// 鄰域濾鏡在逐點引擎上做不到無接縫（磚塊固定 32x32、無鄰居、無餘裕），這裡用「磚塊內
// 3x3 遮罩」近似：把每個 32x32 磚塊當成獨立小圖，邊緣以夾邊取樣。輕度通常看不出來，
// 強度高時磚塊邊界（每 32 像素）可能出現淡淡接縫。
// ─────────────────────────────────────────────────────────────────────────

#define SHP_W 32

typedef struct {
    int32_t  r_amount;
    uint8_t  pad0[0x40 - 4];
    void    *ctrl_slider;
    void    *ctrl_unused1;
    void    *ctrl_unused2;
    int32_t  ui_amount;
    uint8_t  pad1[0x80 - 0x5c];
} SharpenState;

typedef struct {
    int32_t amount;
    int32_t pad0;
    int64_t pad1;
} SharpenParams;

static SharpenState *g_cur_shp_state = NULL;

static void *shp_slider_cb(void *ctrl, uint32_t ctrl_id, uint32_t ev, void *a4, void *a5, void *a6, void *a7) {
    SharpenState *st = (SharpenState *)((fn_get_userdata_t)(g_base + g_off->rva_get_userdata))(a7);
    if (!st) st = g_cur_shp_state;
    uint32_t ev0 = g_off->ev_slider_begin;
    if (st && ev >= ev0 && ev <= ev0 + 2 && ctrl_id == STR_SHP_SLIDER) {
        st->ui_amount = *(int32_t *)((char *)a5 + g_off->slider_val_off);
        if (ev == ev0)          ((fn_preview_act_t)(g_base + g_off->rva_prev_drag_begin))();
        else if (ev == ev0 + 1) ((fn_preview_act_t)(g_base + g_off->rva_prev_drag_move))();
        else                    ((fn_preview_act_t)(g_base + g_off->rva_prev_drag_end))();
    }
    return 0;
}

static void shp_build_ui(SharpenState *st, void *dlg, void *parent_box, void *a4) {
    install_for_dialog(dlg, "sharpen");
    void *vbox = ((fn_create_vbox_t)(g_base + g_off->rva_create_vbox))(parent_box, 0, 0, 0);
    void *grid = ((fn_create_grid_t)(g_base + g_off->rva_create_grid))(vbox, 2, 3);
    ((fn_set_col_w_t)(g_base + g_off->rva_set_col_w))(grid, 1, 0x200);
    ((fn_set_col_w_t)(g_base + g_off->rva_set_col_w))(grid, 2, 0);

    void *row1 = ((fn_add_row_t)(g_base + g_off->rva_add_row))(vbox, grid, 0, 0);
    ((fn_add_label_t)(g_base + g_off->rva_add_label))(row1, 1, 0, STR_SHP_LBL);
    ((fn_add_slider_t)(g_base + g_off->rva_add_slider))(
        row1, 2, 0, STR_SHP_SLIDER, (void *)shp_slider_cb, 0, 0, 0x169, 0, NULL, 1, 0, 10);

    st->ctrl_slider = ((fn_find_ctrl_t)(g_base + g_off->rva_find_ctrl))(dlg, STR_SHP_SLIDER);
    if (st->ui_amount < 1 || st->ui_amount > 10) st->ui_amount = 3;
    ((fn_set_slider_t)(g_base + g_off->rva_set_slider))(st->ctrl_slider, st->ui_amount, 0);
}

static void *shp_create_params_2023(SharpenState *st) {
    SharpenParams *p = (SharpenParams *)((fn_alloc_t)(g_base + g_off->rva_alloc))(sizeof(SharpenParams));
    if (p) {
        p->amount = (st->ui_amount >= 1 && st->ui_amount <= 10) ? st->ui_amount : 3;
        p->pad0   = 0;
        p->pad1   = 0;
    }
    return p;
}

static void shp_copy_params_2026(SharpenState *st, SharpenParams *p) {
    if (p) {
        p->amount = (st->ui_amount >= 1 && st->ui_amount <= 10) ? st->ui_amount : 3;
        p->pad0   = 0;
        p->pad1   = 0;
    }
}

static uint8_t shp_prep_preview(SharpenState *st, uint8_t flag, SharpenParams *p, void *rect) {
    st->r_amount = p->amount;
    return 1;
}

static uint8_t shp_prep_commit(SharpenState *st, SharpenParams *p, void *rect) {
    st->r_amount = p->amount;
    return 1;
}

static void shp_process_pixels(SharpenState *st, int count, uint16_t *dst, const uint16_t *src) {
    log_pixel_call("sharpen", count, dst, src, _ReturnAddress());
    int amt = st->r_amount;
    if (amt < 1) amt = 1;
    if (amt > 10) amt = 10;
    const int W = SHP_W;
    if (count != W * W) {
        memcpy(dst, src, (size_t)count * 4 * sizeof(uint16_t));
        return;
    }
    static const int wgt[3] = {1, 2, 1};   // 3x3 高斯權重 [1 2 1]⊗[1 2 1] / 16
    for (int y = 0; y < W; y++) {
        for (int x = 0; x < W; x++) {
            const uint16_t *c = src + (y * W + x) * 4;
            uint16_t *o = dst + (y * W + x) * 4;
            int32_t a = c[3];
            if (a == 0) {
                *(uint64_t *)o = 0;
                continue;
            }
            for (int ch = 0; ch < 3; ch++) {
                int32_t acc = 0;
                for (int dy = -1; dy <= 1; dy++) {
                    int yy = y + dy;
                    if (yy < 0) yy = 0; else if (yy >= W) yy = W - 1;
                    for (int dx = -1; dx <= 1; dx++) {
                        int xx = x + dx;
                        if (xx < 0) xx = 0; else if (xx >= W) xx = W - 1;
                        acc += wgt[dy + 1] * wgt[dx + 1] * src[(yy * W + xx) * 4 + ch];
                    }
                }
                int32_t blur = acc >> 4;                 // ÷16
                int32_t center = c[ch];
                int32_t out = center + (amt * (center - blur)) / 4;  // amt=4 → 1.0×；可達 2.5×
                if (out < 0) out = 0;
                if (out > a) out = a;                    // 預乘：色版不得超過 alpha
                o[ch] = (uint16_t)out;
            }
            o[3] = (uint16_t)a;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Filter Registration & Execution
// ─────────────────────────────────────────────────────────────────────────

static void *g_bin_filter_obj = NULL;
static void *g_pos_filter_obj = NULL;
static void *g_pix_filter_obj = NULL;
static void *g_shp_filter_obj = NULL;

// ── 記錄檔：SAI2 資料夾的 sai2mod.log（只記少量診斷，方便回報問題）──
static void mod_log(const char *fmt, ...) {
    if (!g_cfg_debug) return;
    WCHAR path[MAX_PATH];
    GetModuleFileNameW(NULL, path, MAX_PATH);
    WCHAR *slash = path + lstrlenW(path);
    while (slash > path && slash[-1] != L'\\' && slash[-1] != L'/') slash--;
    lstrcpyW(slash, L"sai2mod.log");
    HANDLE h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                           OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return;
    char buf[512];
    SYSTEMTIME t;
    GetLocalTime(&t);
    int n = snprintf(buf, sizeof(buf), "%02d:%02d:%02d ", t.wHour, t.wMinute, t.wSecond);
    va_list ap;
    va_start(ap, fmt);
    n += vsnprintf(buf + n, sizeof(buf) - n - 2, fmt, ap);
    va_end(ap);
    if (n > (int)sizeof(buf) - 2) n = (int)sizeof(buf) - 2;
    buf[n++] = '\r';
    buf[n++] = '\n';
    DWORD w;
    WriteFile(h, buf, (DWORD)n, &w, NULL);
    CloseHandle(h);
}

// 指標指向的記憶體是否已配置且可讀寫（避免把字串表寫進不是 context 的地方）
static int mem_rw(const void *p, size_t len) {
    MEMORY_BASIC_INFORMATION mbi;
    if (!p || !VirtualQuery(p, &mbi, sizeof(mbi))) return 0;
    if (mbi.State != MEM_COMMIT) return 0;
    if (!(mbi.Protect & (PAGE_READWRITE | PAGE_EXECUTE_READWRITE | PAGE_WRITECOPY))) return 0;
    return (const uint8_t *)p + len <= (const uint8_t *)mbi.BaseAddress + mbi.RegionSize;
}

static int mem_readable(const void *p, size_t len) {
    MEMORY_BASIC_INFORMATION mbi;
    if (!p || !VirtualQuery(p, &mbi, sizeof(mbi))) return 0;
    if (mbi.State != MEM_COMMIT) return 0;
    if (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return 0;
    return (const uint8_t *)p + len <= (const uint8_t *)mbi.BaseAddress + mbi.RegionSize;
}

// 診斷：記下 prep 回呼拿到的 rect（判斷是否逐磚塊呼叫、能否取得座標 → 決定鄰域濾鏡可行性）
static void log_prep(const char *name, const char *phase, void *rect) {
    if (!g_cfg_debug) return;
    static volatile LONG c = 0;
    if (InterlockedIncrement(&c) > 48) return;
    if (rect && mem_readable(rect, 24)) {
        int32_t *r = (int32_t *)rect;
        mod_log("%s %s: [%d %d %d %d %d %d] thread=%lu",
                name, phase, r[0], r[1], r[2], r[3], r[4], r[5], GetCurrentThreadId());
    } else {
        mod_log("%s %s: rect=%p thread=%lu", name, phase, rect, GetCurrentThreadId());
    }
}

// 只在「看起來是 UI context」時寫入：SAI2 自己的字串表在 slot 2，context 會有同一個指標
static int install_into_ctx(uint8_t *ctx, void **glob_str) {
    if (!mem_rw(ctx + 0x90, 4 * sizeof(void *))) return 0;
    void **slots = (void **)(ctx + 0x90);
    if (slots[0] == g_mod_strings) return 1;
    if (!glob_str[2] || slots[2] != glob_str[2]) return 0;
    slots[0] = g_mod_strings;
    return 1;
}

static int install_into_window(HWND h, void **glob_str) {
    uint8_t *wi = (uint8_t *)GetPropW(h, L"SYSTEMAX-WININFO");
    if (!mem_rw(wi, 0x60)) return 0;
    int n = 0;
    // UI context 指標藏在 wininfo 裡（2026=+0x30、2023=+0x38）；對話框可能用別的位移，
    // 所以掃一段範圍，每個都用「slot 2 == SAI2 全域字串表」驗證，寫錯位置會被擋下
    for (size_t off = 0x28; off <= 0x50; off += 8) {
        uint8_t *ctx = *(uint8_t **)(wi + off);
        if (ctx && install_into_ctx(ctx, glob_str)) n++;
    }
    return n;
}

static BOOL CALLBACK install_child_cb(HWND h, LPARAM lp) {
    *(int *)lp += install_into_window(h, (void **)(g_base + g_off->rva_glob_str_tbl));
    return TRUE;
}

static BOOL CALLBACK install_enum_cb(HWND h, LPARAM lp) {
    DWORD pid = 0;
    GetWindowThreadProcessId(h, &pid);
    if (pid == GetCurrentProcessId()) {
        int *count = (int *)lp;
        *count += install_into_window(h, (void **)(g_base + g_off->rva_glob_str_tbl));
        EnumChildWindows(h, install_child_cb, lp);   // 對話框若是子視窗也要涵蓋
    }
    return TRUE;
}

// obj 可能直接就是 UI context（例如對話框物件），也試著寫進去
static int install_ctx_object(void *obj) {
    if (!obj || !g_off) return 0;
    void **glob_str = (void **)(g_base + g_off->rva_glob_str_tbl);
    return install_into_ctx((uint8_t *)obj, glob_str) ? 1 : 0;
}

static void ensure_string_table_installed(void) {
    if (!g_off) return;
    void **glob_str = (void **)(g_base + g_off->rva_glob_str_tbl);
    glob_str[0] = g_mod_strings;            // slot 0 SAI2 沒有使用（它只註冊 slot 2）

    int n = 0;
    if (g_off->rva_default_ctx) {
        uint8_t *ctx = *(uint8_t **)(g_base + g_off->rva_default_ctx);
        if (ctx && install_into_ctx(ctx, glob_str)) n++;
    }
    EnumWindows(install_enum_cb, (LPARAM)&n);

    static int s_last = -1;
    if (n != s_last) {
        mod_log("string table installed into %d UI context(s) (profile %d)", n, g_off->ver_type);
        s_last = n;
    }
}

// 對話框建立時（SAI2 呼叫 build_ui）再裝一次：此時對話框視窗／context 才存在
static void install_for_dialog(void *dlg, const char *who) {
    ensure_string_table_installed();
    int d = install_ctx_object(dlg);
    mod_log("%s build_ui: dlg=%p installed_as_ctx=%d", who, dlg, d);
}

// 診斷：像素回呼前幾次被呼叫時的參數（判斷一次處理的範圍，供之後的濾鏡使用）
static volatile LONG g_px_log_count = 0;
static void log_pixel_call(const char *name, int count, const void *dst, const void *src, void *ret) {
    if (!g_cfg_debug) return;
    if (InterlockedIncrement(&g_px_log_count) > 12) return;
    mod_log("%s: count=%d dst-src=%lld caller=+0x%llx thread=%lu", name, count,
            (long long)((const char *)dst - (const char *)src),
            (unsigned long long)((uintptr_t)ret - g_base), GetCurrentThreadId());
}

static void *create_filter_instance(
    size_t state_size,
    int32_t init_val,
    size_t init_val_off,
    void **cur_state_slot,       // 存一份目前狀態指標（濾鏡間狀態結構大小可能相同，不能用大小判斷）
    void *cb_build_ui,
    void *cb_params_2023,
    void *cb_params_2026,
    void *cb_prep_prev,
    void *cb_prep_commit,
    void *cb_proc_pixels,
    uint32_t title_str_id,
    const char *id_str
) {
    uint8_t *st = (uint8_t *)((fn_alloc_t)(g_base + g_off->rva_alloc))(state_size);
    if (!st) return NULL;
    memset(st, 0, state_size);
    *(int32_t *)(st + init_val_off) = init_val;
    if (cur_state_slot) *cur_state_slot = st;

    uint8_t desc[0xB0];
    memset(desc, 0, sizeof(desc));

    if (g_off->ver_type == 2023) {
        *(void **)(desc + 0x00)   = (void *)(g_base + g_off->rva_free);
        *(void **)(desc + 0x08)   = cb_build_ui;
        *(void **)(desc + 0x10)   = cb_params_2023;
        *(void **)(desc + 0x18)   = (void *)(g_base + g_off->rva_free);
        *(void **)(desc + 0x20)   = (void *)(g_base + g_off->rva_ret1);
        *(void **)(desc + 0x28)   = (void *)(g_base + g_off->rva_ret0);
        *(void **)(desc + 0x30)   = cb_prep_prev;
        *(void **)(desc + 0x38)   = cb_prep_commit;
        *(void **)(desc + 0x58)   = cb_proc_pixels;
        *(uint32_t *)(desc + 0x7c)= title_str_id;
        *(uint32_t *)(desc + 0x80)= 3;
        *(uint32_t *)(desc + 0x84)= 0x40000010;
        *(uint32_t *)(desc + 0x88)= 0xC;
        ((fn_strcpy_t)(g_base + g_off->rva_strcpy))((char *)(desc + 0x8f), 0x20, id_str);
    } else {
        *(void **)(desc + 0x00)   = (void *)(g_base + g_off->rva_free);
        *(void **)(desc + 0x08)   = cb_params_2026;
        *(void **)(desc + 0x10)   = cb_build_ui;
        *(void **)(desc + 0x18)   = (void *)(g_base + g_off->rva_ret1);
        *(void **)(desc + 0x20)   = (void *)(g_base + g_off->rva_ret0);
        *(void **)(desc + 0x28)   = cb_prep_prev;
        *(void **)(desc + 0x30)   = cb_prep_commit;
        *(void **)(desc + 0x50)   = cb_proc_pixels;
        *(uint32_t *)(desc + 0x74)= title_str_id;
        *(uint32_t *)(desc + 0x78)= 3;
        *(uint32_t *)(desc + 0x7c)= 0x40000010;
        *(uint32_t *)(desc + 0x80)= 3;
        *(uint32_t *)(desc + 0x84)= 0x18;
        ((fn_strcpy_t)(g_base + g_off->rva_strcpy))((char *)(desc + 0x8b), 0x20, id_str);
    }

    void *obj = ((fn_reg_filter_t)(g_base + g_off->rva_reg_filter))(desc, st);
    if (!obj) {
        ((fn_free_t)(g_base + g_off->rva_free))(st);
    }
    return obj;
}

static void launch_filter_obj(void *filter_obj) {
    if (!filter_obj || !g_off) return;
    ensure_string_table_installed();
    void *doc = *(void **)(g_base + g_off->rva_active_doc);
    if (!doc) return;
    if (g_off->ver_type == 2023) {
        ((fn_run_filter_2023_t)(g_base + g_off->rva_run_filter))(filter_obj, doc);
    } else {
        ((fn_run_filter_2026_t)(g_base + g_off->rva_run_filter))(filter_obj);
    }
}

static void open_binarize_filter(void) {
    if (!g_bin_filter_obj) {
        g_bin_filter_obj = create_filter_instance(
            sizeof(BinarizeState),
            128,
            offsetof(BinarizeState, ui_threshold),
            (void **)&g_cur_bin_state,
            (void *)bin_build_ui,
            (void *)bin_create_params_2023,
            (void *)bin_copy_params_2026,
            (void *)bin_prep_preview,
            (void *)bin_prep_commit,
            (void *)bin_process_pixels,
            STR_BIN_TITLE,
            "adjustment.binarize"
        );
    }
    launch_filter_obj(g_bin_filter_obj);
}

static void open_posterize_filter(void) {
    if (!g_pos_filter_obj) {
        g_pos_filter_obj = create_filter_instance(
            sizeof(PosterizeState),
            4,
            offsetof(PosterizeState, ui_levels),
            (void **)&g_cur_pos_state,
            (void *)pos_build_ui,
            (void *)pos_create_params_2023,
            (void *)pos_copy_params_2026,
            (void *)pos_prep_preview,
            (void *)pos_prep_commit,
            (void *)pos_process_pixels,
            STR_POS_TITLE,
            "adjustment.posterize"
        );
    }
    launch_filter_obj(g_pos_filter_obj);
}

static void open_pixelate_filter(void) {
    if (!g_pix_filter_obj) {
        g_pix_filter_obj = create_filter_instance(
            sizeof(PixelateState),
            3,
            offsetof(PixelateState, ui_block),
            (void **)&g_cur_pix_state,
            (void *)pix_build_ui,
            (void *)pix_create_params_2023,
            (void *)pix_copy_params_2026,
            (void *)pix_prep_preview,
            (void *)pix_prep_commit,
            (void *)pix_process_pixels,
            STR_PIX_TITLE,
            "adjustment.pixelate"
        );
    }
    launch_filter_obj(g_pix_filter_obj);
}

static void open_sharpen_filter(void) {
    if (!g_shp_filter_obj) {
        g_shp_filter_obj = create_filter_instance(
            sizeof(SharpenState),
            3,
            offsetof(SharpenState, ui_amount),
            (void **)&g_cur_shp_state,
            (void *)shp_build_ui,
            (void *)shp_create_params_2023,
            (void *)shp_copy_params_2026,
            (void *)shp_prep_preview,
            (void *)shp_prep_commit,
            (void *)shp_process_pixels,
            STR_SHP_TITLE,
            "adjustment.sharpen"
        );
    }
    launch_filter_obj(g_shp_filter_obj);
}

// ─────────────────────────────────────────────────────────────────────────
// Menu Injection & Synchronization
// ─────────────────────────────────────────────────────────────────────────

#define WM_SAI2MOD_INIT (WM_APP + 0x5A1)

static HMENU g_h_eff_submenu = NULL;

static int menu_has_cmd(HMENU hm, UINT cmd) {
    if (!hm) return 0;
    if (GetMenuState(hm, cmd, MF_BYCOMMAND) != (UINT)-1) return 1;
    int cnt = GetMenuItemCount(hm);
    for (int i = 0; i < cnt; i++) {
        HMENU sub = GetSubMenu(hm, i);
        if (sub && menu_has_cmd(sub, cmd)) return 1;
    }
    return 0;
}

static HMENU get_sai2_filter_menu(HWND hwnd) {
    if (!hwnd || !g_off) return NULL;
    uint8_t *wi = (uint8_t *)GetPropW(hwnd, L"SYSTEMAX-WININFO");
    if (!wi) return NULL;
    uint8_t *mb = *(uint8_t **)(wi + 0x88);
    if (!mb) return NULL;
    HMENU h_main = *(HMENU *)(mb + 0x58);
    if (!h_main) return NULL;

    int cnt = GetMenuItemCount(h_main);
    for (int i = 0; i < cnt; i++) {
        HMENU h_sub = GetSubMenu(h_main, i);
        if (!h_sub) continue;
        WCHAR title[64];
        title[0] = 0;
        GetMenuStringW(h_main, i, title, 64, MF_BYPOSITION);
        if (wcsstr(title, L"濾鏡") || wcsstr(title, L"滤镜") ||
            wcsstr(title, L"Filter") || wcsstr(title, L"フィルター") ||
            menu_has_cmd(h_sub, g_off->cmd_id_lumcon)) {
            return h_sub;
        }
    }
    return NULL;
}

static void ensure_effects_menu_injected(HWND hwnd) {
    if (!g_cfg_enabled || (!g_cfg_binarize && !g_cfg_posterize && !g_cfg_pixelate && !g_cfg_sharpen)) return;
    ensure_string_table_installed();
    HMENU h_filter = get_sai2_filter_menu(hwnd);
    if (!h_filter) return;

    int already_injected =
        (GetMenuState(h_filter, MENU_ID_BINARIZE, MF_BYCOMMAND) != (UINT)-1) ||
        (GetMenuState(h_filter, MENU_ID_POSTERIZE, MF_BYCOMMAND) != (UINT)-1) ||
        (GetMenuState(h_filter, MENU_ID_PIXELATE, MF_BYCOMMAND) != (UINT)-1) ||
        (GetMenuState(h_filter, MENU_ID_SHARPEN, MF_BYCOMMAND) != (UINT)-1);

    if (!already_injected) {
        HMENU h_eff = CreatePopupMenu();
        if (!h_eff) return;
        g_h_eff_submenu = h_eff;

        int idx = 0;
        if (g_cfg_binarize) {
            MENUITEMINFOW item;
            memset(&item, 0, sizeof(item));
            item.cbSize     = sizeof(item);
            item.fMask      = MIIM_ID | MIIM_STRING | MIIM_FTYPE | MIIM_STATE;
            item.fType      = MFT_STRING;
            item.fState     = MFS_ENABLED;
            item.wID        = MENU_ID_BINARIZE;
            item.dwTypeData = L"二值化(&B) ...";
            InsertMenuItemW(h_eff, idx++, TRUE, &item);
        }
        if (g_cfg_posterize) {
            MENUITEMINFOW item;
            memset(&item, 0, sizeof(item));
            item.cbSize     = sizeof(item);
            item.fMask      = MIIM_ID | MIIM_STRING | MIIM_FTYPE | MIIM_STATE;
            item.fType      = MFT_STRING;
            item.fState     = MFS_ENABLED;
            item.wID        = MENU_ID_POSTERIZE;
            item.dwTypeData = L"色調分離(&P) ...";
            InsertMenuItemW(h_eff, idx++, TRUE, &item);
        }
        if (g_cfg_pixelate) {
            MENUITEMINFOW item;
            memset(&item, 0, sizeof(item));
            item.cbSize     = sizeof(item);
            item.fMask      = MIIM_ID | MIIM_STRING | MIIM_FTYPE | MIIM_STATE;
            item.fType      = MFT_STRING;
            item.fState     = MFS_ENABLED;
            item.wID        = MENU_ID_PIXELATE;
            item.dwTypeData = L"像素化(&X) ...";
            InsertMenuItemW(h_eff, idx++, TRUE, &item);
        }
        if (g_cfg_sharpen) {
            MENUITEMINFOW item;
            memset(&item, 0, sizeof(item));
            item.cbSize     = sizeof(item);
            item.fMask      = MIIM_ID | MIIM_STRING | MIIM_FTYPE | MIIM_STATE;
            item.fType      = MFT_STRING;
            item.fState     = MFS_ENABLED;
            item.wID        = MENU_ID_SHARPEN;
            item.dwTypeData = L"銳化(&S) ...";
            InsertMenuItemW(h_eff, idx++, TRUE, &item);
        }

        int pos = GetMenuItemCount(h_filter);
        MENUITEMINFOW sep;
        memset(&sep, 0, sizeof(sep));
        sep.cbSize = sizeof(sep);
        sep.fMask  = MIIM_ID | MIIM_FTYPE;
        sep.fType  = MFT_SEPARATOR;
        sep.wID    = MENU_ID_EFFECT_SEP;
        InsertMenuItemW(h_filter, pos, TRUE, &sep);

        MENUITEMINFOW sub;
        memset(&sub, 0, sizeof(sub));
        sub.cbSize     = sizeof(sub);
        sub.fMask      = MIIM_ID | MIIM_SUBMENU | MIIM_STRING | MIIM_FTYPE | MIIM_STATE;
        sub.fType      = MFT_STRING;
        sub.fState     = MFS_ENABLED;
        sub.wID        = MENU_ID_EFFECT_SUBMENU;
        sub.hSubMenu   = h_eff;
        sub.dwTypeData = L"效果(&E)";
        InsertMenuItemW(h_filter, pos + 1, TRUE, &sub);
    }

    // Sync enabled/grayed state with active document
    void *doc = *(void **)(g_base + g_off->rva_active_doc);
    int can_run = (doc != NULL);
    UINT flag = MF_BYCOMMAND | (can_run ? MF_ENABLED : MF_GRAYED);
    EnableMenuItem(h_filter, MENU_ID_EFFECT_SUBMENU, flag);
    EnableMenuItem(h_filter, MENU_ID_BINARIZE, flag);
    EnableMenuItem(h_filter, MENU_ID_POSTERIZE, flag);
    EnableMenuItem(h_filter, MENU_ID_PIXELATE, flag);
    EnableMenuItem(h_filter, MENU_ID_SHARPEN, flag);
    if (g_h_eff_submenu) {
        EnableMenuItem(g_h_eff_submenu, MENU_ID_BINARIZE, flag);
        EnableMenuItem(g_h_eff_submenu, MENU_ID_POSTERIZE, flag);
        EnableMenuItem(g_h_eff_submenu, MENU_ID_PIXELATE, flag);
        EnableMenuItem(g_h_eff_submenu, MENU_ID_SHARPEN, flag);
    }
}

static LRESULT CALLBACK main_subclass_proc(HWND h, UINT m, WPARAM w, LPARAM l) {
    if (m == WM_SAI2MOD_INIT) {
        ensure_effects_menu_injected(h);
        return 0;
    }
    if (m == WM_INITMENU || m == WM_INITMENUPOPUP) {
        LRESULT r = CallWindowProcW(g_orig_wndproc, h, m, w, l);
        ensure_effects_menu_injected(h);
        return r;
    }
    if (m == WM_COMMAND) {
        UINT id = (UINT)w;
        if (id == MENU_ID_BINARIZE || LOWORD(w) == LOWORD(MENU_ID_BINARIZE)) {
            open_binarize_filter();
            return 0;
        }
        if (id == MENU_ID_POSTERIZE || LOWORD(w) == LOWORD(MENU_ID_POSTERIZE)) {
            open_posterize_filter();
            return 0;
        }
        if (id == MENU_ID_PIXELATE || LOWORD(w) == LOWORD(MENU_ID_PIXELATE)) {
            open_pixelate_filter();
            return 0;
        }
        if (id == MENU_ID_SHARPEN || LOWORD(w) == LOWORD(MENU_ID_SHARPEN)) {
            open_sharpen_filter();
            return 0;
        }
    }
    return CallWindowProcW(g_orig_wndproc, h, m, w, l);
}

static void load_mod_config(void) {
    WCHAR ini_path[MAX_PATH];
    GetModuleFileNameW(NULL, ini_path, MAX_PATH);
    WCHAR *slash = ini_path + lstrlenW(ini_path);
    while (slash > ini_path && slash[-1] != L'\\' && slash[-1] != L'/') slash--;
    lstrcpyW(slash, L"sai2_filters_mod.ini");

    g_cfg_enabled   = GetPrivateProfileIntW(L"FiltersMod", L"enabled",   1, ini_path);
    g_cfg_binarize  = GetPrivateProfileIntW(L"FiltersMod", L"binarize",  1, ini_path);
    g_cfg_posterize = GetPrivateProfileIntW(L"FiltersMod", L"posterize", 1, ini_path);
    g_cfg_pixelate  = GetPrivateProfileIntW(L"FiltersMod", L"pixelate",  1, ini_path);
    g_cfg_sharpen   = GetPrivateProfileIntW(L"FiltersMod", L"sharpen",   1, ini_path);
    g_cfg_debug     = GetPrivateProfileIntW(L"FiltersMod", L"debug",     0, ini_path);
}

static BOOL CALLBACK find_main_hwnd_cb(HWND h, LPARAM lp) {
    DWORD pid = 0;
    GetWindowThreadProcessId(h, &pid);
    if (pid == GetCurrentProcessId() && GetPropW(h, L"SYSTEMAX-WININFO") && !GetParent(h)) {
        WCHAR title[256];
        GetWindowTextW(h, title, 256);
        if (wcsstr(title, L"PaintTool SAI") || wcsstr(title, L"SAI")) {
            g_main_hwnd = h;
            return FALSE;
        }
    }
    return TRUE;
}

static DWORD WINAPI init_worker_thread(LPVOID param) {
    load_mod_config();
    if (!g_cfg_enabled || (!g_cfg_binarize && !g_cfg_posterize && !g_cfg_pixelate && !g_cfg_sharpen)) {
        return 0;
    }

    g_base = (uintptr_t)GetModuleHandleW(NULL);
    if (!g_base) return 0;

    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)g_base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return 0;
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(g_base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return 0;

    uint32_t ts = nt->FileHeader.TimeDateStamp;
    for (size_t i = 0; i < sizeof(k_profiles) / sizeof(k_profiles[0]); i++) {
        if (k_profiles[i].timestamp == ts) {
            g_off = &k_profiles[i];
            break;
        }
    }
    if (!g_off) {
        // 認不得這個 SAI2 版本（timestamp 不符）：所有內部位址都是依版本硬編碼的，
        // 套用錯的位址會直接讓 SAI2 當掉。寧可不注入（選單不出現），也不要冒險。
        // 要支援新版 SAI2：用 native/sai2mod/README.md 的流程重新產生 offset 並加一組 profile。
        mod_log("unknown SAI2 build timestamp 0x%08x — not injecting (need a new profile)", ts);
        return 0;
    }

    for (int i = 0; i < 300 && !g_main_hwnd; i++) {
        EnumWindows(find_main_hwnd_cb, 0);
        if (!g_main_hwnd) Sleep(100);
    }
    if (!g_main_hwnd) return 0;

    ensure_string_table_installed();
    g_orig_wndproc = (WNDPROC)SetWindowLongPtrW(g_main_hwnd, GWLP_WNDPROC, (LONG_PTR)main_subclass_proc);

    // Wait until SYSTEMAX-WININFO->pMenuBar->hMainMenu is ready and inject on UI thread
    for (int i = 0; i < 50; i++) {
        if (get_sai2_filter_menu(g_main_hwnd)) {
            PostMessageW(g_main_hwnd, WM_SAI2MOD_INIT, 0, 0);
            break;
        }
        Sleep(100);
    }
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE hinst, DWORD reason, LPVOID reserved) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hinst);
        HANDLE ht = CreateThread(NULL, 0, init_worker_thread, NULL, 0, NULL);
        if (ht) CloseHandle(ht);
    }
    return TRUE;
}
