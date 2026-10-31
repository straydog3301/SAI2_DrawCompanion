# SAI2 DrawCompanion 2.0 🎨

**PaintTool SAI Ver.2 的桌面小夥伴**：在 SAI2 旁邊安靜地陪你畫畫，自動記錄每張作品畫了多久、每天排好練習任務，速寫和臨摹的參考圖用小窗開著，不占你的畫布。

**介紹網頁：<https://straydog3301.github.io/SAI2_DrawCompanion/>**　·　**下載：[v2.0.0-beta.7](https://github.com/straydog3301/SAI2_DrawCompanion/releases/tag/v2.0.0-beta.7)**　·　**回饋：[填寫表單](https://docs.google.com/forms/d/e/1FAIpQLSdmVgbIjduOo64vnu7S4OUdu1t54_-3mCNL4WLYcpwTzY8taw/viewform)**

> 目前是 2.0 測試版。1.x（Tk 版）已停止維護與測試，舊版仍可從 [v1.7.0](https://github.com/straydog3301/SAI2_DrawCompanion/releases/tag/v1.7.0) 下載。

---

## 開始使用

1. 下載 `DrawCompanion2.exe`（約 35 MB），放在任何資料夾
2. 雙擊執行：桌面出現寵物「墨墨」就完成了
3. 打開 SAI2 開始畫；其他設定都有預設值，用到時才會提醒你

- 需要 Windows 10／11（64 位元）與 PaintTool SAI Ver.2；免安裝，不需要 Python
- 第一次執行時 Windows 可能顯示「Windows 已保護您的電腦」：按「其他資訊 → 仍要執行」。這是因為程式沒有購買數位簽章，不是偵測到病毒（[說明](https://straydog3301.github.io/SAI2_DrawCompanion/#smartscreen)）
- 縮時錄影要合成影片時才需要 [ffmpeg](https://ffmpeg.org/)（加入 PATH）
- 紀錄、設定、縮圖與影片都存在程式所在的資料夾，不會上傳

---

## 功能

### 桌面寵物 × 快捷面板
- 平常只有一隻可以拖曳的寵物，依 SAI2 的狀態切換動作；動筆時自動變半透明
- 點一下打開快捷面板：今日進度、每日任務（開始、繼續、打卡）、最近開啟的作品縮圖、快捷按鈕
- 寵物下方顯示本次動筆時間與錄影開關；畫太久會提醒休息

### 自動記錄動筆時間
- 偵測 SAI2 目前畫的檔案，只計算真正下筆的時間，不用按開始或停止
- 未存檔的新畫布預設不記錄；可以設定「不記錄的資料夾」（例如「下載」）

### 每日任務與課程
- 依每日練習時間與想加強的技能排出速寫、臨摹研究、反覆練習；可以換一個或手動加入，每週可以請假
- **課程**：7 條學習路徑，每堂課有目標、分段步驟、常見錯誤與完成檢查；參考圖取自美術館的公有領域作品、Unsplash／Pexels 或本機圖庫
- **AI 評鑑（可關閉）**：課程打卡時，把課程目標、參考圖與你的畫布交給你自己的 AI 評 1～5 分並附簡評，分數決定是否進入下一課；不同意可以改分數。支援 Google AI Studio（Gemini，有每日免費額度）與 OpenAI 相容服務（OpenAI、OpenRouter、本機 Ollama／LM Studio）。金鑰只存在本機

### 參考小窗（速寫、臨摹）
- 速寫：本機圖庫或線上圖庫自動換圖，**下筆時才倒數**；開始時自動建立一輪共用的畫布（預設 A4 橫向）
- 臨摹研究：步驟、灰階、明度分階、主色、構圖線；**按住快捷鍵把你的畫布疊上參考圖比對**
- 穿透模式：小窗半透明、滑鼠點得穿，疊在畫布上照著畫；可以縮成膠囊

### 成長與作品
- 練習月曆、連續天數、動筆統計（週／月／半年／一年）、技能卡與等級
- 作品清單附**自動擷取的縮圖**（存檔、停筆時；只截取畫紙），可以合併另存的檔案、批次刪除紀錄
- 打卡時存一張畫布快照，回頭看自己的進步

### 縮時錄影
- 只在動筆時擷取，**只錄畫紙**（去掉 SAI2 的外框、捲軸與工作區；暗色、白色系與放大、旋轉都適用）
- 畫哪個作品就錄哪個，每個作品各自一部；關閉 SAI2（或所有檔案）時合成，也可以在「工具」頁現在就合成
- 畫面大小改變時等比例補邊、不變形；程式當機或斷電留下的錄影，下次啟動時可以合成

### 客製化
- 自訂角色（各狀態可用 PNG／GIF／APNG／WebP 動畫）、對話泡泡外觀（單張圖九宮格）、主題色與深淺色
- 「如果…就…」規則（一條規則可以有多個動作）、快捷面板的區塊與按鈕、全域快捷鍵
- 設定與角色可以匯出分享（不含金鑰與本機路徑）

### 預設快捷鍵

| 快捷鍵 | 功能 |
|---|---|
| `Ctrl + Alt + D` | 打開／關閉快捷面板 |
| `Ctrl + Alt + H` | 顯示／隱藏寵物 |
| `Ctrl + Alt + R` | 顯示／隱藏參考小窗 |
| `Ctrl + Alt + X` | 參考小窗穿透模式 |
| `Ctrl + Alt + C`（按住） | 把我的畫布疊上參考圖比對 |
| `Ctrl + Alt + N` | 速寫：下一張 |
| `Ctrl + Alt + P` | 速寫：暫停／繼續 |

都可以在「設定 › 快捷鍵」修改或清除。

### 不提供的功能
- **筆刷工坊、液化**：SAI2 2026-07-02 版起內建素材登錄（筆刷形狀、散布、筆刷紋理、紙張材質）與格子／網格變形，請直接使用 SAI2 的功能
- 介面目前只有繁體中文

---

## 回報問題
- 填寫 [回饋表單](https://docs.google.com/forms/d/e/1FAIpQLSdmVgbIjduOo64vnu7S4OUdu1t54_-3mCNL4WLYcpwTzY8taw/viewform)，或開 [GitHub Issue](https://github.com/straydog3301/SAI2_DrawCompanion/issues/new)
- 需要時可以在「設定 › 一般 › 關於與問題回報」匯出診斷資訊（不含 API 金鑰、本機路徑與作品檔名）

---

## 開發

```bash
pip install -r requirements2.txt
python drawcompanion2.py --data-dir <測試用資料夾>    # 加上 --data-dir 就不會讀寫正式紀錄
python tests/run_tests.py                            # 核心 + 介面測試（介面測試會開視窗）
build2.bat                                           # 打包成 DrawCompanion2.exe（專案根目錄與 dist/）
```

- 架構：`core/` 是不依賴介面的邏輯，`ui2/` 是 PySide6 介面；見 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 更新紀錄：[CHANGELOG.md](CHANGELOG.md)；之後的計劃：[docs/ROADMAP.md](docs/ROADMAP.md)；發布前測試：[docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)
- 1.x 的原始碼（`main.py` 等）仍保留在儲存庫中，但已停止維護與測試

---

## 授權條款
目前儲存庫尚未附上授權檔（`LICENSE`），因此在加入之前，原始碼依著作權法預設保留所有權利。歡迎下載使用與回報問題；若想修改或再發布原始碼，請先開 [Issue](https://github.com/straydog3301/SAI2_DrawCompanion/issues) 與作者聯繫。

PaintTool SAI 是 SYSTEMAX 的產品；本工具為個人開發的非官方輔助程式。
