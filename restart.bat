@echo off
REM JARVIS herstarten.
REM
REM Dit bestand bestaat zodat de bekende Engelse naam ook werkt. De echte
REM stappen staan in HERSTART-JARVIS.bat -- daar hoef je niets voor te weten, dubbelklikken
REM op dit bestand doet precies hetzelfde.
cd /d "%~dp0"
call "%~dp0HERSTART-JARVIS.bat" %*
exit /b %errorlevel%
