@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv || exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller || exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --collect-all sounddevice --collect-all soundfile --name Nadajnik transmitter.py || exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --collect-all sounddevice --collect-all soundfile --name Odbiornik receiver.py || exit /b 1

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --collect-all sounddevice --collect-all soundfile --name Transceiver transceiver.py || exit /b 1

echo.
echo Gotowe: dist\Nadajnik.exe, dist\Odbiornik.exe i dist\Transceiver.exe
endlocal
