@echo off
REM Build a standalone Windows executable for Nova Assistant.
REM Requires Python 3.10+ on PATH. Output: dist\NovaAssistant.exe

cd /d "%~dp0"

echo [1/3] Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
if errorlevel 1 goto :error

echo [2/3] Running self-test...
python selftest.py
if errorlevel 1 goto :error

echo [3/3] Building executable...
pyinstaller NovaAssistant.spec --noconfirm --clean
if errorlevel 1 goto :error

echo.
echo Done!  Your executable is at:  dist\NovaAssistant.exe
pause
exit /b 0

:error
echo Build failed - read the messages above.
pause
exit /b 1
