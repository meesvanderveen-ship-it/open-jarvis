@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ============================================================
echo   JARVIS Trading Bot - installatie
echo ============================================================
echo.
echo Dit duurt ongeveer 5 tot 10 minuten. Je hoeft niets te doen
echo tot er om je API-sleutels wordt gevraagd.
echo.

REM ---------------------------------------------------------------
REM 1. Is Python aanwezig?
REM ---------------------------------------------------------------
echo [1/5] Python controleren...
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo.
    echo   FOUT: Python is niet gevonden.
    echo.
    echo   Installeer Python via https://www.python.org/downloads/
    echo   Zet tijdens het installeren een vinkje bij
    echo   "Add python.exe to PATH" -- dat is belangrijk.
    echo.
    echo   Start dit bestand daarna opnieuw.
    echo.
    pause
    exit /b 1
)
%PY% --version
echo.

REM ---------------------------------------------------------------
REM 2. Is Node.js aanwezig? (nodig voor het dashboard)
REM ---------------------------------------------------------------
echo [2/5] Node.js controleren...
where npm >nul 2>&1
if errorlevel 1 (
    echo.
    echo   FOUT: Node.js is niet gevonden.
    echo.
    echo   Installeer Node.js via https://nodejs.org/
    echo   Kies de knop "LTS" en klik in de installer steeds op Next.
    echo.
    echo   Start dit bestand daarna opnieuw.
    echo.
    pause
    exit /b 1
)
call npm --version
echo.

REM ---------------------------------------------------------------
REM 3. Python-omgeving en pakketten
REM ---------------------------------------------------------------
echo [3/5] Python-omgeving klaarzetten...
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    if errorlevel 1 (
        echo   FOUT: kon de Python-omgeving niet aanmaken.
        pause
        exit /b 1
    )
)
set "VENV_PY=%CD%\.venv\Scripts\python.exe"

echo       Pakketten installeren, even geduld...
"%VENV_PY%" -m pip install --upgrade pip --quiet
"%VENV_PY%" -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo   FOUT: installeren van de Python-pakketten is mislukt.
    pause
    exit /b 1
)
REM Het dashboard heeft een eigen lijst (fastapi, uvicorn); zonder deze
REM stap start de webserver niet.
"%VENV_PY%" -m pip install -r dashboard\backend\requirements.txt --quiet
if errorlevel 1 (
    echo   FOUT: installeren van de dashboard-pakketten is mislukt.
    pause
    exit /b 1
)
echo       Klaar.
echo.

REM ---------------------------------------------------------------
REM 4. Dashboard bouwen
REM ---------------------------------------------------------------
echo [4/5] Dashboard bouwen...
pushd dashboard\frontend
call npm install --silent
if errorlevel 1 (
    echo   FOUT: npm install is mislukt.
    popd
    pause
    exit /b 1
)
call npm run build
if errorlevel 1 (
    echo   FOUT: het bouwen van het dashboard is mislukt.
    popd
    pause
    exit /b 1
)
popd
echo       Klaar.
echo.

REM ---------------------------------------------------------------
REM 5. API-sleutels invoeren
REM ---------------------------------------------------------------
echo [5/5] Je API-sleutels instellen...
echo.
echo   Houd twee dingen bij de hand:
echo     - je OpenAI API key    (platform.openai.com/api-keys)
echo     - je Coinbase JSON-bestand met "name" en "privateKey"
echo.
echo   Wat je typt blijft onzichtbaar. Dat hoort zo.
echo.
pause
echo.
"%VENV_PY%" -m tools.setup_wizard
set "WIZARD_RESULT=%errorlevel%"

echo.
echo ============================================================
if "%WIZARD_RESULT%"=="0" (
    echo   INSTALLATIE GELUKT
    echo.
    echo   Start de bot voortaan met:  START-JARVIS.bat
) else (
    echo   INSTALLATIE NOG NIET COMPLEET
    echo.
    echo   De sleutels zijn nog niet allemaal goed ingesteld.
    echo   Hierboven staat precies wat er mist.
    echo   Start dit bestand opnieuw om het te herstellen.
)
echo ============================================================
echo.
pause
