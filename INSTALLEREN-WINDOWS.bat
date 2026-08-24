@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set "STAP=0"
echo ============================================================
echo   JARVIS Trading Bot - installatie
echo ============================================================
echo.
echo Dit duurt ongeveer 5 tot 15 minuten. Je hoeft niets te doen
echo tot er om je API-sleutels wordt gevraagd.
echo.

REM ===============================================================
REM 1. Python
REM ===============================================================
echo [1/7] Python controleren...
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    call :GEEN_PYTHON
    exit /b 1
)
%PY% --version >nul 2>&1
if errorlevel 1 (
    REM Windows heeft een 'python' alias die naar de Store leidt en niets doet.
    call :GEEN_PYTHON
    exit /b 1
)
for /f "delims=" %%v in ('%PY% --version 2^>^&1') do echo       %%v
echo.

REM ===============================================================
REM 2. Node.js en npm (apart controleren; npm kan los ontbreken)
REM ===============================================================
echo [2/7] Node.js en npm controleren...
call :CHECK_NODE
if "%NODE_OK%"=="1" goto NODE_KLAAR

echo       Node.js is niet gevonden.
echo.
where winget >nul 2>&1
if errorlevel 1 goto NODE_HANDMATIG

echo       winget is beschikbaar. Node.js LTS kan automatisch worden
echo       geinstalleerd vanaf de officiele bron (OpenJS Foundation).
echo.
set "ANTWOORD="
set /p "ANTWOORD=      Nu automatisch installeren? (J/N): "
if /i not "!ANTWOORD!"=="J" goto NODE_HANDMATIG

echo.
echo       Node.js LTS installeren via winget...
REM -e/--exact voorkomt dat winget de id als zoekterm behandelt en een
REM ander pakket kiest. OpenJS.NodeJS.LTS is het officiele pakket van de
REM OpenJS Foundation in de standaard winget-bron.
winget install --id OpenJS.NodeJS.LTS -e --source winget ^
    --accept-package-agreements --accept-source-agreements --silent
if errorlevel 1 (
    echo       De automatische installatie is niet gelukt.
    goto NODE_HANDMATIG
)

REM Een nieuw geinstalleerde Node staat nog niet in de PATH van dit venster.
REM Die halen we uit het register en plakken we er zelf bij.
echo       PATH vernieuwen...
call :REFRESH_PATH
call :CHECK_NODE
if "%NODE_OK%"=="1" (
    echo       Node.js is geinstalleerd en gevonden.
    goto NODE_KLAAR
)

echo.
echo   ------------------------------------------------------------
echo   Node.js is geinstalleerd, maar dit venster ziet het nog niet.
echo   Dat is normaal: Windows moet de PATH opnieuw inlezen.
echo.
echo   SLUIT DIT VENSTER en dubbelklik INSTALLEREN-WINDOWS.bat
echo   opnieuw. Daarna gaat de installatie gewoon verder.
echo   ------------------------------------------------------------
echo.
pause
exit /b 1

:NODE_HANDMATIG
echo.
echo   ------------------------------------------------------------
echo   Node.js moet handmatig geinstalleerd worden.
echo.
echo   1. Ga naar https://nodejs.org/
echo   2. Klik op de knop met "LTS" erin.
echo   3. Open het gedownloade bestand en klik steeds op Next.
echo   4. Sluit dit venster en start dit bestand opnieuw.
echo   ------------------------------------------------------------
echo.
pause
exit /b 1

:NODE_KLAAR
echo       node !NODE_VERSIE!   npm !NPM_VERSIE!
echo.

REM ===============================================================
REM 3. Python-omgeving
REM ===============================================================
echo [3/7] Python-omgeving klaarzetten...
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv
    if errorlevel 1 (
        echo   FOUT: kon de Python-omgeving niet aanmaken.
        pause
        exit /b 1
    )
)
set "VENV_PY=%CD%\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo   FOUT: de Python-omgeving is onvolledig. Verwijder de map .venv
    echo   en start dit bestand opnieuw.
    pause
    exit /b 1
)
echo       Klaar.
echo.

REM ===============================================================
REM 4. Python-pakketten
REM ===============================================================
echo [4/7] Python-pakketten installeren, even geduld...
"%VENV_PY%" -m pip install --upgrade pip --quiet
"%VENV_PY%" -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo   FOUT: installeren van de Python-pakketten is mislukt.
    pause
    exit /b 1
)
REM Het dashboard heeft een eigen lijst (fastapi, uvicorn).
"%VENV_PY%" -m pip install -r dashboard\backend\requirements.txt --quiet
if errorlevel 1 (
    echo   FOUT: installeren van de dashboard-pakketten is mislukt.
    pause
    exit /b 1
)
echo       Klaar.
echo.

REM ===============================================================
REM 5. Dashboard bouwen
REM ===============================================================
echo [5/7] Dashboard bouwen...
pushd dashboard\frontend
REM npm ci volgt package-lock.json exact; npm install zou de lockfile
REM kunnen wijzigen en een andere versiecombinatie kunnen opleveren.
call npm ci --no-audit --no-fund
if errorlevel 1 (
    echo       npm ci is mislukt; opnieuw proberen met npm install...
    call npm install --no-audit --no-fund
    if errorlevel 1 (
        echo   FOUT: installeren van de dashboard-onderdelen is mislukt.
        popd
        pause
        exit /b 1
    )
)
call npm run build
if errorlevel 1 (
    echo   FOUT: het bouwen van het dashboard is mislukt.
    popd
    pause
    exit /b 1
)
popd
if not exist "dashboard\frontend\dist\index.html" (
    echo   FOUT: het dashboard is gebouwd maar dist\index.html ontbreekt.
    pause
    exit /b 1
)
echo       Klaar.
echo.

REM ===============================================================
REM 6. Sleutels invoeren
REM ===============================================================
echo [6/7] Je API-sleutels instellen...
echo.
echo   Houd twee dingen bij de hand:
echo     - je OpenAI API key    (platform.openai.com/api-keys)
echo     - het Coinbase JSON-bestand dat je hebt gedownload
echo.
echo   De OpenAI-sleutel plak je met een rechtermuisklik. Je ziet
echo   sterretjes verschijnen; de sleutel zelf blijft onzichtbaar.
echo.
echo   Voor Coinbase wordt het JSON-BESTAND gebruikt. Staat dat in je
echo   map Downloads, dan vindt de wizard het zelf en hoef je alleen
echo   het nummer te typen. Anders sleep je het bestand in dit venster.
echo   Dat is betrouwbaarder dan de sleutel plakken: een privateKey
echo   staat op meerdere regels en overleeft plakken niet.
echo.
pause
echo.

:SLEUTELS
"%VENV_PY%" -m tools.setup_wizard
if not errorlevel 1 goto SLEUTELS_KLAAR

echo.
echo   ------------------------------------------------------------
echo   De sleutels zijn nog niet allemaal goed ingesteld.
echo   Hierboven staat precies wat er mist.
echo   ------------------------------------------------------------
echo.
set "NOGMAALS="
set /p "NOGMAALS=  Meteen opnieuw proberen? (J/N): "
echo.
if /i "!NOGMAALS!"=="J" goto SLEUTELS

echo.
echo ============================================================
echo   INSTALLATIE NIET COMPLEET
echo.
echo   Alles behalve de sleutels staat klaar. Je hoeft de
echo   installatie niet opnieuw te doen; start dit bestand opnieuw
echo   en de eerdere stappen worden overgeslagen.
echo ============================================================
echo.
pause
exit /b 1

:SLEUTELS_KLAAR
echo.

REM ===============================================================
REM 7. Online validatie -- werken de sleutels echt?
REM ===============================================================
echo [7/7] Sleutels controleren bij OpenAI en Coinbase...
echo       Dit doet alleen leesvragen. Er wordt niets gekocht of verkocht.
echo.
"%VENV_PY%" -m tools.setup_wizard --check --online
set "ONLINE=%errorlevel%"

echo.
echo ============================================================
if "%ONLINE%"=="0" (
    echo   INSTALLATIE GELUKT
    echo.
    echo   Sleutels opgeslagen en door OpenAI en Coinbase geaccepteerd.
    echo   Start de bot voortaan met:  START-JARVIS.bat
) else if "%ONLINE%"=="2" (
    echo   INSTALLATIE VOLTOOID - API-VALIDATIE NIET UITGEVOERD
    echo.
    echo   De sleutels staan goed opgeslagen, maar OpenAI of Coinbase
    echo   was niet bereikbaar. Dat wijst op een netwerk- of
    echo   internetprobleem, niet op een verkeerde sleutel.
    echo.
    echo   Controleer je internetverbinding en draai daarna:
    echo     .venv\Scripts\python -m tools.setup_wizard --check --online
) else (
    echo   INSTALLATIE NIET COMPLEET - SLEUTELS AFGEWEZEN
    echo.
    echo   De sleutels zijn opgeslagen, maar werden afgewezen.
    echo   Hierboven staat welke en waarom.
    echo   Haal die sleutel opnieuw op en start dit bestand opnieuw.
)
echo ============================================================
echo.
pause
exit /b 0


REM ===============================================================
REM Hulpblokken
REM ===============================================================

:CHECK_NODE
set "NODE_OK="
set "NODE_VERSIE="
set "NPM_VERSIE="
where node >nul 2>&1 || goto :eof
where npm  >nul 2>&1 || goto :eof
for /f "delims=" %%v in ('node --version 2^>nul') do set "NODE_VERSIE=%%v"
for /f "delims=" %%v in ('npm --version 2^>nul') do set "NPM_VERSIE=%%v"
if not defined NODE_VERSIE goto :eof
if not defined NPM_VERSIE goto :eof
set "NODE_OK=1"
goto :eof

:REFRESH_PATH
REM Haal de PATH opnieuw uit het register, zodat een zojuist geinstalleerd
REM programma zonder herstart van het venster gevonden kan worden.
for /f "tokens=2,*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul ^| find "REG_"') do set "MACHINE_PATH=%%b"
for /f "tokens=2,*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul ^| find "REG_"') do set "USER_PATH=%%b"
set "PATH=%MACHINE_PATH%;%USER_PATH%;%PATH%"
goto :eof

:GEEN_PYTHON
echo.
echo   ------------------------------------------------------------
echo   Python is niet gevonden.
echo.
echo   1. Ga naar https://www.python.org/downloads/
echo   2. Klik op de grote gele knop.
echo   3. BELANGRIJK: zet onderin een vinkje bij
echo      "Add python.exe to PATH" voordat je op Install klikt.
echo   4. Sluit dit venster en start dit bestand opnieuw.
echo   ------------------------------------------------------------
echo.
pause
goto :eof
