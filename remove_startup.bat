@echo off
chcp 950 >nul
echo ============================================
echo  SAI2 繪圖助手 - 移除開機自動啟動
echo ============================================
echo.

set "LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\SAI2_DrawCompanion_Watcher.lnk"

if exist "%LINK%" (
    del "%LINK%"
    echo 已成功移除開機自動啟動捷徑。
) else (
    echo 找不到啟動捷徑，可能之前已經移除或尚未設定。
)

echo.
echo 正在關閉背景監控進程...
wmic process where "CommandLine like '%%watcher.pyw%%'" call terminate >nul 2>&1
echo 背景監視器已成功關閉。
echo.
pause
