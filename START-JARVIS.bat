@echo off
setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ============================================================
echo   JARVIS starten
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo   De bot is nog niet geinstalleerd.
    echo   Dubbelklik eerst op INSTALLEREN-WINDOWS.bat
    echo.
    pause
    exit /b 1
)
set "VENV_PY=%CD%\.venv\Scripts\python.exe"

REM ---------------------------------------------------------------
REM Eerst controleren of de sleutels kloppen -- anders start er niets
REM ---------------------------------------------------------------
echo Sleutels controleren...
echo.
"%VENV_PY%" -m tools.setup_wizard --check
if errorlevel 1 (
    echo.
    echo ------------------------------------------------------------
    echo   JARVIS is nog niet startklaar.
    echo   Hierboven staat wat er mist.
    echo.
    echo   Herstel dit met:  INSTALLEREN-WINDOWS.bat
    echo ------------------------------------------------------------
    echo.
    pause
    exit /b 1
)

echo.
echo ------------------------------------------------------------
echo   Alles staat goed. JARVIS start nu.
echo.
echo   Er openen twee zwarte vensters. Laat ze allebei open staan;
echo   sluiten betekent stoppen.
echo.
echo   Het dashboard komt vanzelf in je browser op:
echo     http://127.0.0.1:8000
echo ------------------------------------------------------------
echo.

REM Beide processen krijgen een eigen venster. Hier staat bewust het
REM relatieve pad .venv\Scripts\python.exe: dat bevat zelf geen spaties, ook
REM niet als de projectmap in bijvoorbeeld "Mijn Documenten" staat, zodat de
REM aanhalingstekens van cmd /k niet in de knoop raken.
start "JARVIS dashboard" cmd /k ".venv\Scripts\python.exe -m dashboard.backend.run"
start "JARVIS bot" cmd /k ".venv\Scripts\python.exe run_trader_loop.py"

REM Even wachten tot de webserver luistert, dan de browser openen
timeout /t 6 /nobreak >nul
start "" http://127.0.0.1:8000

echo Klaar. Dit venster mag je sluiten.
echo.
pause
