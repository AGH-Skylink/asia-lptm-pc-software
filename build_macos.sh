#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
export PYINSTALLER_CONFIG_DIR="$PWD/.pyinstaller-cache"
export PIP_CACHE_DIR="$PWD/.pip-cache"

if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi

.venv/bin/python -m pip install -r requirements.txt pyinstaller
.venv/bin/python -m PyInstaller --noconfirm --clean --onedir --windowed \
    --collect-all sounddevice --collect-all soundfile \
    --name Nadajnik transmitter.py
.venv/bin/python -m PyInstaller --noconfirm --clean --onedir --windowed \
    --collect-all sounddevice --collect-all soundfile \
    --name Odbiornik receiver.py

plutil -insert NSMicrophoneUsageDescription -string \
    "Odbiornik używa mikrofonu do odbierania sygnału akustycznego." \
    dist/Odbiornik.app/Contents/Info.plist
codesign --force --deep --sign - dist/Odbiornik.app

.venv/bin/python -m PyInstaller --noconfirm --clean --onedir --windowed \
    --collect-all sounddevice --collect-all soundfile \
    --name Transceiver transceiver.py
plutil -insert NSMicrophoneUsageDescription -string \
    "Transceiver uses the microphone to receive acoustic messages and files." \
    dist/Transceiver.app/Contents/Info.plist
codesign --force --deep --sign - dist/Transceiver.app

echo "Built: dist/Nadajnik.app, dist/Odbiornik.app and dist/Transceiver.app"
