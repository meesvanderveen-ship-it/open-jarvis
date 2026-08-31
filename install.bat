@echo off
REM JARVIS installeren.
REM
REM Dit bestand bestaat zodat de bekende Engelse naam ook werkt. De echte
REM stappen staan in INSTALLEREN-WINDOWS.bat -- daar hoef je niets voor te weten, dubbelklikken
REM op dit bestand doet precies hetzelfde.
cd /d "%~dp0"
call "%~dp0INSTALLEREN-WINDOWS.bat" %*
exit /b %errorlevel%
