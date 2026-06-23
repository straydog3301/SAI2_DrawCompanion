@echo off
echo ============================================
echo  SAI2 Draw Timer - Build EXE
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+
    exit /b 1
)

echo [1/3] Installing Python packages...
pip install -r requirements.txt
if errorlevel 1 ( echo [ERROR] pip install failed & exit /b 1 )

echo.
echo [2/3] Installing PyInstaller...
pip install pyinstaller
if errorlevel 1 ( echo [ERROR] PyInstaller install failed & exit /b 1 )

echo.
echo [3/3] Compiling...
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
    echo [ERROR] Build failed
    exit /b 1
)

echo [4/4] Copying locales directory to dist...
xcopy /E /I /Y locales dist\locales

echo.
echo ============================================
echo  Completed! Executable: dist\SAI2_DrawCompanion.exe
echo ============================================
