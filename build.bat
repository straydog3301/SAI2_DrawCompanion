@echo off
chcp 950 >nul
echo ============================================
echo  SAI2 繪圖助手 - 編譯 EXE (v1.2.0)
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 python 指令。請確認已安裝 Python 3.10+ 並且已勾選「Add Python to PATH」。
    pause
    exit /b 1
)

echo [1/4] 正在安裝/更新必要的 Python 套件...
pip install -r requirements.txt
if errorlevel 1 (
    echo [錯誤] pip 安裝套件失敗。
    pause
    exit /b 1
)

echo.
echo [2/4] 正在安裝/更新 PyInstaller...
pip install pyinstaller
if errorlevel 1 (
    echo [錯誤] 安裝 PyInstaller 失敗。
    pause
    exit /b 1
)

echo.
echo [3/4] 正在進行打包編譯...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "SAI2_DrawCompanion" ^
    --add-data "locales;locales" ^
    --hidden-import "win32gui" ^
    --hidden-import "win32api" ^
    --hidden-import "win32con" ^
    --hidden-import "pywintypes" ^
    --hidden-import "PIL._tkinter_finder" ^
    main.py

if errorlevel 1 (
    echo [錯誤] PyInstaller 編譯失敗。
    pause
    exit /b 1
)

echo.
echo [4/4] 正在複製語言檔與更新輸出檔...
xcopy /E /I /Y locales dist\locales >nul
copy /Y dist\SAI2_DrawCompanion.exe . >nul

echo.
echo ============================================
echo  編譯成功！
echo  已將最新版執行檔輸出至專案根目錄與 dist 目錄下。
echo  根目錄：SAI2_DrawCompanion.exe
echo  dist 目錄：dist\SAI2_DrawCompanion.exe
echo ============================================
echo.
pause
