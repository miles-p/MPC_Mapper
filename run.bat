@echo off
rem Create the venv on first run, then launch MPC Mapper (Windows).
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 (
        echo Could not create the virtual environment. Install Python 3.9+ from python.org
        echo and tick "Add python.exe to PATH" in the installer.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Installing the requirements failed.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m mpc_mapper %*
if errorlevel 1 pause
