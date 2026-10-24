# 階段 0：技術驗證（PySide6）

對應 [docs/UI_2.0_PLAN.md](../../docs/UI_2.0_PLAN.md) §3 的六項。驗證程式只用來證明「做得到」，2.0 正式開發時會重寫，但其中的 `core/` 模組會直接沿用。

| 檔案 | 內容 |
|---|---|
| `core/single_instance.py` | 具名 Mutex 單一實例（正式模組，附測試） |
| `core/sai2_launcher.py` | SAI2 開檔統一流程（正式模組，附測試 `tests/core/test_v2_launch.py`） |
| `winutil.py` | 置頂、滑鼠穿透、Z 順序、全域快捷鍵、前景視窗監聽 |
| `pet.py` | 寵物視窗、影格解碼、測試角色產生 |
| `refwin.py` | 參考小窗（停留浮出工具列、穿透、按住比對） |
| `app.py` | 可手動操作的整合版（寵物＋小窗＋快捷鍵＋單一實例＋系統匣） |
| `selftest.py` | 自動驗證（20 項） |
| `sai2_probe.py` | 在真的 SAI2 上測開檔流程（會開啟 SAI2 與測試畫布） |

需要 `pip install PySide6==6.8.1`（尚未加入 requirements.txt，正式開工時再加）。

## 結果（Windows 11、150% 縮放、PySide6 6.8.1、Python 3.12）

| # | 項目 | 結果 | 數據 / 備註 |
|---|---|---|---|
| 1 | 寵物：逐像素透明 | 通過 | 透明像素點擊會落到下方程式，不透明像素由寵物接收 |
| 1 | 寵物：拖曳 / 點擊判斷、位置記憶、拉回螢幕 | 通過 | 移動 < 4 px 算點擊；位置依螢幕記錄 |
| 1 | 寵物：置頂自我修復 | 通過 | 被其他置頂視窗蓋住後，`SetWindowPos(HWND_TOPMOST)` 可回到最上層且不搶焦點 |
| 1 | 寵物：動畫效能 | 通過 | 24 fps APNG 實測 23.0 fps；256 px、60 fps 精靈圖 56～58 fps，約一個核心的 10%；記憶體 79 MB |
| 1 | 影格解碼 | 通過 | APNG / GIF / WebP / 精靈圖各 24 格，載入 0.1～0.16 秒；**GIF 確認沒有半透明邊緣**，APNG / WebP 有 |
| 2 | 參考小窗穿透 | 通過 | 開啟後點擊落到下方程式，關閉後恢復 |
| 3 | 單一實例 | 通過 | 第二份把參數交給第一份後 0.4 秒內結束，第一份收到 `--open` 參數 |
| 4 | SAI2 開檔流程 | 通過 | 真的 SAI2（Ver.2 64bit Preview.2023.07.11）：SAI2 未開啟時先單獨啟動、就緒後交檔，檔案開在該視窗；已開啟時 **cmdline 與 drop 兩種交檔都在 0.3 秒內開檔、沒有多出第二個 SAI2**。預設採 drop（不需另開行程，SAI2 已開啟時也不必知道執行檔路徑）。流程另有 10 種情境以假 SAI2 測試 |
| 5 | 全域快捷鍵、前景視窗監聽 | 通過 | `RegisterHotKey` 綁隱藏原生視窗＋Qt 原生事件過濾器；`EVENT_SYSTEM_FOREGROUND` 事件即時收到 |
| 6 | 按住比對 | 通過 | 按住期間顯示比對、放開即恢復；真的 SAI2 畫布擷取（`capture_sai2_canvas`）修正裁切後正確得到 800×600 畫布 |

## 開發時要注意的發現
1. **高 DPI 座標**：Qt 用邏輯座標、Win32 用實體像素（150% 時差 1.5 倍）。凡是把座標交給 Win32（`WindowFromPoint`、`SetWindowPos` 指定位置、擷取範圍），都要乘上 `devicePixelRatio`；儲存位置一律用 Qt 邏輯座標。
2. **動畫計時器要用 `Qt.PreciseTimer`**：預設精度約 16 ms，42 ms 一格會被拉長成 47 ms（24 fps 掉到 20.7 fps）。
3. **快捷鍵會和 1.x 衝突**：測試時 1.x 正在執行，`Ctrl+Alt+T` 已被 1.x 佔用。2.0 期間使用者仍會為了筆刷工坊、液化同時開 1.x，所以 2.0 的預設快捷鍵要避開 1.x 的組合，並在設定中顯示「已被佔用」。
4. 1.x 打包成單一 exe 時，工作管理員會看到兩個 `SAI2_DrawCompanion.exe`（啟動器＋本體），這是正常的，不是重複開啟；判斷是否多開要以 Mutex 為準。
5. **SAI2 標題顯示的是路徑**：開啟暫存資料夾的檔案時，標題是「…Preview.2023.07.11 - Artist / AppData / Local / Temp / … / 檔名.psd」。開檔確認只比對最後一段；1.x 的 `tracker.extract_filename` 會把它記成「Artist _ AppData _ … _ 檔名.psd」，2.0 的作品紀錄要再檢查這個命名方式。
6. **畫布擷取裁切修正（1.x 也受影響）**：SAI2 畫布視窗有深色外框與顏色接近工作區的捲軸，原本的 `trim_workspace` 以左上角（外框）為背景色，結果整張都沒裁到（3098×1905）。已改為以出現最多的顏色當工作區、先排除四邊最內側的整條線（外框、捲軸邊線）再找畫布，並補上模擬外框與捲軸的測試。這個修正在 `core/snapshots.py`，1.x 的研究比對與打卡快照合併後也會一起變好。
7. 寵物與小窗都是 `Qt.Tool` 視窗，不會出現在工作列；程式入口只有系統匣圖示與寵物。

## 執行
```
python spikes/v2_stage0/selftest.py
python spikes/v2_stage0/app.py
python spikes/v2_stage0/sai2_probe.py --exe E:\SAI2\sai2.exe --capture
```
