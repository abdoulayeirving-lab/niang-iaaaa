@echo off
rem start_remote.cmd — runs Kaizumi with the Bluetooth phone transport enabled.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -u "%~dp0main.py" --remote
  exit /b 0
)

if not exist "%~dp0START_NIANG_IA.bat" goto missing_environment
call "%~dp0START_NIANG_IA.bat" --remote
if errorlevel 1 exit /b 1
exit /b 0

:missing_environment
echo [ERREUR] L'environnement NIANG IA est absent ou incomplet.
echo Lancez START_NIANG_IA.bat depuis le dossier d'installation pour reparer l'application.
pause
exit /b 1
