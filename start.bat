@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0venv\Scripts\python.exe" (
    echo Run setup_windows.bat first.
    pause
    exit /b 1
)
"%~dp0venv\Scripts\python.exe" "%~dp0ribbon_analyzer.py" %*
if errorlevel 1 pause
