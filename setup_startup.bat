@echo off
chcp 950 >nul
echo ============================================
echo  SAI2 繪圖助手 - 設定開機自動啟動
echo ============================================
echo.
echo 將會在您的 Windows 啟動資料夾中建立捷徑。
echo 啟動後，當偵測到 PaintTool SAI 開啟時，本軟體將會自動啟動；
echo 當 PaintTool SAI 關閉時，本軟體也會自動儲存並關閉。
echo.

:: 偵測 watcher.pyw 的路徑
set "WATCHER=%~dp0watcher.pyw"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LINK=%STARTUP_DIR%\SAI2_DrawCompanion_Watcher.lnk"

:: 尋找 pythonw.exe
for /f "delims=" %%i in ('where pythonw.exe 2^>nul') do set "PYTHONW=%%i"
if "%PYTHONW%"=="" (
    for /f "delims=" %%i in ('where python.exe 2^>nul') do set "PYTHONW=%%i"
)
if "%PYTHONW%"=="" (
    echo [錯誤] 找不到 Python。請確認已安裝 Python 且已將其加入到系統的 PATH 中。
    pause
    exit /b 1
)

echo 使用 Python： %PYTHONW%
echo 監視器路徑： %WATCHER%
echo 建立捷徑： %LINK%
echo.

:: 使用 PowerShell 建立捷徑
powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell;" ^
    "$s = $ws.CreateShortcut('%LINK%');" ^
    "$s.TargetPath = '%PYTHONW%';" ^
    "$s.Arguments = '\"%WATCHER%\"';" ^
    "$s.WorkingDirectory = '%~dp0';" ^
    "$s.Description = 'SAI2 繪圖助手 啟動監視器';" ^
    "$s.Save();"

if errorlevel 1 (
    echo [錯誤] 建立捷徑失敗。
    pause
    exit /b 1
)

echo ============================================
echo  設定完成！
echo.
echo  下次您登入系統或啟動電腦時，該監視器將會自動在背景啟動。
echo  一旦您開啟 PaintTool SAI，計時助手也會自動被啟動。
echo.
echo  若想移除開機自動啟動，請執行 remove_startup.bat
echo ============================================
echo.
pause
