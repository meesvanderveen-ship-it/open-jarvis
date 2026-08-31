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
REM --online erbij: een ingetrokken sleutel heeft nog steeds een geldige
REM vorm en komt door de offline controle heen. Dan zou de bot starten met
REM credentials die Coinbase allang weigert, en werd de koppeling nooit
REM aangeboden. Alleen een echte read-only aanroep sluit dat uit.
echo Sleutels controleren...
echo.
REM De wizard onderscheidt drie uitkomsten: 0 = goed en geverifieerd,
REM 1 = ontbreekt of afgewezen, 2 = vorm klopt maar de API was onbereikbaar.
REM Alleen 1 vraagt om nieuwe sleutels. Bij 2 is er niets mis met de
REM credentials en zou een setup-dialoog de gebruiker op het verkeerde been
REM zetten; dat wordt een waarschuwing en de bot start gewoon.
"%VENV_PY%" -m tools.setup_wizard --check --online
set "PREFLIGHT=%errorlevel%"
if "%PREFLIGHT%"=="2" (
    echo.
    echo   Let op: de sleutels konden niet bij de API gecontroleerd worden.
    echo   Dat wijst op een netwerkprobleem, niet op verkeerde sleutels.
    echo   JARVIS start door.
    echo.
)
if "%PREFLIGHT%"=="1" (
    echo.
    echo ------------------------------------------------------------
    echo   JARVIS is nog niet startklaar.
    echo   Hierboven staat wat er mist.
    echo ------------------------------------------------------------
    echo.
    REM Meteen hier aanbieden in plaats van doorverwijzen naar een ander
    REM bestand: de sleutels invullen is precies wat er nu moet gebeuren,
    REM en dat is dezelfde wizard die INSTALLEREN-WINDOWS.bat zou starten.
    choice /c JN /n /m "Services nu koppelen? [J/N] "
    if errorlevel 2 (
        echo.
        echo   Goed. Start dit bestand opnieuw zodra de sleutels klaar zijn.
        echo.
        pause
        exit /b 1
    )
    echo.
    REM Connection setup opent de officiele pagina's en pikt de credential
    REM daarna zelf op. Lukt dat niet, dan vraagt hij hem alsnog gewoon --
    REM dezelfde opslag- en validatielaag als tools.setup_wizard, dat als
    REM handmatige route beschikbaar blijft.
    "%VENV_PY%" -m tools.connect_services
    echo.
    echo Sleutels opnieuw controleren...
    echo.
    "%VENV_PY%" -m tools.setup_wizard --check --online
    set "PREFLIGHT=%errorlevel%"
    if "!PREFLIGHT!"=="1" (
        echo.
        echo ------------------------------------------------------------
        echo   Nog steeds niet startklaar. Hierboven staat waarom.
        echo ------------------------------------------------------------
        echo.
        pause
        exit /b 1
    )
)

REM ===============================================================
REM Systeemcontrole: nooit starten en dan pas ontdekken dat er iets mist
REM ===============================================================
echo.
echo Systeemcontrole...
echo.
"%VENV_PY%" -m bot.health_check
set "HEALTH=%errorlevel%"
if "%HEALTH%"=="1" (
    echo.
    echo ------------------------------------------------------------
    echo   JARVIS start niet: er ontbreekt iets belangrijks.
    echo   Hierboven staat wat, en wat je eraan kunt doen.
    echo.
    echo   Draai DIAGNOSE-JARVIS.bat voor een volledige controle.
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
echo   De bot zelf draait onder een bewaker. Crasht hij door een
echo   storing, dan wordt hij vanzelf opnieuw gestart.
echo ------------------------------------------------------------
echo.

REM ===============================================================
REM Beide vensters draaien een langlopende dienst. Hier staat bewust het
REM relatieve pad .venv\Scripts\python.exe: dat bevat zelf geen spaties,
REM ook niet als de projectmap in bijvoorbeeld "Mijn Documenten" staat.
REM ===============================================================
echo Dashboard starten...
start "JARVIS dashboard" cmd /k ".venv\Scripts\python.exe -m dashboard.backend.run"

echo Achtergronddienst voor de Chrome-extensie starten...
start "JARVIS achtergronddienst" cmd /k ".venv\Scripts\python.exe -m control_service.run"

REM De bot niet rechtstreeks starten maar via de bewaker: die logt een
REM crash, ruimt op, wacht af en start opnieuw. Zonder die laag zou een
REM enkele exceptie het botvenster leeg achterlaten zonder uitleg.
echo Bot starten onder bewaking...
"%VENV_PY%" -m tools.jarvis_control start
if errorlevel 1 (
    echo.
    echo ------------------------------------------------------------
    echo   De bot is niet gestart. Hierboven staat waarom.
    echo   Kijk zo nodig in:  logs\supervisor.log
    echo ------------------------------------------------------------
    echo.
    pause
    exit /b 1
)

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

REM ===============================================================
REM Toegangssleutel voor de Chrome-extensie
REM ===============================================================
if exist "state\control_token.txt" (
    echo.
    echo ------------------------------------------------------------
    echo   Chrome-extensie
    echo.
    echo   De extensie heeft eenmalig een toegangssleutel nodig.
    echo   Die staat in dit bestand:
    echo     %CD%\state\control_token.txt
    echo.
    echo   Open het met Kladblok, kopieer de regel en plak hem in de
    echo   instellingen van de JARVIS-extensie in Chrome.
    echo.
    echo   Deel deze sleutel met niemand. Hij geeft toegang tot het
    echo   starten en stoppen van de bot op deze pc.
    echo ------------------------------------------------------------
)

echo.
echo Dit venster mag je sluiten. De twee andere niet.
echo.
echo Stoppen doe je met:  STOP-JARVIS.bat
echo.
pause
