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
| `single_instance.py` | 2.0：具名 Mutex 單一實例 |
| `sai2_launcher.py` | 2.0：在 SAI2 開檔的統一流程（先確認 / 啟動 SAI2，再以拖放交檔） |
| `settings2.py` | 2.0：設定檔 `drawcompanion2_settings.json`（第一次從 1.x 設定帶入共用值） |
| `hotkeys.py` | 2.0：快捷鍵字串解析、與 1.x 預設的衝突檢查 |
| `companion.py` | 2.0：常駐服務（追蹤、任務進度、最近開啟、1.x 執行中時暫停記錄） |
| `pet_pack.py` / `pet_builtin.py` | 2.0：寵物角色包（PNG / GIF / APNG / WebP / 精靈圖）、內建角色「墨墨」 |
| `pet_state.py` | 2.0：寵物狀態與休息提醒 |
| `file_paths.py` | 由追蹤紀錄的檔案 key 反推實際路徑（自 1.x main.py 移入） |
| `sketch_source.py` | 速寫圖源（本機 / Unsplash / Pexels 網址池）、倒數計張與歷史（自 1.x main.py 移入） |
| `study_tools.py` | 臨摹研究的影像工具、分段計時、練習畫布（自 1.x study_window.py 移入） |
| `stats.py` | 動筆時間統計圖資料（週／月／三個月／半年／一年／至今，自 1.x main.py 移入） |
| `works.py` | 作品清單：分組、排序、搜尋、影片資料夾、課程歷次紀錄 |
| `slots.py` | 2.0：快捷面板的區塊與快捷按鈕（內建動作、開啟檔案／資料夾、執行程式、開網址） |
| `rules.py` | 2.0：「如果…就…」規則引擎（固定的觸發條件與動作清單，一條規則可有多個動作；休息提醒、夜間睡覺也是規則） |
| `backup.py` | 2.0：整套設定、角色包與泡泡圖的匯出／匯入（不匯出本機路徑，金鑰預設不匯出） |
| `bubble_skin.py` | 2.0：對話泡泡的自訂外觀（單張圖＋文字範圍，九宮格延伸） |
| `onboarding.py` | 2.0：用到時才提醒（「30 秒調整你的練習」、使用 3 天後建議練習時間與開機啟動、第一部影片位置） |
| `data_text.py` | 2.0：內建技能／範本／練習方式／課程以 id 對應翻譯表（`locales/data_<語言>.json`；目前只有繁中） |
| `autostart.py` | 2.0：開機啟動（HKCU Run）、1.x 監視器捷徑偵測與移除 |

### 介面（Tk，1.x）
`main.py`（主視窗、速寫視窗、設定）、`study_window.py`、`brush_studio.py`、`liquify_helper.py`、
`growth_view.py`（成長頁籤）、`quest_manager_window.py`（任務與技能管理）、`ui_kit.py`（DPI 縮放換算、依內容決定視窗大小、捲動容器）。

### 介面（PySide6，2.0 開發中）
`drawcompanion2.py`（進入點）、`ui2/app.py`（常駐主程式、系統匣、單一實例交接）、`ui2/pet_window.py`、`ui2/bubble.py`（對話泡泡）、`ui2/bubble_editor.py`（圈選泡泡文字範圍）、
`ui2/quick_panel.py`（快捷面板與共用的任務清單 `QuestList`）、`ui2/ref_window.py`（參考小窗：研究 / 速寫、穿透、比對、膠囊、打卡側滑面板）、
`ui2/main_window.py`（主視窗：控制中心與設定合一，左側欄切換）、`ui2/pages_more.py`（成長、課程、作品、工具頁）、
`ui2/charts.py`（長條圖、走勢、月曆熱度）、`ui2/settings_pages.py`（設定頁：一般、寵物工作室、快捷面板、規則、外觀…）、
`ui2/quests_page.py`（每日任務課表、範本、技能管理）、`ui2/status_capsule.py`（寵物下方的計時與錄影開關）、
`ui2/widgets.py`（共用元件：開關、設定列、卡片、統計塊、步進器…）、`ui2/theme.py`（色票與樣式表、WCAG 對比檢查）、`ui2/a11y.py`（鍵盤焦點、報讀名稱）、`ui2/icons.py`、`ui2/winutil.py`。
相依套件見 `requirements2.txt`；開發時用 `python drawcompanion2.py --data-dir <暫存資料夾>`，不碰真正的紀錄。
打包用 `build2.bat`（設定在 `DrawCompanion2.spec`，只帶用到的 Qt 模組），輸出 `DrawCompanion2.exe`；放在 1.x 的 exe 旁邊即共用同一份紀錄。

## 資料相容
所有資料檔都在 `APP_DIR`，2.0 直接讀取同一批檔案，使用者紀錄不需轉換（1.x 執行中時 2.0 暫停記錄，避免兩邊同時寫入）：
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
- 介面規劃見 [UI_2.0_PLAN.md](UI_2.0_PLAN.md)（桌面寵物＋參考小窗、單一實例、開檔流程、分階段交付）。
- 2.0 開工前先以新框架做技術驗證：寵物透明視窗與拖曳、參考小窗穿透、單一實例、SAI2 開檔流程、全域快捷鍵與前景視窗監聽、畫布比對。
- 筆刷工坊（`brush_studio.py`、`core/brush_assets.py`）與液化（`liquify_helper.py`）仍有缺陷，2.0 不移植，程式碼只供 2.x 重新開發時參考。
- 1.x 的新功能（第 3、4 階段）以「核心邏輯放 `core/` 並附測試、介面只做簡單版本」的方式開發。
- `main.py` 內的設定讀寫（`_load_settings` / `_save_settings`）與速寫網址池邏輯，之後移入 `core/`。
