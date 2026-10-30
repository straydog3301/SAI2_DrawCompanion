@echo off
rem 先切到 UTF-8 再重新執行自己（同 build2.bat）
if not "%DC2_UTF8%"=="1" (
    chcp 65001 >nul
    set DC2_UTF8=1
    cmd /c ""%~f0" %*"
    exit /b
)
rem 編譯 SAI2 濾鏡擴充模組：mscms.dll（2026 版）與 dwmapi.dll（2023.07.11 版）
rem 需要 Visual Studio 的 x64 C 編譯器；靜態連結 C 執行階段（/MT），SAI2 資料夾不需要額外的執行階段 DLL
setlocal
cd /d "%~dp0"
set VCVARS=
for %%v in (2022 2019 2017) do (
    for %%e in (Community Professional Enterprise BuildTools) do (
        if not defined VCVARS if exist "%ProgramFiles%\Microsoft Visual Studio\%%v\%%e\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%ProgramFiles%\Microsoft Visual Studio\%%v\%%e\VC\Auxiliary\Build\vcvars64.bat"
        if not defined VCVARS if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\%%v\%%e\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%ProgramFiles(x86)%\Microsoft Visual Studio\%%v\%%e\VC\Auxiliary\Build\vcvars64.bat"
    )
)
if not defined VCVARS (
    echo [錯誤] 找不到 Visual Studio 的 vcvars64.bat
    exit /b 1
)
call "%VCVARS%" >nul
for %%p in (mscms dwmapi) do (
    python def2pragma.py %%p >nul || exit /b 1
    cl /nologo /O2 /MT /utf-8 /W3 /LD /FI%%p_exports.h sai2mod.c /Fo%%p.obj /link /OUT:%%p.dll user32.lib kernel32.lib || exit /b 1
    del /q %%p.obj %%p.exp %%p.lib %%p_exports.h 2>nul
)
echo 完成：mscms.dll、dwmapi.dll
