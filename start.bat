@echo off
REM One-click launcher for Nova Assistant (Windows)
cd /d "%~dp0"
if exist "dist\NovaAssistant.exe" (
    start "Nova Assistant" "dist\NovaAssistant.exe"
    exit /b 0
)
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv || goto :error
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt || goto :error
) else (
    call .venv\Scripts\activate.bat
)
python main.py
exit /b 0

:error
echo Setup failed - make sure Python 3.10+ is installed and on PATH.
pause
