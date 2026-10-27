@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title NIANG IA - Assistant

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
    goto launch
)

call :find_python
if defined PYTHON_EXE goto create_venv

where winget >nul 2>&1
if errorlevel 1 goto python_missing

echo Python 3.11 ou 3.12 est necessaire pour NIANG IA.
echo Le programme peut installer Python 3.12 depuis winget.
choice /C YN /M "Installer Python 3.12 maintenant"
if errorlevel 2 exit /b 1

winget install --id Python.Python.3.12 --exact --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo.
    echo [ERREUR] Installation de Python impossible.
    echo Installe Python 3.12 depuis https://www.python.org/downloads/ puis relance ce fichier.
    pause
    exit /b 1
)

call :find_python
if not defined PYTHON_EXE goto python_missing

:create_venv
echo.
echo Creation de l'environnement Python de NIANG IA...
"%PYTHON_EXE%" %PYTHON_ARGS% -m venv ".venv"
if errorlevel 1 (
    echo [ERREUR] Impossible de creer l'environnement Python.
    pause
    exit /b 1
)

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
echo.
echo Installation des dependances. Cette etape necessite Internet et peut prendre plusieurs minutes...
"%PYTHON_EXE%" setup.py
if errorlevel 1 (
    echo.
    echo [ERREUR] Installation des dependances echouee.
    pause
    exit /b 1
)

:launch
echo.
"%PYTHON_EXE%" -c "import sys; print('Python', sys.version.split()[0])"
"%PYTHON_EXE%" -c "from google import genai" >nul 2>&1
if errorlevel 1 (
    echo Le module Gemini manque. Reparation de google-genai...
    "%PYTHON_EXE%" -m pip install --upgrade google-genai
    if errorlevel 1 goto genai_install_error
    "%PYTHON_EXE%" -c "from google import genai" >nul 2>&1
    if errorlevel 1 goto genai_import_error
)
"%PYTHON_EXE%" main.py
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo NIANG IA s'est arrete avec le code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%

:find_python
set "PYTHON_EXE="
set "PYTHON_ARGS="

where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3.12"
        exit /b 0
    )
    py -3.11 -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 11))" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3.11"
        exit /b 0
    )
)

for %%P in ("%LocalAppData%\Programs\Python\Python312\python.exe" "%LocalAppData%\Programs\Python\Python311\python.exe") do (
    if not defined PYTHON_EXE if exist "%%~P" (
        "%%~P" -c "import sys; raise SystemExit(sys.version_info[:2] not in ((3, 11), (3, 12)))" >nul 2>&1
        if not errorlevel 1 set "PYTHON_EXE=%%~P"
    )
)

if defined PYTHON_EXE exit /b 0

where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(sys.version_info[:2] not in ((3, 11), (3, 12)))" >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python"
)
exit /b 0

:python_missing
echo.
echo [ERREUR] Python 3.11 ou 3.12 n'a pas ete trouve.
echo Installe Python 3.12 depuis https://www.python.org/downloads/ puis relance ce fichier.
pause
exit /b 1

:genai_install_error
echo.
echo [ERREUR] Installation de google-genai echouee.
echo Verifie ta connexion Internet et relance START_NIANG_IA.bat.
pause
exit /b 1

:genai_import_error
echo.
echo [ERREUR] google-genai reste indisponible apres la reparation.
echo Dans PowerShell, execute : .\.venv\Scripts\python.exe -m pip install --upgrade google-genai
pause
exit /b 1
