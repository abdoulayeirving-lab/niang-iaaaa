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

set "PYTHON_INSTALLER=%~dp0runtime\python-3.12.10-amd64.exe"
if exist "%PYTHON_INSTALLER%" goto install_bundled_python

where winget >nul 2>&1
if errorlevel 1 goto python_missing

echo Installation automatique de Python 3.12...
winget install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo.
    echo [ERREUR] Installation de Python impossible.
    echo Verifie la connexion Internet ou installe Python 3.11/3.12, puis relance NIANG IA.
    pause
    exit /b 1
)

call :find_python
if not defined PYTHON_EXE goto python_missing
goto create_venv

:install_bundled_python
echo Installation automatique de Python 3.12 fourni avec NIANG IA...
"%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 TargetDir="%LocalAppData%\Programs\Python\Python312" PrependPath=0 Include_launcher=0 Include_pip=1 Include_tcltk=1 Include_test=0 Shortcuts=0
if errorlevel 1 goto python_install_error
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
echo Si Python vient d'etre installe, ferme et relance NIANG IA.
echo Sinon, installe Python 3.11 ou 3.12, puis relance ce fichier.
pause
exit /b 1

:python_install_error
echo.
echo [ERREUR] L'installation automatique de Python 3.12 a echoue.
echo Relance l'installateur NIANG IA ou installe Python 3.11/3.12 manuellement.
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
