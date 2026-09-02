@echo off
REM JARVIS stoppen.
REM
REM Dit bestand bestaat zodat de bekende Engelse naam ook werkt. De echte
REM stappen staan in STOP-JARVIS.bat -- daar hoef je niets voor te weten, dubbelklikken
REM op dit bestand doet precies hetzelfde.
cd /d "%~dp0"
call "%~dp0STOP-JARVIS.bat" %*
exit /b %errorlevel%
