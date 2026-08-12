@echo off
REM Prepare the active data directory for the clean production installer.
REM The first install deliberately starts with an empty database. If an older
REM Bambuddy installation is present, move its data aside instead of loading it
REM into the new product. Subsequent upgrades keep the user's production data.

setlocal
set "DATA_ROOT=%~1"
if "%DATA_ROOT%"=="" (
    echo [prepare-clean-data] missing data root
    exit /b 2
)

set "MARKER=%DATA_ROOT%\.fresh-install-complete"
set "DATA_DIR=%DATA_ROOT%\data"
if exist "%MARKER%" (
    echo [prepare-clean-data] existing installation marker found; preserving data
    exit /b 0
)

if not exist "%DATA_ROOT%" mkdir "%DATA_ROOT%"
if exist "%DATA_DIR%" (
    for /f "delims=" %%A in ('dir /b "%DATA_DIR%" 2^>nul') do set "HAS_DATA=1"
    if defined HAS_DATA (
        for /f "delims=" %%T in ('powershell.exe -NoProfile -Command "(Get-Date).ToString('yyyyMMdd-HHmmss')"') do set "STAMP=%%T"
        if not defined STAMP set "STAMP=previous"
        echo [prepare-clean-data] moving old data to %DATA_ROOT%\previous-data-%STAMP%
        move /Y "%DATA_DIR%" "%DATA_ROOT%\previous-data-%STAMP%" >nul
        if errorlevel 1 (
            echo [prepare-clean-data] could not move old data; refusing to start clean install
            exit /b 1
        )
    )
)

mkdir "%DATA_DIR%" 2>nul
>"%MARKER%" echo Bambuddy clean production install initialized on %DATE% %TIME%
echo [prepare-clean-data] empty production data directory ready
endlocal
exit /b 0
