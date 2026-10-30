@echo off
rem 先切到 UTF-8 再重新執行自己：在檔案中途切換字碼頁，cmd 讀後面的中文行會錯位
if not "%DC2_UTF8%"=="1" (
    chcp 65001 >nul
    set DC2_UTF8=1
    cmd /c ""%~f0" %*"
    exit /b
)
rem 從別的資料夾執行時，也以本檔所在的專案資料夾為準
cd /d "%~dp0"
echo ============================================
echo  DrawCompanion 2.0 - 編譯 EXE
echo  （1.x 請用 build.bat；兩個 exe 可以並存，共用同一份紀錄）
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [錯誤] 找不到 python 指令。請確認已安裝 Python 3.10+ 並且已勾選「Add Python to PATH」。
    pause
    exit /b 1
)

echo [1/3] 正在安裝/更新必要的 Python 套件...
python -m pip install -r requirements2.txt pyinstaller
if errorlevel 1 (
    echo [錯誤] pip 安裝套件失敗。
    pause
    exit /b 1
)

echo.
echo [2/3] 正在進行打包編譯（設定在 DrawCompanion2.spec）...
python -m PyInstaller --noconfirm --clean --workpath build\v2 --distpath dist DrawCompanion2.spec
if errorlevel 1 (
    echo [錯誤] PyInstaller 編譯失敗。
    pause
    exit /b 1
)

echo.
echo [3/3] 正在複製語言檔與更新輸出檔...
xcopy /E /I /Y locales dist\locales >nul
xcopy /E /I /Y native\sai2mod dist\native\sai2mod >nul
copy /Y dist\DrawCompanion2.exe . >nul

echo.
echo ============================================
echo  編譯成功！
echo  根目錄：DrawCompanion2.exe
echo  dist 目錄：dist\DrawCompanion2.exe
echo  放在 1.x 的 SAI2_DrawCompanion.exe 旁邊，就會讀寫同一份紀錄。
echo ============================================
echo.
if not "%1"=="--no-pause" pause
