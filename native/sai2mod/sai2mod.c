/*
 * sai2mod.c — PaintTool SAI Ver.2 Native Filter Expansion Mod (mscms.dll proxy)
 *
 * 將「效果 (Effects)」子選單（「二值化 ...」、「色調分離 ...」）直接注入 SAI2 原生「濾鏡」選單，
 * 並對接 SAI2 內部原生濾鏡引擎 (FilterDescriptor / 16-bit Tile Engine)：
 *   - 100% 原生 SAI2 濾鏡對話框（自動套用 sai2S 深色/自訂主題）
 *   - 16-bit BGRA 磚塊多執行緒畫布即時預覽（支援選取範圍、保護不透明度、圖層資料夾、剪裁遮罩）
 *   - 點擊「確定」直接寫入圖層並建立原生 Undo/Redo 歷史步驟（完整支援 Ctrl+Z / Ctrl+Y）
 * 另外在圖層面板「特殊效果」加入非破壞的「筆畫」圖層效果（2026 版，見 fx_stroke_install）。
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
#include <math.h>

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
#define STR_FX_TITLE            0x4000E   // 特殊效果下拉選單的「筆畫」
#define STR_FX_GROUP            0x4000F   // 圖層面板 RGB 群組
#define STR_FX_R_LBL            0x40010
#define STR_FX_G_LBL            0x40011
#define STR_FX_B_LBL            0x40012
#define STR_FX_R_CTL            0x40013
#define STR_FX_G_CTL            0x40014
#define STR_FX_B_CTL            0x40015

typedef struct {
    const wchar_t *key;
    const wchar_t *text;
    const wchar_t *sub;
    uint64_t       pad1;
    uint64_t       pad2;
    uint64_t       flags;
} Sai2StrEntry; // 48 bytes (0x30)

static Sai2StrEntry g_mod_strings[23] = {
    { NULL, (const wchar_t *)23, NULL, 0, 0, 0 },
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
    { L"Mod_FxStroke_Title",    L"筆畫",                       NULL, 0, 0, 0 },
    { L"Mod_FxStroke_Group",    L"",                           NULL, 0, 0, 0 },
    { L"Mod_FxStroke_RLbl",     L"紅",                         NULL, 0, 0, 0 },
    { L"Mod_FxStroke_GLbl",     L"綠",                         NULL, 0, 0, 0 },
    { L"Mod_FxStroke_BLbl",     L"藍",                         NULL, 0, 0, 0 },
    { L"Mod_FxStroke_RCtl",     L"",                           NULL, 0, 0, 0 },
    { L"Mod_FxStroke_GCtl",     L"",                           NULL, 0, 0, 0 },
    { L"Mod_FxStroke_BCtl",     L"",                           NULL, 0, 0, 0 },
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
static int g_cfg_fx_stroke = 1;           // 圖層效果「筆畫」
static uint32_t g_cfg_fx_rgb = 0x000000;  // 新的筆畫圖層預設顏色（= 最近一次用過的顏色，模組會寫回 ini）
static WCHAR g_ini_path[MAX_PATH];        // sai2_filters_mod.ini
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

// ─────────────────────────────────────────────────────────────────────────
// 圖層效果「筆畫」（非破壞，只支援 2026）：借用 SAI2「水彩邊緣」圖層效果的管線
//
// 筆畫圖層 = 特殊效果是水彩邊緣（layer+0x254 == 1）且圖層名稱帶 [#RRGGBB] 標記。
// 水彩邊緣圖層的每個圖層磚塊都配一張效果磚塊（32x32 uint16，磚塊格 +0x10[ty][tx]），由 SAI2
// 自己配置、在圖層內容變動時呼叫 0x10cd20 重算、合成時由 0x10e470 取出並疊上。inline hook 這兩個：
//   重算 → 原函式照跑（負責配置效果磚塊），之後把內容換成內側筆畫覆蓋率（Q14）
//   取磚塊 → 不走水彩邊緣的混合，改成用覆蓋率把標記的顏色塗上去
// 寬度 = 水彩邊緣「寬度」×2（1..15 → 2..30px），不透明度 = 「強度」（+0x84，Q14）。
// 存檔是原生的水彩邊緣設定 + 圖層名稱；沒裝模組的 SAI2 打開只會看到一般的水彩邊緣。
// 函式 / 全域位址是 2026（0x6ad549f7）專用：只在該 profile 啟用，且掛之前逐一比對開頭位元組。
// ─────────────────────────────────────────────────────────────────────────

#define STK_TILE   32
#define STK_MARGIN 32                              // 寬度上限 = 邊距
#define STK_WIN    (STK_TILE + 2 * STK_MARGIN)     // 96
#define STK_BG_A   0x1000                          // alpha 低於此值視為透明背景
#define STK_INF    1e20f

// 圖層磚塊格（layer+0xf0..0x118，6 層 mip）：+0 旗標列、+8 磚塊指標列（tile = rows[ty][tx]）、
// +0x10 效果磚塊列、+0x20..0x2c 磚塊範圍 [x0 y0 x1 y1)。旗標 bit0 = 一般磚塊（槽位是 32x32 預乘
// 16-bit BGRA 像素指標）；bit1 = 單色磚塊（槽位本身就是那 1 個像素）；兩者皆無 = 空白
// 熱路徑用：只檢查範圍，不做 VirtualQuery
// 回傳像素起點；*uniform=1 表示單色磚塊（只有 1 個像素，所有位置都讀它）
static const uint16_t *layer_tile_at(const uint8_t *tg, int tx, int ty, int *uniform) {
    *uniform = 0;
    const int32_t *b = (const int32_t *)(tg + 0x20);
    if (tx < b[0] || ty < b[1] || tx >= b[2] || ty >= b[3]) return NULL;
    const uint8_t *const *frows = *(const uint8_t *const **)(tg + 0x00);
    const uint8_t *const *trows = *(const uint8_t *const **)(tg + 0x08);
    const uint8_t *fr = frows[ty];
    const uint16_t *const *row = (const uint16_t *const *)trows[ty];
    if (!fr || !row) return NULL;
    if (fr[tx] & 1) return row[tx];
    if (fr[tx] & 2) { *uniform = 1; return (const uint16_t *)&row[tx]; }
    return NULL;
}

// Felzenszwalb 1D 平方距離轉換
static void edt_1d(const float *f, int n, float *d, int *v, float *z) {
    int k = 0;
    v[0] = 0;
    z[0] = -STK_INF;
    z[1] = STK_INF;
    for (int q = 1; q < n; q++) {
        float s;
        for (;;) {   // z[0] = -INF 且 s 有界（|f| ≤ 1e20），所以 k 不會跌破 0
            int r = v[k];
            s = ((f[q] + (float)(q * q)) - (f[r] + (float)(r * r))) / (float)(2 * q - 2 * r);
            if (s > z[k]) break;
            k--;
        }
        k++;
        v[k] = q;
        z[k] = s;
        z[k + 1] = STK_INF;
    }
    k = 0;
    for (int q = 0; q < n; q++) {
        while (z[k + 1] < (float)q) k++;
        float dq = (float)(q - v[k]);
        d[q] = dq * dq + f[v[k]];
    }
}

// 一個磚塊的內側筆畫覆蓋率（Q14，0..0x4000）：取本身 + 四周 32px 的 alpha 做距離轉換
// center 是這個磚塊的像素（center_uni=1 表示單色磚塊，只有 1 個像素）
static void stroke_coverage(const uint8_t *tg, int tx, int ty, const uint16_t *center, int center_uni,
                            float width, float *g, uint16_t *cov) {
    // 1) 96x96 視窗的背景遮罩：背景 0、前景 INF
    for (int j = -1; j <= 1; j++)
        for (int i = -1; i <= 1; i++) {
            int uni = center_uni;
            const uint16_t *t = (i == 0 && j == 0) ? center : layer_tile_at(tg, tx + i, ty + j, &uni);
            for (int y = 0; y < STK_TILE; y++) {
                float *row = g + ((j + 1) * STK_TILE + y) * STK_WIN + (i + 1) * STK_TILE;
                for (int x = 0; x < STK_TILE; x++)
                    row[x] = (t && t[uni ? 3 : (y * STK_TILE + x) * 4 + 3] >= STK_BG_A) ? STK_INF : 0.0f;
            }
        }

    // 2) 先逐列、再逐行（只算中間 32 行）
    float f[STK_WIN], d[STK_WIN], z[STK_WIN + 1];
    int v[STK_WIN];
    for (int y = 0; y < STK_WIN; y++) {
        edt_1d(g + y * STK_WIN, STK_WIN, d, v, z);
        memcpy(g + y * STK_WIN, d, sizeof(d));
    }
    for (int x = STK_MARGIN; x < STK_MARGIN + STK_TILE; x++) {
        for (int y = 0; y < STK_WIN; y++) f[y] = g[y * STK_WIN + x];
        edt_1d(f, STK_WIN, d, v, z);
        for (int y = 0; y < STK_WIN; y++) g[y * STK_WIN + x] = d[y];
    }

    // 3) 覆蓋率 = clamp(寬度 + 1 - 距離, 0, 1)；半透明邊緣像素直接算滿
    for (int y = 0; y < STK_TILE; y++)
        for (int x = 0; x < STK_TILE; x++) {
            uint32_t a = center[center_uni ? 3 : (y * STK_TILE + x) * 4 + 3];
            float c;
            if (a == 0) c = 0.0f;
            else if (a < STK_BG_A) c = 1.0f;
            else {
                c = width + 1.0f - sqrtf(g[(y + STK_MARGIN) * STK_WIN + x + STK_MARGIN]);
                c = c < 0.0f ? 0.0f : (c > 1.0f ? 1.0f : c);
            }
            cov[y * STK_TILE + x] = (uint16_t)(c * 16384.0f + 0.5f);
        }
}

// 用覆蓋率把顏色塗上去（保留原 alpha）：out = in + (色×alpha − in) × 覆蓋率 × 不透明度
static void stroke_paint(uint16_t *dst, const uint16_t *src, const uint16_t *cov, uint32_t rgb, uint32_t opacity_q14) {
    const uint32_t cr = (rgb >> 16) & 0xff, cg = (rgb >> 8) & 0xff, cb = rgb & 0xff;
    for (int i = 0; i < STK_TILE * STK_TILE; i++) {
        const uint16_t *c = src + i * 4;
        uint16_t *o = dst + i * 4;
        int32_t a = c[3];
        int32_t k = (int32_t)(((uint32_t)cov[i] * opacity_q14) >> 14);
        if (a == 0 || k == 0) { *(uint64_t *)o = *(const uint64_t *)c; continue; }
        int32_t sb = (int32_t)((cb * (uint32_t)a + 127) / 255);
        int32_t sg = (int32_t)((cg * (uint32_t)a + 127) / 255);
        int32_t sr = (int32_t)((cr * (uint32_t)a + 127) / 255);
        o[0] = (uint16_t)(c[0] + (((sb - c[0]) * k) >> 14));
        o[1] = (uint16_t)(c[1] + (((sg - c[1]) * k) >> 14));
        o[2] = (uint16_t)(c[2] + (((sr - c[2]) * k) >> 14));
        o[3] = (uint16_t)a;
    }
}

typedef uint64_t (*fn_any8_t)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);

typedef struct {
    uintptr_t   rva;
    size_t      len;            // 被搬走的指令長度（剛好落在指令邊界、≥14）
    const char *expect_hex;     // 開頭位元組，對不上就不掛
    void       *detour;
    uint8_t     saved[24];
    uint8_t    *tramp;
    int         active;
    int         own_tramp;      // 1 = trampoline 已自行組好（不要照抄開頭位元組）
} InlineHook;

static int hex_eq(const uint8_t *p, const char *hex, size_t n) {
    for (size_t i = 0; i < n; i++) {
        unsigned v;
        if (sscanf_s(hex + i * 2, "%2x", &v) != 1 || p[i] != (uint8_t)v) return 0;
    }
    return 1;
}

static void write_absjmp(uint8_t *at, uint64_t to) {
    at[0] = 0xFF; at[1] = 0x25;                 // jmp qword ptr [rip+0]
    *(uint32_t *)(at + 2) = 0;
    *(uint64_t *)(at + 6) = to;
}

static int hook_install(InlineHook *h) {
    if (h->active) return 1;
    uint8_t *target = (uint8_t *)(g_base + h->rva);
    if (!hex_eq(target, h->expect_hex, h->len)) {
        mod_log("hook +%llx: 開頭位元組不符，不掛", (unsigned long long)h->rva);
        return 0;
    }
    if (!h->tramp) {
        h->tramp = (uint8_t *)VirtualAlloc(NULL, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
        if (!h->tramp) return 0;
    }
    memcpy(h->saved, target, h->len);
    if (!h->own_tramp) {
        memcpy(h->tramp, target, h->len);
        write_absjmp(h->tramp + h->len, (uint64_t)(target + h->len));
    }
    DWORD old;
    if (!VirtualProtect(target, h->len, PAGE_EXECUTE_READWRITE, &old)) return 0;
    uint8_t patch[24];
    write_absjmp(patch, (uint64_t)h->detour);
    for (size_t i = 14; i < h->len; i++) patch[i] = 0x90;
    memcpy(target, patch, h->len);
    VirtualProtect(target, h->len, old, &old);
    FlushInstructionCache(GetCurrentProcess(), target, h->len);
    h->active = 1;
    return 1;
}

#define FX_EFFECT_FRINGE 1      // layer+0x254：0 無、1 水彩邊緣、2 色彩二值化、3 網點

static uint64_t fx_get_tile(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);
static uint64_t fx_update(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);
static uint64_t fx_set_name(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);

static InlineHook g_hk_get    = { 0x10e470, 14, "48895c2408574883ec40418b4004", (void *)fx_get_tile };
static InlineHook g_hk_update = { 0x10cd20, 14, "4c894c242048894c240853555657", (void *)fx_update };
static InlineHook g_hk_name   = { 0x10b340, 15, "48896c24104889742418574883ec20", (void *)fx_set_name };
static volatile LONG g_fx_fault = 0;

#define FX_NAME_MAX 0xfe     // SAI2 圖層名稱上限（0x10b470 檢查 ≤ 0xfe 字）

static inline int fx_hex(wchar_t c) {
    if (c >= L'0' && c <= L'9') return c - L'0';
    if (c >= L'a' && c <= L'f') return c - L'a' + 10;
    if (c >= L'A' && c <= L'F') return c - L'A' + 10;
    return -1;
}

// n[i] 開始是不是 [#RRGGBB]：逐字檢查，碰到結尾會先失敗，不會讀過頭
static int32_t fx_tag_at(const wchar_t *n, int i) {
    if (n[i] != L'[' || n[i + 1] != L'#') return -1;
    int32_t rgb = 0;
    for (int k = 2; k < 8; k++) {
        int h = fx_hex(n[i + k]);
        if (h < 0) return -1;
        rgb = (rgb << 4) | h;
    }
    return n[i + 8] == L']' ? rgb : -1;
}

// 圖層名稱裡的 [#RRGGBB] 標記 → 顏色；沒有標記回傳 -1
static int32_t fx_name_color(const uint8_t *layer) {
    const wchar_t *n = *(const wchar_t *const *)(layer + 0x278);
    if (!n) return -1;
    for (int i = 0; i < FX_NAME_MAX && n[i]; i++) {
        int32_t rgb = fx_tag_at(n, i);
        if (rgb >= 0) return rgb;
    }
    return -1;
}

#define WM_SAI2MOD_FXREFRESH (WM_APP + 0x5A2)
static void fx_panel_sync(void);

// 筆畫圖層 = 水彩邊緣 + 名稱帶 [#RRGGBB]；回傳顏色，不是則 -1
static const uint8_t *volatile g_fx_preview_layer = NULL;   // 拖動 RGB 滑桿中：先用預覽色畫，放開才改名
static volatile int32_t g_fx_preview_rgb = -1;

static inline int32_t fx_stroke_color(const uint8_t *layer) {
    if (!g_cfg_fx_stroke || *(const int32_t *)(layer + 0x254) != FX_EFFECT_FRINGE) return -1;
    int32_t rgb = fx_name_color(layer);
    if (rgb >= 0 && layer == g_fx_preview_layer && g_fx_preview_rgb >= 0) rgb = g_fx_preview_rgb;
    return rgb;
}

// 合成時取磚塊：(out, layer, coord{?, level, tx, ty}, in) → 回傳像素指標
static uint64_t fx_get_tile(uint64_t out, uint64_t layer, uint64_t coord, uint64_t in,
                            uint64_t a5, uint64_t a6, uint64_t a7, uint64_t a8) {
    const uint8_t *L = (const uint8_t *)layer;
    int32_t rgb = fx_stroke_color(L);
    if (rgb < 0)
        return ((fn_any8_t)g_hk_get.tramp)(out, layer, coord, in, a5, a6, a7, a8);
    const int32_t *c = (const int32_t *)coord;
    int lv = c[1], tx = c[2], ty = c[3];
    if (lv < 0 || lv >= 6) return ((fn_any8_t)g_hk_get.tramp)(out, layer, coord, in, a5, a6, a7, a8);
    const uint8_t *tg = *(const uint8_t *const *)(L + 0xf0 + lv * 8);
    const int32_t *b = (const int32_t *)(tg + 0x20);
    if (tx < b[0] || ty < b[1] || tx >= b[2] || ty >= b[3]) return in;
    const uint16_t *const *erow = (*(const uint16_t *const *const **)(tg + 0x10))[ty];
    const uint16_t *E = erow ? erow[tx] : NULL;
    if (!E) return in;
    stroke_paint((uint16_t *)out, (const uint16_t *)in, E, (uint32_t)rgb, *(const uint16_t *)(L + 0x84));
    return out;
}

// 圖層內容變動：(layer, grid, rect{x0,y0,x1,y1}（單一磚塊內）, ctx) → 回傳效果磚塊
static uint64_t fx_update(uint64_t layer, uint64_t grid, uint64_t rect, uint64_t ctx,
                          uint64_t a5, uint64_t a6, uint64_t a7, uint64_t a8) {
    uint64_t E = ((fn_any8_t)g_hk_update.tramp)(layer, grid, rect, ctx, a5, a6, a7, a8);
    const uint8_t *L = (const uint8_t *)layer;
    if (!E || fx_stroke_color(L) < 0) return E;
    const int32_t *rc = (const int32_t *)rect;
    int tx = rc[0] >> 5, ty = rc[1] >> 5;
    int uni = 0;
    const uint16_t *center = layer_tile_at((const uint8_t *)grid, tx, ty, &uni);
    if (!center) { memset((void *)E, 0, 2048); return E; }
    int w = *(const int32_t *)(L + 0x258) * 2;     // 水彩邊緣寬度 1..15 → 筆畫 2..30px
    if (w < 1) w = 1;
    if (w > STK_MARGIN) w = STK_MARGIN;
    float *g = (float *)HeapAlloc(GetProcessHeap(), 0, STK_WIN * STK_WIN * sizeof(float));
    if (!g) return E;
    __try {
        stroke_coverage((const uint8_t *)grid, tx, ty, center, uni, (float)w, g, (uint16_t *)E);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        if (InterlockedIncrement(&g_fx_fault) <= 4)
            mod_log("fx stroke: fault at tile (%d,%d) code=%08lx", tx, ty, GetExceptionCode());
    }
    HeapFree(GetProcessHeap(), 0, g);
    return E;
}

// 設定圖層名稱（0x10b340(layer, name, 編號)）：改名命令、Ctrl+Z / Ctrl+Y 還原名稱都會經過這裡。
// 筆畫標記一變（加上、換色、拿掉），效果磚塊就得照新狀態重算 → 請介面執行緒做
static uint64_t fx_set_name(uint64_t layer, uint64_t name, uint64_t num, uint64_t a4,
                            uint64_t a5, uint64_t a6, uint64_t a7, uint64_t a8) {
    const uint8_t *L = (const uint8_t *)layer;
    int32_t before = L ? fx_stroke_color(L) : -1;
    uint64_t r = ((fn_any8_t)g_hk_name.tramp)(layer, name, num, a4, a5, a6, a7, a8);
    if (L && g_main_hwnd && fx_stroke_color(L) != before)
        PostMessageW(g_main_hwnd, WM_SAI2MOD_FXREFRESH, (WPARAM)*(const uint32_t *)(L + 0x200), 0);
    return r;
}

// 目前圖層（doc+0x228）
static uint8_t *current_layer(void) {
    if (!g_off || g_off->ver_type != 2026) return NULL;
    uint8_t *doc = *(uint8_t **)(g_base + g_off->rva_active_doc);
    if (!doc || !mem_readable(doc + 0x228, 8)) return NULL;
    uint8_t *layer = *(uint8_t **)(doc + 0x228);
    return (layer && mem_rw(layer + 0x240, 0x40)) ? layer : NULL;
}

static void fx_log_name(const char *tag, const wchar_t *n) {
    char u8[400];
    WideCharToMultiByte(CP_UTF8, 0, n, -1, u8, sizeof(u8), NULL, NULL);
    mod_log("%s「%s」", tag, u8);
}

// 讓 SAI2 重算圖層效果並重畫畫布：照抄「效果參數滑桿」套用時的流程（0xfcc0）
//   0x113190(doc, layer, 0, 0) 重算效果磚塊 → 0x10b0d0(doc, layer) → 0xf6e30(doc) → 0x5cac0(doc)
// 這些要在文件執行緒上跑（跟其他命令依序），不能在介面執行緒直接呼叫，否則會跟正在執行的
// 命令搶著改圖層 → 畫布磚塊錯亂。所以包成工作交給 0xd3e0（沒有復原：第 2、3 個回呼給 0），
// 回呼收到的工作物件：+0x60 = doc、+0x68 = 我們給的資料（圖層 id）
typedef void (*fx_fn1_t)(void *);
static uint64_t fx_refresh_job(uint8_t *job) {
    uint8_t *doc = *(uint8_t **)(job + 0x60);
    const uint32_t *arg = *(const uint32_t **)(job + 0x68);
    uint32_t id = arg[0], full = arg[1];
    typedef uint8_t *(*fn_find_t)(void *, uint32_t);
    typedef void (*fn4_t)(void *, void *, uint64_t, uint64_t);
    typedef void (*fn2_t)(void *, void *);
    __try {
        uint8_t *layer = ((fn_find_t)(g_base + 0x532b0))(doc, id);     // 依 id 找圖層（已刪除的回傳 0）
        if (!layer) return 0;
        if (full) ((fn4_t)(g_base + 0x113190))(doc, layer, 0, 0);
        ((fn2_t)(g_base + 0x10b0d0))(doc, layer);
        ((fx_fn1_t)(g_base + 0xf6e30))(doc);
        ((fx_fn1_t)(g_base + 0x5cac0))(doc);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        mod_log("fx tag: 重畫失敗 code=%08lx", GetExceptionCode());
    }
    return 0;
}

static void fx_refresh_layer_id(uint32_t id, int full) {
    uint8_t *doc = *(uint8_t **)(g_base + g_off->rva_active_doc);
    if (!doc || !id) return;
    typedef int (*fn_submit_t)(void *, void *, void *, void *, void *);
    uint32_t arg[2] = { id, (uint32_t)full };
    __try {
        int r = ((fn_submit_t)(g_base + 0xd3e0))((void *)fx_refresh_job, NULL, NULL, doc, arg);
        if (full) mod_log("fx tag: 重畫圖層 id=%u -> %d", id, r);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        mod_log("fx tag: 送出重畫工作失敗 code=%08lx", GetExceptionCode());
    }
}

// 拿掉名稱裡所有 [#RRGGBB] 標記（含前面一個空白）：src → dst（dst 至少 FX_NAME_MAX+1 字）
static void fx_name_strip(wchar_t *dst, const wchar_t *src) {
    int r = 0, w = 0;
    while (src[r] && w < FX_NAME_MAX) {
        if (fx_tag_at(src, r) >= 0) {
            if (w > 0 && dst[w - 1] == L' ') w--;
            r += 9;
            continue;
        }
        dst[w++] = src[r++];
    }
    dst[w] = 0;
}

// 用 SAI2 圖層屬性對話框（0x71cf0）按確定時的同一個命令改名，會進復原紀錄、也會更新圖層清單：
//   參數 0x270 bytes：+0 圖層 id、+4 圖層類型(+0x204)、+8 要改的項目（bit0 = 名稱）、+0x6a 名稱
//   0xd3e0(套用 0x704f0, 0xd780, 0xd6a0, doc, 參數) 交給文件執行緒執行並等待
static int fx_set_layer_name(uint8_t *L, const wchar_t *name) {
    uint8_t *doc = *(uint8_t **)(g_base + g_off->rva_active_doc);
    if (!doc) return 0;
    __declspec(align(16)) uint8_t prm[0x270];
    memset(prm, 0, sizeof(prm));
    *(uint32_t *)(prm + 0) = *(const uint32_t *)(L + 0x200);
    *(uint32_t *)(prm + 4) = *(const uint32_t *)(L + 0x204);
    *(uint32_t *)(prm + 8) = 1;
    lstrcpynW((wchar_t *)(prm + 0x6a), name, FX_NAME_MAX + 1);
    typedef int (*fn_submit_t)(void *, void *, void *, void *, void *);
    int r = -1;
    __try {
        r = ((fn_submit_t)(g_base + 0xd3e0))((void *)(g_base + 0x704f0), (void *)(g_base + 0xd780),
                                             (void *)(g_base + 0xd6a0), doc, prm);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        mod_log("fx tag: 改名命令失敗 code=%08lx", GetExceptionCode());
        return 0;
    }
    return r >= 0;
}

// 把圖層名稱的筆畫標記設成 rgb（rgb < 0 = 拿掉），走可復原的改名命令
// 記住筆畫顏色：每個圖層各自一份（本次執行期間），另外記「最近一次」並寫回 ini 給下次啟動用
typedef struct { uint32_t id; int32_t rgb; } FxColorMem;
static FxColorMem g_fx_mem[128];
static int g_fx_mem_next = 0;

static void fx_remember_color(const uint8_t *L, int32_t rgb) {
    if (rgb < 0) return;
    uint32_t id = *(const uint32_t *)(L + 0x200);
    int slot = -1;
    for (int i = 0; i < 128; i++) if (g_fx_mem[i].id == id) { slot = i; break; }
    if (slot < 0) { slot = g_fx_mem_next; g_fx_mem_next = (g_fx_mem_next + 1) & 127; }
    g_fx_mem[slot].id = id;
    g_fx_mem[slot].rgb = rgb;
    if ((uint32_t)rgb != g_cfg_fx_rgb) {
        g_cfg_fx_rgb = (uint32_t)rgb;
        WCHAR v[16];
        swprintf_s(v, 16, L"%06x", (uint32_t)rgb);
        WritePrivateProfileStringW(L"FiltersMod", L"fx_stroke_color", v, g_ini_path);
    }
}

static uint32_t fx_recall_color(const uint8_t *L) {
    uint32_t id = *(const uint32_t *)(L + 0x200);
    for (int i = 0; i < 128; i++) if (g_fx_mem[i].id == id && id) return (uint32_t)g_fx_mem[i].rgb;
    return g_cfg_fx_rgb;
}

static int fx_apply_color(uint8_t *L, int32_t rgb) {
    fx_remember_color(L, rgb >= 0 ? rgb : fx_name_color(L));     // 拿掉前先記下原本的顏色
    const wchar_t *n = *(const wchar_t *const *)(L + 0x278);
    wchar_t name[FX_NAME_MAX + 1];
    fx_name_strip(name, n ? n : L"");
    if (rgb >= 0) {
        int len = lstrlenW(name);
        if (len > FX_NAME_MAX - 10) len = FX_NAME_MAX - 10;      // 留 " [#RRGGBB]"
        swprintf_s(name + len, FX_NAME_MAX + 1 - len, len ? L" [#%06x]" : L"[#%06x]", (uint32_t)rgb);
    }
    int ok = fx_set_layer_name(L, name);
    fx_log_name(ok ? "fx tag: 改名為" : "fx tag: 改名失敗，目標", name);
    return ok;
}

#define FX_EFFECT_STROKE   4
#define RVA_FX_LIST        0x49cd50
#define RVA_FX_CACHE       0x47a8d0
#define RVA_FX_PANEL       0x47a4b0
#define RVA_FX_PANEL_ROOT  0x47a4d8
#define RVA_FX_BUSY        0x47a180

static const uint32_t k_fx_lbl[3] = { STR_FX_R_LBL, STR_FX_G_LBL, STR_FX_B_LBL };
static const uint32_t k_fx_ctl[3] = { STR_FX_R_CTL, STR_FX_G_CTL, STR_FX_B_CTL };
static int g_fx_group_built = 0, g_fx_item_added = 0;
static uint64_t g_fx_fringe_grp = 0;
static uint8_t *g_fx_grp = NULL;          // 我們的群組物件：[+0xd1] = 顯示旗標

static uint64_t fx_set_effect(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);
static uint64_t fx_group_create(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);
static uint64_t fx_panel_refresh(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);
static uint64_t fx_panel_event(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);

// 0x103a0 / 0x287550 很短而且開頭有相對跳躍 / 呼叫，不搬原指令：整個用 detour 重寫
static InlineHook g_hk_seteff  = { 0x103a0,  20, "4885c97429895424104883ec28833dcc9d460000", (void *)fx_set_effect };
static InlineHook g_hk_group   = { 0x287550, 17, "4883ec38c744242001000000e82fffffff",       (void *)fx_group_create };
static InlineHook g_hk_refresh = { 0x195710, 15, "48895c2408488974241048897c2418",           (void *)fx_panel_refresh };
static InlineHook g_hk_event   = { 0x185510, 14, "4883ec284c8b15bd4c2f004d85d2",             (void *)fx_panel_event };

// 原本的 0x103a0：doc 有效且沒在忙 → 0xd7c0(0x10180, doc, &值)
static void fx_orig_set_effect(uint8_t *doc, int32_t v) {
    if (!doc || *(const int32_t *)(g_base + RVA_FX_BUSY)) return;
    typedef void (*fn_t)(void *, void *, void *);
    ((fn_t)(g_base + 0xd7c0))((void *)(g_base + 0x10180), doc, &v);
}

static uint64_t fx_set_effect(uint64_t doc_, uint64_t val, uint64_t a3, uint64_t a4,
                              uint64_t a5, uint64_t a6, uint64_t a7, uint64_t a8) {
    uint8_t *doc = (uint8_t *)doc_;
    int32_t v = (int32_t)val;
    uint8_t *L = g_cfg_fx_stroke ? current_layer() : NULL;
    if (!L) {
        if (v != FX_EFFECT_STROKE) fx_orig_set_effect(doc, v);
        return 0;
    }
    int32_t eff = *(const int32_t *)(L + 0x254);
    int stroke = eff == FX_EFFECT_FRINGE && fx_name_color(L) >= 0;
    mod_log("fx panel: 選擇效果 %d（目前 %d%s）", v, eff, stroke ? "，筆畫" : "");
    if (v == FX_EFFECT_STROKE) {
        if (eff != FX_EFFECT_FRINGE) fx_orig_set_effect(doc, FX_EFFECT_FRINGE);
        if (!stroke) fx_apply_color(L, (int32_t)fx_recall_color(L));
        return 0;
    }
    if (!(stroke && v == FX_EFFECT_FRINGE)) fx_orig_set_effect(doc, v);
    if (stroke) fx_apply_color(L, -1);
    return 0;
}

typedef uint64_t (*fn12_t)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t,
                           uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);

static void fx_build_group(uint64_t cont) {
    uint8_t *B = (uint8_t *)g_base;
    uint64_t grp = ((fn12_t)(B + 0x287490))(cont, 0, 0x1001, STR_FX_GROUP, 1, 0, 0, 0, 0, 0, 0, 0);
    if (!grp) return;
    g_fx_grp = (uint8_t *)grp;
    g_fx_grp[0xd1] = 0;
    ((fn12_t)(B + 0x287440))(grp, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    ((fn12_t)(B + 0x287470))(grp, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    uint64_t grid = ((fn12_t)(B + 0x2848e0))(grp, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    ((fn12_t)(B + 0x2849f0))(grid, 1, 0x200, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    ((fn12_t)(B + 0x2849f0))(grid, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    ((fn12_t)(B + 0x284a10))(grid, 1, 0x32, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    for (int i = 0; i < 3; i++) {
        uint64_t row = ((fn12_t)(B + 0x287590))(grp, grid, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
        ((fn12_t)(B + 0x287b40))(row, 1, 0, k_fx_lbl[i], 0, 0, 0, 0, 0, 0, 0, 0);
        ((fn12_t)(B + 0x288f40))(row, 2, 0x10001, k_fx_ctl[i], 0, 0, 0, 0x50, 0x80030006, 0, 0, 255);
    }
    g_fx_group_built = 1;
}

static uint64_t fx_group_create(uint64_t cont, uint64_t a2, uint64_t flags, uint64_t id,
                                uint64_t a5, uint64_t a6, uint64_t a7, uint64_t a8) {
    uint64_t g = ((fn12_t)(g_base + 0x287490))(cont, a2, flags, id, 1, 0, 0, 0, 0, 0, 0, 0);
    if ((uint32_t)id == 0x20280) g_fx_fringe_grp = g;
    // 色彩二值化群組（0x20285）建立時，水彩邊緣群組的列已經加完 → 接在它們下面
    if ((uint32_t)id == 0x20285 && g_fx_fringe_grp && g_cfg_fx_stroke && !g_fx_group_built) {
        __try {
            fx_build_group(g_fx_fringe_grp);
            mod_log("fx panel: 筆畫群組已建立");
        } __except (EXCEPTION_EXECUTE_HANDLER) {
            mod_log("fx panel: 建立群組失敗 code=%08lx", GetExceptionCode());
        }
    }
    return g;
}

static void *fx_find_ctrl(void *panel, uint32_t id) {
    typedef void *(*fn_t)(void *, uint32_t);
    return ((fn_t)(g_base + 0x256140))(panel, id);
}

static void fx_panel_sync(void) {
    void *panel = *(void **)(g_base + RVA_FX_PANEL);
    void *root  = *(void **)(g_base + RVA_FX_PANEL_ROOT);
    if (!panel || !root) return;
    if (!g_fx_item_added) {
        void *list = *(void **)(g_base + RVA_FX_LIST);
        if (list) {
            typedef void (*fn_t)(void *, uint32_t, uint32_t, uint32_t);
            ((fn_t)(g_base + 0x256df0))(list, 2, FX_EFFECT_STROKE, STR_FX_TITLE);
            g_fx_item_added = 1;
            mod_log("fx panel: 效果清單加入「筆畫」");
        }
    }
    if (!g_fx_group_built) return;
    uint8_t *L = current_layer();
    int32_t rgb = L ? fx_stroke_color(L) : -1;
    typedef void (*fn_set_t)(void *, uint32_t, uint32_t);
    // 0x2864c0 用 id 找不到巢狀在水彩邊緣群組裡的我們 → 直接寫顯示旗標；
    // 有變才照刷新函式結尾的流程重新排版：0x28b470(0x242800(panel), -1, -1)
    uint8_t show = rgb >= 0;
    if (g_fx_grp && g_fx_grp[0xd1] != show) {
        g_fx_grp[0xd1] = show;
        typedef void *(*fn_win_t)(void *);
        typedef void (*fn_lay_t)(void *, int32_t, int32_t);
        void *w = ((fn_win_t)(g_base + 0x242800))(panel);
        if (w) ((fn_lay_t)(g_base + 0x28b470))(w, -1, -1);
    }
    if (rgb < 0) return;
    void *combo = fx_find_ctrl(panel, 0x2027f);
    if (combo) ((fn_set_t)(g_base + 0x171c30))(combo, STR_FX_TITLE, 0);
    *(int32_t *)(g_base + RVA_FX_CACHE) = FX_EFFECT_STROKE;
    for (int i = 0; i < 3; i++) {
        void *c = fx_find_ctrl(panel, k_fx_ctl[i]);
        if (c) ((fn_set_t)(g_base + 0x2c85c0))(c, (rgb >> (16 - 8 * i)) & 0xff, 0);
    }
}

static uint64_t fx_panel_refresh(uint64_t a1, uint64_t a2, uint64_t a3, uint64_t a4,
                                 uint64_t a5, uint64_t a6, uint64_t a7, uint64_t a8) {
    uint64_t r = ((fn_any8_t)g_hk_refresh.tramp)(a1, a2, a3, a4, a5, a6, a7, a8);
    __try {
        fx_panel_sync();
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        mod_log("fx panel: 刷新失敗 code=%08lx", GetExceptionCode());
    }
    return r;
}

static uint64_t fx_panel_event(uint64_t a1, uint64_t id, uint64_t evt, uint64_t a4,
                               uint64_t a5, uint64_t a6, uint64_t a7, uint64_t a8) {
    int ch = -1;
    for (int i = 0; i < 3; i++) if ((uint32_t)id == k_fx_ctl[i]) ch = i;
    if (ch < 0) return ((fn_any8_t)g_hk_event.tramp)(a1, id, evt, a4, a5, a6, a7, a8);
    uint32_t e = (uint32_t)evt;
    if (e < 0x544 || e > 0x546 || !a5) return 0;
    uint8_t *L = current_layer();
    if (!L) return 0;
    int32_t cur = fx_stroke_color(L);
    if (cur < 0) return 0;
    int v = *(const int32_t *)(a5 + 0xc8);
    v = v < 0 ? 0 : (v > 255 ? 255 : v);
    int sh = 16 - 8 * ch;
    int32_t rgb = (cur & ~(0xff << sh)) | (v << sh);
    if (e != 0x546) {
        if (rgb != cur) {
            g_fx_preview_layer = L;
            g_fx_preview_rgb = rgb;
            fx_refresh_layer_id(*(const uint32_t *)(L + 0x200), 0);
        }
        return 0;
    }
    g_fx_preview_rgb = -1;
    g_fx_preview_layer = NULL;
    if (rgb != fx_name_color(L)) fx_apply_color(L, rgb);
    return 0;
}

// 0x185510 開頭的 mov r10, [rip+x] 不能照搬：改成 mov r10, imm64 ; mov r10, [r10]
static int fx_build_event_tramp(void) {
    uint8_t *t = (uint8_t *)(g_base + 0x185510);
    if (!hex_eq(t, g_hk_event.expect_hex, 14)) return 0;
    uint8_t *tr = (uint8_t *)VirtualAlloc(NULL, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!tr) return 0;
    uint64_t abs = (uint64_t)(t + 11) + *(const int32_t *)(t + 7);       // RIP 相對位址的目標
    uint8_t *q = tr;
    memcpy(q, t, 4); q += 4;                                             // sub rsp, 0x28
    *q++ = 0x49; *q++ = 0xBA; *(uint64_t *)q = abs; q += 8;             // mov r10, imm64
    *q++ = 0x4D; *q++ = 0x8B; *q++ = 0x12;                               // mov r10, [r10]
    memcpy(q, t + 11, 3); q += 3;                                        // test r10, r10
    write_absjmp(q, (uint64_t)(t + 14));                                 // 接回原函式（旗標不受 jmp 影響）
    g_hk_event.tramp = tr;
    g_hk_event.own_tramp = 1;
    return 1;
}

// SAI2 有 6 處「字串 id → 文字」查詢：slot = (id >> 16) & 3，表 = ctx ? ctx->slots[slot] : 全域[slot]。
// 新開的視窗（下拉選單彈出清單、建面板當下）的 ctx 沒有我們放的 slot 0 → 文字空白。
// 每處把 `mov R, [B + rax*8 + 0x90]`（8 bytes）換成 call 到小段程式：
//   R = [B + rax*8 + 0x90]; if (!R) R = 全域[rax]; ret
// 原本 slot 0 SAI2 沒用，所以只影響我們的字串；SAI2 自己的 slot 2 在 ctx 裡本來就有。
typedef struct { uintptr_t rva; uint8_t reg; } FxStrSite;      // reg：0..7 的暫存器編號
static const FxStrSite k_fx_str_sites[] = {
    { 0x23cd75, 1 }, { 0x23cdca, 2 }, { 0x23ce1a, 2 }, { 0x23d20c, 1 }, { 0x24e38d, 7 }, { 0x24e3dc, 2 },
};

static uint8_t *fx_alloc_near(uintptr_t base) {
    for (uintptr_t a = (base & ~(uintptr_t)0xffff) - 0x10000; a > base - 0x70000000; a -= 0x10000) {
        void *p = VirtualAlloc((void *)a, 0x1000, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
        if (p) return (uint8_t *)p;
    }
    return NULL;
}

static int fx_patch_string_lookup(void) {
    uint8_t *stubs = fx_alloc_near(g_base);
    if (!stubs) return 0;
    uint64_t glob = (uint64_t)(g_base + g_off->rva_glob_str_tbl);
    int ok = 0;
    for (size_t i = 0; i < sizeof(k_fx_str_sites) / sizeof(k_fx_str_sites[0]); i++) {
        uint8_t *site = (uint8_t *)(g_base + k_fx_str_sites[i].rva);
        uint8_t r = k_fx_str_sites[i].reg;
        // 驗證：48 8B (r<<3|4) SIB(rax*8 + base) 90 00 00 00
        if (site[0] != 0x48 || site[1] != 0x8B || site[2] != (uint8_t)(0x84 | (r << 3)) ||
            (site[3] & 0xF8) != 0xC0 || *(const uint32_t *)(site + 4) != 0x90) {
            mod_log("fx str: +%llx 位元組不符，跳過", (unsigned long long)k_fx_str_sites[i].rva);
            continue;
        }
        uint8_t *q = stubs + i * 32;
        memcpy(q, site, 8); q += 8;                                         // mov R, [B+rax*8+0x90]
        *q++ = 0x48; *q++ = 0x85; *q++ = (uint8_t)(0xC0 | (r << 3) | r);   // test R, R
        *q++ = 0x75; *q++ = 14;                                             // jnz → ret
        *q++ = 0x48; *q++ = (uint8_t)(0xB8 + r); *(uint64_t *)q = glob; q += 8;   // mov R, imm64
        *q++ = 0x48; *q++ = 0x8B; *q++ = (uint8_t)(0x04 | (r << 3)); *q++ = (uint8_t)(0xC0 | r);  // mov R, [R+rax*8]
        *q++ = 0xC3;                                                        // ret
        int64_t rel = (int64_t)(stubs + i * 32) - (int64_t)(site + 5);
        if (rel != (int32_t)rel) continue;
        uint8_t patch[8] = { 0xE8, 0, 0, 0, 0, 0x90, 0x90, 0x90 };
        *(int32_t *)(patch + 1) = (int32_t)rel;
        DWORD old;
        if (!VirtualProtect(site, 8, PAGE_EXECUTE_READWRITE, &old)) continue;
        memcpy(site, patch, 8);
        VirtualProtect(site, 8, old, &old);
        FlushInstructionCache(GetCurrentProcess(), site, 8);
        ok++;
    }
    return ok;
}

static void fx_stroke_install(void) {
    if (!g_cfg_fx_stroke || !g_off || g_off->ver_type != 2026) return;
    InlineHook *hooks[] = { &g_hk_update, &g_hk_get, &g_hk_name, &g_hk_group, &g_hk_seteff, &g_hk_refresh, &g_hk_event };
    for (size_t i = 0; i < sizeof(hooks) / sizeof(hooks[0]); i++) {
        if (!hex_eq((const uint8_t *)(g_base + hooks[i]->rva), hooks[i]->expect_hex, hooks[i]->len)) {
            mod_log("fx stroke: +%llx 開頭位元組不符，筆畫效果停用", (unsigned long long)hooks[i]->rva);
            return;
        }
    }
    // 字串表提早放進全域 slot 0：面板建構當下的標籤就查得到
    ((void **)(g_base + g_off->rva_glob_str_tbl))[0] = g_mod_strings;
    int sp = fx_patch_string_lookup();
    if (!fx_build_event_tramp()) { mod_log("fx stroke: 事件 trampoline 建立失敗，筆畫效果停用"); return; }
    int ok = 0;
    for (size_t i = 0; i < sizeof(hooks) / sizeof(hooks[0]); i++) ok += hook_install(hooks[i]);
    mod_log("fx stroke: %d/7 hook(s) installed, string lookup patched %d/6", ok, sp);
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
    if (m == WM_SAI2MOD_FXREFRESH) {
        fx_refresh_layer_id((uint32_t)w, 1);
        __try { fx_panel_sync(); } __except (EXCEPTION_EXECUTE_HANDLER) {}
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
    WCHAR *ini_path = g_ini_path;
    GetModuleFileNameW(NULL, ini_path, MAX_PATH);
    WCHAR *slash = ini_path + lstrlenW(ini_path);
    while (slash > ini_path && slash[-1] != L'\\' && slash[-1] != L'/') slash--;
    lstrcpyW(slash, L"sai2_filters_mod.ini");

    g_cfg_enabled   = GetPrivateProfileIntW(L"FiltersMod", L"enabled",   1, ini_path);
    g_cfg_binarize  = GetPrivateProfileIntW(L"FiltersMod", L"binarize",  1, ini_path);
    g_cfg_posterize = GetPrivateProfileIntW(L"FiltersMod", L"posterize", 1, ini_path);
    g_cfg_pixelate  = GetPrivateProfileIntW(L"FiltersMod", L"pixelate",  1, ini_path);
    g_cfg_sharpen   = GetPrivateProfileIntW(L"FiltersMod", L"sharpen",   1, ini_path);
    g_cfg_fx_stroke = GetPrivateProfileIntW(L"FiltersMod", L"fx_stroke", 1, ini_path);
    g_cfg_debug     = GetPrivateProfileIntW(L"FiltersMod", L"debug",     0, ini_path);
    WCHAR col[16];
    GetPrivateProfileStringW(L"FiltersMod", L"fx_stroke_color", L"000000", col, 16, ini_path);
    g_cfg_fx_rgb = (uint32_t)wcstoul(col[0] == L'#' ? col + 1 : col, NULL, 16) & 0xffffff;
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
    if (!g_cfg_enabled || (!g_cfg_binarize && !g_cfg_posterize && !g_cfg_pixelate && !g_cfg_sharpen &&
                           !g_cfg_fx_stroke)) {
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

    // 要趕在圖層面板建好之前掛上（面板在主視窗出現前就可能建好）
    fx_stroke_install();

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
