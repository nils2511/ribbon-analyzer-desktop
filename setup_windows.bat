@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 'Python 3.10+ required')"
if errorlevel 1 goto failed
if not exist "venv\Scripts\python.exe" (
    py -3 -m venv venv
    if errorlevel 1 goto failed
)
"venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Setup complete. Double-click start.bat.
echo Manual annotation works locally without an API key.
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.10+ with Tcl/Tk and the Python launcher.
pause
exit /b 1
