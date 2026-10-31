# sai2mod — SAI2 原生濾鏡擴充模組

把「濾鏡 → 效果」子選單（二值化、色調分離、像素化、銳化）注入 SAI2 原生選單，
對接 SAI2 內部濾鏡引擎：原生對話框、16-bit 即時預覽、寫入圖層、支援 Ctrl+Z 復原。
另在圖層面板「特殊效果」下拉選單加入「筆畫」圖層效果（僅 SAI2 2026 版，見下方）。

由 `mscms.dll` 代理 DLL 載入（2026 版 `sai2.exe` 靜態匯入 `mscms.dll`），在 `DllMain` 起工作執行緒
掛主視窗 `WndProc` 並注入選單。開關由 SAI2 資料夾的 `sai2_filters_mod.ini` 控制（下次啟動生效）。

> 代理 DLL 名稱固定為 `mscms.dll`。舊版另外產出的 `dwmapi.dll` 會與漢化模組（同樣用 `dwmapi.dll`
> 代理）衝突並跳出警告，已移除；DrawCompanion 同步時會刪掉自己舊放的 `dwmapi.dll`
> （以檔案內含 `sai2_filters_mod.ini` 字串判斷，其他模組的同名檔案不會動）。
> 2023 版 `sai2.exe` 沒有匯入 `mscms.dll`，因此不會載入本模組。

## 檔案

| 檔案 | 用途 |
|---|---|
| `sai2mod.c` | 模組本體（選單注入、對話框、濾鏡像素處理、筆畫圖層效果、字串表） |
| `mscms.def` | 代理 DLL 的匯出轉發表（轉回 System32 原版） |
| `gen_def.py` | 從 System32 的 DLL 產生 `.def`（`python gen_def.py mscms`） |
| `def2pragma.py` | 把 `.def` 轉成 MSVC `/export` pragma（`build.bat` 用 `/FI` 引入） |
| `build.bat` | 用 Visual Studio 的 x64 C 編譯器編出 `mscms.dll`（靜態連結 CRT） |

## 編譯

安裝 Visual Studio（含 x64 C 編譯器）後：

```bat
native\sai2mod\build.bat
```

產出 `mscms.dll`。DrawCompanion 打包時會把它內嵌進 exe（見 `DrawCompanion2.spec`）。

## ⚠️ 版本綁定：SAI2 更新後要加新的 profile

模組內所有 SAI2 內部位址（函式、全域變數的 RVA）都是**依 SAI2 的 PE TimeDateStamp**
硬編碼在 `sai2mod.c` 的 `k_profiles[]`。**timestamp 認不得就不注入**（選單不出現），
避免套用錯位址讓 SAI2 當掉。所以 SAI2 一改版，就要重新產生 offset、加一組 profile。

### 重新產生 offset 的流程

逆向工具在 `tools/`（`sai_disasm.py` 反組譯、`sai_xref.py` 交叉參照；需 `pip install capstone pefile`），以新版 `sai2.exe` 為對象：

1. **timestamp**：`python -c "import pefile;print(hex(pefile.PE('sai2.exe').FILE_HEADER.TimeDateStamp))"`
2. **選單 / 指令 ID**（`menu_id_filter`、`menu_id_flt_color`、`cmd_id_lumcon`）：沿用舊版附近值，
   或在 `.rsrc` / 選單字串附近比對。
3. **字串表 `rva_glob_str_tbl`**：找「亮度對比」等內建濾鏡字串，回溯讀取它的查找函式所用的全域表。
   查找函式會 `GetPropW(hwnd,"SYSTEMAX-WININFO")` → 讀 `wininfo+0x30`(2026)/`+0x38`(2023) 當 context，
   再取 `context+0x90+slot*8`；UI 字串 ID 的 `(id>>16)&3` 選 slot（SAI2 用 slot 2，本模組用 slot 0）。
4. **濾鏡註冊 / 執行**（`rva_reg_filter`、`rva_run_filter`）：找內建濾鏡字串
   （`adjustment.bricon`、`blur.gauss` 等，在 `.rdata`）的參照，那附近就是 `reg_filter` 呼叫。
5. **配置 / UI 建構 / 預覽函式**：對照 `bricon`（逐點）與 `blur.gauss`（空間）兩個內建濾鏡的描述子，
   逐一比對本模組用到的 `rva_*`。
6. **事件碼與欄位位移**（`ev_slider_begin`、`ev_checkbox_click`、`slider_val_off`、`rva_default_ctx`）：
   在滑桿回呼附近觀察。
7. 把一整組填進 `k_profiles[]` 新增一筆，`timestamp` 設為步驟 1 的值，重新編譯。

## 濾鏡引擎備忘

- **逐點引擎**：一次給固定 **32×32 磚塊**（count=1024）、多執行緒、**無座標、無鄰域餘裕**。
  二值化、色調分離、像素化、銳化都走這條。像素化用 32 的因數所以無接縫；銳化是磚塊內
  3×3 近似，強度高時磚塊邊界可能有淡接縫。
- **空間引擎**（高斯模糊）：階層式磚塊畫布（mip、32/256 對齊），真正的鄰域濾鏡走這條，
  但結構複雜，本模組未使用。要做無接縫的鄰域效果（銳化無縫版、內外光暈、浮雕）需對接它。

## 筆畫圖層效果（2026 版）

圖層面板「特殊效果」下拉選單多一項「筆畫」：沿圖形內側描邊，寬度 2～30 像素、強度、紅綠藍顏色，
畫圖時即時更新，切換與調色都進 SAI2 的 Ctrl+Z。

- **存法**：沿用 SAI2 的「水彩邊緣」效果（`layer+0x254 == 1`），在圖層名稱尾端加 `[#RRGGBB]` 標記
  來區分「筆畫」與顏色。寬度 = 水彩邊緣寬度 ×2，強度 = `layer+0x84`。所以檔案存檔後在沒裝模組的
  SAI2 打開，會顯示成水彩邊緣、名稱帶色碼，不會壞檔。
- **繪製**：inline hook `0x10cd20`（更新效果磚塊 → 寫入覆蓋率）與 `0x10e470`（取磚塊 → 上色）。
- **名稱標記**：改名一律走 SAI2 可復原的圖層屬性指令（`0xd3e0` 文件執行緒工作），不就地改寫字串；
  hook `0x10b340`（改名）在顏色變動時通知主視窗重新整理。重新整理也必須排進文件執行緒，
  不然會跟 SAI2 自己的工作搶磚塊、畫面破圖。
- **面板**：下拉選單項目由 `0x256df0` 加入效果清單；RGB 滑桿群組巢狀在水彩邊緣群組裡，
  顯示旗標 `[grp+0xd1]` + 重新排版；顏色依圖層記住（執行期間），最近一次用的顏色寫回 ini 的
  `fx_stroke_color`。
- **字串**：SAI2 每個視窗的字串 context 沒有 slot 0，模組修補六處查表指令，查不到時退回全域表。
- **安全**：所有 hook 點先比對開頭位元組，有一處不符就整個效果不裝（濾鏡選單照常）。

## ini 設定

`[FiltersMod]`：`enabled`、`binarize` / `posterize` / `pixelate` / `sharpen`、`fx_stroke`（1 開 0 關，預設開）、
`fx_stroke_color`（模組自己寫回的最近筆畫顏色，6 碼十六進位）、`debug`。

## 除錯

`sai2_filters_mod.ini` 的 `[FiltersMod] debug=1` 會在 SAI2 資料夾寫 `sai2mod.log`
（字串表裝入數量、對話框建立、像素回呼參數、筆畫 hook 安裝結果等）。預設關閉。
