@echo off
set "LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\SAI2_DrawCompanion_Watcher.lnk"

if exist "%LINK%" (
    del "%LINK%"
    echo w}۰ʱҰʱ|C
) else (
    echo 䤣Ұʱ|Ai|]wΤwC
)

echo.
echo bIʵBz{...
wmic process where "CommandLine like '%%watcher.pyw%%'" call terminate >nul 2>&1
echo IʵBz{ǤwC
echo.
pause
