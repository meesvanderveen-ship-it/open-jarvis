@echo off
REM Volledige diagnose van de installatie.
REM
REM Dit bestand bestaat zodat de bekende Engelse naam ook werkt. De echte
REM stappen staan in DIAGNOSE-JARVIS.bat -- daar hoef je niets voor te weten, dubbelklikken
REM op dit bestand doet precies hetzelfde.
cd /d "%~dp0"
call "%~dp0DIAGNOSE-JARVIS.bat" %*
exit /b %errorlevel%
