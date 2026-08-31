@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ============================================================
echo   JARVIS herstarten
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo   JARVIS is nog niet geinstalleerd.
    echo   Dubbelklik eerst op INSTALLEREN-WINDOWS.bat
    echo.
    pause
    exit /b 1
)
set "VENV_PY=%CD%\.venv\Scripts\python.exe"

echo Stap 1 van 2: stoppen...
echo.
"%VENV_PY%" -m tools.jarvis_control stop
if errorlevel 1 (
    echo.
    echo ------------------------------------------------------------
    echo   JARVIS is nog niet gestopt, dus er wordt niets herstart.
    echo.
    echo   Twee bots tegelijk zouden dezelfde posities beheren, en dat
    echo   is precies wat er nooit mag gebeuren. Wacht een minuut en
    echo   probeer het opnieuw.
    echo ------------------------------------------------------------
    echo.
    pause
    exit /b 1
)

echo.
echo Stap 2 van 2: starten...
echo.
"%VENV_PY%" -m tools.jarvis_control start
set "CODE=!errorlevel!"

echo.
echo ============================================================
if "!CODE!"=="0" (
    echo   JARVIS IS HERSTART
    echo.
    echo   Het dashboard blijft bereikbaar op:
    echo     http://127.0.0.1:8000
) else (
    echo   HERSTARTEN IS NIET GELUKT
    echo.
    echo   Hierboven staat wat er misging.
    echo   Draai DIAGNOSE-JARVIS.bat voor een volledige controle.
)
echo ============================================================
echo.
pause
exit /b !CODE!
