@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ============================================================
echo   JARVIS - volledige diagnose
echo ============================================================
echo.
echo Dit controleert je hele installatie en verandert niets.
echo Er wordt niets gekocht of verkocht.
echo.

set "PROBLEMEN=0"

REM ===============================================================
REM 1. Windows
REM ===============================================================
echo [1/6] Windows...
for /f "tokens=*" %%v in ('ver') do echo       %%v
echo.

REM ===============================================================
REM 2. Python in de projectomgeving
REM ===============================================================
echo [2/6] Python-omgeving...
if not exist ".venv\Scripts\python.exe" (
    echo       [FOUT] De map .venv ontbreekt.
    echo              Dubbelklik op INSTALLEREN-WINDOWS.bat.
    set /a PROBLEMEN+=1
    goto SAMENVATTING
)
set "VENV_PY=%CD%\.venv\Scripts\python.exe"
"%VENV_PY%" tools\check_python.py
if errorlevel 1 (
    echo       [FOUT] De Python-versie is niet geschikt.
    set /a PROBLEMEN+=1
)
echo.

REM ===============================================================
REM 3. Systeemcontrole
REM ===============================================================
echo [3/6] Systeemcontrole...
echo.
"%VENV_PY%" -m bot.health_check
set "HEALTH=!errorlevel!"
if "!HEALTH!"=="1" set /a PROBLEMEN+=1
echo.

REM ===============================================================
REM 4. Draait JARVIS op dit moment?
REM ===============================================================
echo [4/6] Draaiende processen...
"%VENV_PY%" -m tools.jarvis_control status
echo.

REM ===============================================================
REM 5. Poorten
REM ===============================================================
echo [5/6] Poorten...
call :POORT 8000 dashboard
call :POORT 8770 achtergronddienst
echo.

REM ===============================================================
REM 6. Testsuite
REM ===============================================================
echo [6/6] Zelftest van de installatie...
echo       Dit duurt ongeveer een minuut.
echo.
"%VENV_PY%" -m pytest -q tests\test_windows_compatibility.py tests\test_health_check.py tests\test_resilience.py tests\test_supervisor.py tests\test_chrome_extension.py control_service\tests
if errorlevel 1 (
    echo.
    echo       [FOUT] De zelftest is niet volledig geslaagd.
    set /a PROBLEMEN+=1
) else (
    echo.
    echo       [OK] De zelftest is geslaagd.
)
echo.

:SAMENVATTING
echo ============================================================
if "!PROBLEMEN!"=="0" (
    echo   DIAGNOSE AFGEROND - GEEN PROBLEMEN GEVONDEN
    echo.
    echo   Start JARVIS met:  START-JARVIS.bat
) else (
    echo   DIAGNOSE AFGEROND - !PROBLEMEN! PUNT^(EN^) OM NAAR TE KIJKEN
    echo.
    echo   Hierboven staat per onderdeel wat er aan de hand is en
    echo   wat je eraan kunt doen.
    echo.
    echo   Logbestanden staan in de map:  logs
)
echo ============================================================
echo.
pause
exit /b !PROBLEMEN!


:POORT
REM %1 = poortnummer, %2 = omschrijving
netstat -ano | findstr /r /c:"LISTENING" | findstr /c:":%~1 " >nul 2>&1
if errorlevel 1 (
    echo       [vrij]   poort %~1 ^(%~2^) - er luistert niets
) else (
    echo       [bezet]  poort %~1 ^(%~2^) - er luistert een programma
)
goto :eof
