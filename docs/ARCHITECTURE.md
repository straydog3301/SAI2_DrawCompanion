# 架構：核心邏輯與介面分層（為 2.0 換介面框架做準備）

## 分層

| 位置 | 內容 | 規則 |
|---|---|---|
| `core/` | 不含介面的核心邏輯 | **不得 import tkinter / ImageTk 或任何介面模組**；2.0 換框架時直接沿用 |
| 根目錄 `*.py` | Tk 介面（1.x） | 只透過 `core/` 的公開函式與類別讀寫資料；2.0 會整個重寫 |

### core/
| 模組 | 用途 |
|---|---|
| `paths.py` | 程式資料目錄 `APP_DIR`（打包 / 原始碼執行的唯一規則來源） |
| `i18n.py` | 語系載入與 `_tr()` |
| `tracker.py` | SAI2 繪圖時間追蹤（含每日任務用的動筆計數器） |
| `timelapse.py` | 縮時錄影：SAI2 視窗尋找、GDI 擷取、編碼 |
| `sai2_win.py` | SAI2 視窗相關的 Win32 小工具 |
| `brush_assets.py` | SAI2 筆刷 / 紋理 / 紙張素材與自訂工具的讀寫、影像轉換、待寫入佇列 |
| `daily_quests.py` | 每日任務、平衡課表、學習路徑進度、練習紀錄 |
| `study_lessons.py` | 臨摹研究課程與學習路徑（純資料） |
| `study_refs.py` | 參考圖來源（美術館開放典藏、照片圖庫、本機） |
| `growth.py` | 成長統計（技能卡、里程碑、月曆、單日明細），唯讀 |
| `snapshots.py` | SAI2 畫布擷取（裁掉工作區）與打卡快照縮圖 |
| `psd_writer.py` | 產生空白 PSD 練習畫布 |

### 介面（Tk，1.x）
`main.py`（主視窗、速寫視窗、設定）、`study_window.py`、`brush_studio.py`、`liquify_helper.py`、
`growth_view.py`（成長頁籤）、`quest_manager_window.py`（任務與技能管理）、`ui_kit.py`（DPI 縮放換算、依內容決定視窗大小、捲動容器）。

## 資料相容
所有資料檔都在 `APP_DIR`，2.0 直接讀取同一批檔案，使用者紀錄不需轉換：
`sai2_draw_time.json`、`sai2_timer_settings.json`、`daily_quests.json`（含 `schema` 版本號）、`checkin_snapshots/`、
`brush_studio_settings.json`、`sai2_pending_brushes.json`、`study_refs_cache/`、`sai2_settings_backup/`。

## 測試
`python tests/run_tests.py`（`--core` 只跑核心、`--network` 加跑連網測試），說明見 [tests/README.md](../tests/README.md)。
`tests/core/test_core_misc.py` 會自動確認 `core/` 每個模組都不依賴 Tk。

## 驗證 core 沒有依賴 Tk
```python
import sys, importlib
for m in ('tkinter', 'tkinter.ttk', 'PIL.ImageTk', '_tkinter'):
    sys.modules[m] = None   # 任何 core 模組 import Tk 都會失敗
for m in ('core.paths', 'core.sai2_win', 'core.i18n', 'core.tracker', 'core.timelapse',
          'core.brush_assets', 'core.daily_quests', 'core.growth', 'core.snapshots', 'core.study_lessons',
          'core.study_refs', 'core.psd_writer'):
    importlib.import_module(m)
```

## 2.0 前的待辦
- 2.0 開工前先以新框架做技術驗證：精簡模式透明懸浮與強制置頂、全域快捷鍵與前景視窗監聽、液化編輯器即時筆刷、研究視窗比對畫布。
- 1.x 的新功能（第 3、4 階段）以「核心邏輯放 `core/` 並附測試、介面只做簡單版本」的方式開發。
- `main.py` 內的設定讀寫（`_load_settings` / `_save_settings`）與速寫網址池邏輯，之後移入 `core/`。
