@echo off
rem Launch MPC Mapper on Windows, creating/repairing its Python environment first.
rem The venv lives in %LOCALAPPDATA% rather than next to this file: Qt's files
rem have long paths and would exceed Windows' 260-character limit when the
rem project sits in a deep folder such as Downloads\...\MPC_Mapper-...\.
setlocal
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\MPCMapper\venv"
set "PY=%VENV%\Scripts\python.exe"

if not exist "%PY%" (
    echo Creating Python environment in %VENV% ...
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv "%VENV%"
    ) else (
        python -m venv "%VENV%"
    )
    if not exist "%PY%" (
        echo.
        echo Could not create the Python environment. Install Python 3.9 or newer
        echo from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
        pause
        exit /b 1
    )
)

rem Install or repair the requirements whenever one of them is missing.
"%PY%" -c "import PySide6.QtWidgets, mido, pythonosc" >nul 2>nul
if errorlevel 1 (
    echo Installing requirements ...
    "%PY%" -m pip install --upgrade pip >nul 2>nul
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Installing the requirements failed, see the messages above.
        pause
        exit /b 1
    )
)

"%PY%" -m mpc_mapper %*
if errorlevel 1 pause
