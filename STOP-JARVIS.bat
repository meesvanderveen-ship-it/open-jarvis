@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ============================================================
echo   JARVIS stoppen
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo   JARVIS is hier niet geinstalleerd.
    echo   Er valt dus ook niets te stoppen.
    echo.
    pause
    exit /b 1
)
set "VENV_PY=%CD%\.venv\Scripts\python.exe"

REM De bot krijgt een net stopverzoek en mag een lopende handelscyclus
REM afmaken. Hard afbreken zou halve orderadministratie kunnen achterlaten.
echo Stopverzoek versturen...
echo.
"%VENV_PY%" -m tools.jarvis_control stop
set "BOT_CODE=!errorlevel!"

REM De achtergronddienst voor de Chrome Extension draait in een eigen venster.
REM Die stopt niet vanzelf mee, dus die sluiten we hier expliciet af.
echo Achtergronddienst stoppen...
taskkill /fi "WINDOWTITLE eq JARVIS achtergronddienst*" /t >nul 2>&1
taskkill /fi "WINDOWTITLE eq JARVIS dashboard*" /t >nul 2>&1

echo.
echo ============================================================
if "!BOT_CODE!"=="0" (
    echo   JARVIS IS GESTOPT
    echo.
    echo   Er wordt niet meer gehandeld. Starten kan weer met
    echo   START-JARVIS.bat
) else (
    echo   JARVIS REAGEERT NOG NIET
    echo.
    echo   Het stopverzoek staat klaar en blijft staan. De bot maakt
    echo   waarschijnlijk een lopende handelscyclus af.
    echo.
    echo   Wacht een minuut en start dit bestand daarna nog een keer.
    echo   Kijk zo nodig in:  logs\supervisor.log
)
echo ============================================================
echo.
pause
exit /b !BOT_CODE!
