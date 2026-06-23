@echo off
echo ============================================
echo  SAI øϭp - ]w}۰ʱҰ
echo ============================================
echo.
echo }NuSAI øϭp ʵv[J Windows }ҰʡC
echo PaintTool SAI @}ҡApɾN|۰ʥX{FɡApɾ۰xsC
echo.

:: o watcher.pyw |
set "WATCHER=%~dp0watcher.pyw"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LINK=%STARTUP_DIR%\SAI2_DrawCompanion_Watcher.lnk"

::  pythonw.exe
for /f "delims=" %%i in ('where pythonw.exe 2^>nul') do set "PYTHONW=%%i"
if "%PYTHONW%"=="" (
    for /f "delims=" %%i in ('where python.exe 2^>nul') do set "PYTHONW=%%i"
)
if "%PYTHONW%"=="" (
    echo [~] 䤣 PythonAнT{ Python wTw˨å[J PATH
    pause
    exit /b 1
)

echo ϥ PythonG%PYTHONW%
echo ʵ|G%WATCHER%
echo.

::  PowerShell إ߱|
powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell;" ^
    "$s = $ws.CreateShortcut('%LINK%');" ^
    "$s.TargetPath = '%PYTHONW%';" ^
    "$s.Arguments = '\"%WATCHER%\"';" ^
    "$s.WorkingDirectory = '%~dp0';" ^
    "$s.Description = 'SAI øϭp ʵ';" ^
    "$s.Save();"

if errorlevel 1 (
    echo [~] إ߱|
    pause
    exit /b 1
)

echo ============================================
echo  ]wI
echo.
echo  U}εnJAʵ|bI۰ʰC
echo  } PaintTool SAI ɡApɾN۰ʥX{C
echo.
echo  Yn۰ʱҰʡAа remove_startup.bat
echo ============================================
echo.
pause
