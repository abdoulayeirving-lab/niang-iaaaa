@echo off
rem start_remote.cmd — runs Kaizumi with the Bluetooth phone transport enabled.
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -u "%~dp0main.py" --remote
  exit /b 0
)

where pythonw.exe >nul 2>&1
if not errorlevel 1 (
  start "" pythonw.exe -u "%~dp0main.py" --remote
  exit /b 0
)

echo [ERREUR] pythonw.exe introuvable. Installe Python ou relance START_NIANG_IA.bat pour reparer l'environnement.
exit /b 1