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
call :ZOEK_PYTHON
if not defined PY (
    REM Onderscheid maken tussen "geen Python" en "te oude Python": een
    REM gebruiker met 3.11 kwam hier vroeger gewoon doorheen en liep pas in
    REM stap 4 vast op een pip-fout die de Python-versie niet noemt.
    call :ZOEK_PYTHON_OUD
    if defined PY_OUD (
        call :PYTHON_TE_OUD
    ) else (
        call :GEEN_PYTHON
    )
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
echo   JARVIS opent zo de officiele pagina's van OpenAI en Coinbase.
echo   Je hoeft niets op te zoeken en geen paden te typen.
echo.
echo   OpenAI    maak een key aan en druk op de kopieerknop.
echo             JARVIS pikt hem van het klembord.
echo.
echo   Coinbase  maak een API-key aan van het type ECDSA en download
echo             het JSON-bestand. JARVIS ziet de download vanzelf.
echo.
echo   Lukt het oppikken niet, dan wordt het alsnog gewoon gevraagd.
echo.
pause
echo.

:SLEUTELS
"%VENV_PY%" -m tools.connect_services
set "SLEUTELS_CODE=!errorlevel!"
REM 0 = gekoppeld en geverifieerd, 2 = opgeslagen maar de API was niet
REM bereikbaar. Alleen 1 betekent dat er echt iets mis is met de sleutels.
REM Op 2 hier stoppen zou van een tijdelijke internetstoring een mislukte
REM installatie maken; stap 7 legt dat geval netjes uit.
if "!SLEUTELS_CODE!"=="0" goto SLEUTELS_KLAAR
if "!SLEUTELS_CODE!"=="2" goto SLEUTELS_KLAAR

echo.
echo   ------------------------------------------------------------
echo   De sleutels zijn nog niet allemaal goed ingesteld.
echo   Hierboven staat precies wat er mist.
echo.
echo   Met de hand invoeren kan ook:
echo     .venv\Scripts\python -m tools.setup_wizard
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

:ZOEK_PYTHON
REM Zoek een Python die de vastgezette pakketten aankan. numpy 2.4 eist
REM 3.12 of nieuwer, en .python-version noemt 3.12.3. Een oudere versie
REM installeert requirements.txt niet.
REM
REM Op Windows staan vaak meerdere versies naast elkaar, en `py -3` kiest
REM niet per se de nieuwste. Daarom eerst expliciet de nieuwe versies langs
REM via de launcher, en pas daarna de standaardkeuzes.
set "PY="
where py >nul 2>&1 || goto ZOEK_PYTHON_KAAL
REM Blokvorm en geen `&&` achter de if: `if not defined PY cmd && set ...`
REM zou de set koppelen aan de errorlevel van wat er daarvoor liep, en dan
REM alsnog een al gevonden PY overschrijven.
for %%v in (3.14 3.13 3.12) do (
    if not defined PY (
        py -%%v -c "import sys; raise SystemExit(0 if sys.version_info>=(3,12) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY=py -%%v"
    )
)
if defined PY goto :eof
py -3 -c "import sys; raise SystemExit(0 if sys.version_info>=(3,12) else 1)" >nul 2>&1 && set "PY=py -3"
if defined PY goto :eof

:ZOEK_PYTHON_KAAL
REM Windows heeft een 'python' alias die naar de Store leidt en niets doet;
REM die valt hier vanzelf af, want hij voert dit commando niet uit.
python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,12) else 1)" >nul 2>&1 && set "PY=python"
goto :eof

:ZOEK_PYTHON_OUD
REM Is er wel een Python, maar een te oude? Dan is de melding een andere.
set "PY_OUD="
set "PY_OUD_VERSIE="
for %%c in (py python) do (
    if not defined PY_OUD (
        where %%c >nul 2>&1 && %%c -c "import sys" >nul 2>&1 && set "PY_OUD=%%c"
    )
)
if not defined PY_OUD goto :eof
for /f "delims=" %%v in ('!PY_OUD! --version 2^>^&1') do set "PY_OUD_VERSIE=%%v"
goto :eof

:PYTHON_TE_OUD
echo.
echo   ------------------------------------------------------------
echo   Python is gevonden, maar is te oud.
echo.
echo   Gevonden:  !PY_OUD_VERSIE!
echo   Nodig:     Python 3.12 of nieuwer
echo.
echo   De vastgezette pakketten (numpy, pandas) worden niet meer voor
echo   oudere versies uitgebracht; de installatie zou verderop
echo   stukloopen op een foutmelding die dit niet uitlegt.
echo.
echo   1. Ga naar https://www.python.org/downloads/
echo   2. Download Python 3.12 of nieuwer.
echo   3. Zet bij het installeren een vinkje bij
echo      "Add python.exe to PATH".
echo   4. Sluit dit venster en start dit bestand opnieuw.
echo   ------------------------------------------------------------
echo.
pause
goto :eof

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
