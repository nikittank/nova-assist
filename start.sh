#!/usr/bin/env bash
# One-click launcher for Nova Assistant (macOS / Linux)
cd "$(dirname "$0")"

if [ ! -f ".venv/bin/python" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv || { echo "Install python3-venv first (sudo apt install python3-venv python3-pip)"; exit 1; }
    ./.venv/bin/pip install --upgrade pip
    ./.venv/bin/pip install -r requirements.txt
    # Linux: PortAudio is needed for microphone input
    if command -v apt-get >/dev/null 2>&1 && ! ldconfig -p 2>/dev/null | grep -q libportaudio; then
        echo "NOTE: run 'sudo apt install libportaudio2' if the microphone does not work."
    fi
fi

exec ./.venv/bin/python main.py
