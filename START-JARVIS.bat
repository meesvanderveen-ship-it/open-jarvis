@echo off
setlocal enabledelayedexpansion
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

if not exist "dashboard\frontend\dist\index.html" (
    echo   Het dashboard is nog niet gebouwd.
    echo   Dubbelklik eerst op INSTALLEREN-WINDOWS.bat
    echo.
    pause
    exit /b 1
)

REM ===============================================================
REM Preflight: geen enkel proces starten met kapotte credentials
REM ===============================================================
echo Sleutels controleren...
echo.
"%VENV_PY%" -m tools.setup_wizard --check
set "PREFLIGHT=%errorlevel%"
if not "%PREFLIGHT%"=="0" (
    echo.
    echo ------------------------------------------------------------
    echo   JARVIS is nog niet startklaar.
    echo   Hierboven staat wat er mist.
    echo ------------------------------------------------------------
    echo.
    REM Meteen hier aanbieden in plaats van doorverwijzen naar een ander
    REM bestand: de sleutels invullen is precies wat er nu moet gebeuren,
    REM en dat is dezelfde wizard die INSTALLEREN-WINDOWS.bat zou starten.
    choice /c JN /n /m "Sleutels nu invullen? [J/N] "
    if errorlevel 2 (
        echo.
        echo   Goed. Start dit bestand opnieuw zodra de sleutels klaar zijn.
        echo.
        pause
        exit /b 1
    )
    echo.
    "%VENV_PY%" -m tools.setup_wizard
    echo.
    echo Sleutels opnieuw controleren...
    echo.
    "%VENV_PY%" -m tools.setup_wizard --check
    set "PREFLIGHT=%errorlevel%"
    if not "!PREFLIGHT!"=="0" (
        echo.
        echo ------------------------------------------------------------
        echo   Nog steeds niet startklaar. Hierboven staat waarom.
        echo ------------------------------------------------------------
        echo.
        pause
        exit /b 1
    )
)

echo.
echo ------------------------------------------------------------
echo   Alles staat goed. JARVIS start nu.
echo.
echo   Er openen twee zwarte vensters. Laat ze allebei open staan;
echo   sluiten betekent stoppen.
echo ------------------------------------------------------------
echo.

REM ===============================================================
REM Beide processen krijgen een eigen venster. Hier staat bewust het
REM relatieve pad .venv\Scripts\python.exe: dat bevat zelf geen spaties,
REM ook niet als de projectmap in bijvoorbeeld "Mijn Documenten" staat.
REM ===============================================================
echo Dashboard starten...
start "JARVIS dashboard" cmd /k ".venv\Scripts\python.exe -m dashboard.backend.run"

echo Bot starten...
start "JARVIS bot" cmd /k ".venv\Scripts\python.exe run_trader_loop.py"

REM ===============================================================
REM Wachten tot de webserver echt antwoordt. Een vaste wachttijd is
REM onbetrouwbaar: op een trage pc is 6 seconden te kort, en dan opent
REM de browser op een foutpagina.
REM ===============================================================
echo.
echo Wachten tot het dashboard antwoordt...
set "GEREED="
for /l %%i in (1,1,30) do (
    if not defined GEREED (
        "%VENV_PY%" -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2); sys.exit(0)" >nul 2>&1
        if !errorlevel! equ 0 (
            set "GEREED=1"
        ) else (
            timeout /t 1 /nobreak >nul
        )
    )
)

echo.
if defined GEREED (
    echo   Dashboard is bereikbaar. De browser wordt geopend.
    start "" http://127.0.0.1:8000
) else (
    echo   Het dashboard antwoordde niet binnen 30 seconden.
    echo.
    echo   Kijk in het venster "JARVIS dashboard" wat daar staat.
    echo   Een veelvoorkomende oorzaak is dat poort 8000 al bezet is.
    echo   Je kunt zelf proberen:  http://127.0.0.1:8000
)

echo.
echo Dit venster mag je sluiten. De twee andere niet.
echo.
pause
