@echo off
setlocal
title Bambuddy - Install Docker and Slicer Services

echo.
echo ============================================================
echo Bambuddy Docker and automatic slicing setup
echo ============================================================
echo.
echo This step installs Docker Desktop if needed, then downloads and
echo starts the OrcaSlicer and BambuStudio services.
echo Keep this window open and make sure the computer is connected to
echo the Internet. The first download can take several minutes.
echo.

set "INSTALL_DIR=%~dp0.."
set "DATA_ROOT=%ProgramData%\Bambuddy"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-slicer.ps1" -InstallDir "%INSTALL_DIR%" -DataRoot "%DATA_ROOT%" -Interactive
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if exist "%DATA_ROOT%\slicer\setup-status.txt" (
    echo Setup status:
    type "%DATA_ROOT%\slicer\setup-status.txt"
) else (
    echo No setup status file was created.
)
echo.
if not "%EXIT_CODE%"=="0" (
    echo Setup did not finish. Please send the message above for diagnosis.
) else (
    echo Setup command finished. Refresh Bambuddy and test automatic slicing.
)
echo.
pause
endlocal & exit /b %EXIT_CODE%
