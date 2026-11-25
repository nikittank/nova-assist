#!/usr/bin/env bash
# Build a standalone macOS/Linux executable for Nova Assistant.
# Output: dist/NovaAssistant
set -e
cd "$(dirname "$0")"

echo "[1/3] Installing dependencies..."
python3 -m pip install --upgrade pip
pip3 install -r requirements.txt
pip3 install pyinstaller

echo "[2/3] Running self-test..."
python3 selftest.py --audio

echo "[3/3] Building executable..."
pyinstaller NovaAssistant.spec --noconfirm --clean

echo
echo "Done!  Your executable is at:  dist/NovaAssistant"
