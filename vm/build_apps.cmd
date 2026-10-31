@echo off
setlocal
set "EXCHANGE=%~dp0"
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
set "SOURCE=%EXCHANGE%project"
set "WORK=%TEMP%\sound-qemu-build"

if not exist "%PYTHON%" (
    echo Najpierw uruchom install_and_probe.cmd.
    pause
    exit /b 1
)

if not exist "%WORK%" mkdir "%WORK%"
xcopy "%SOURCE%\*" "%WORK%\source\" /E /I /Y >nul
if errorlevel 1 goto failed
cd /d "%WORK%\source"

"%PYTHON%" -m PyInstaller --noconfirm --clean --onefile --windowed --collect-all sounddevice --collect-all soundfile --distpath "%WORK%\dist" --workpath "%WORK%\build" --specpath "%WORK%\spec" --name Nadajnik transmitter.py
if errorlevel 1 goto failed
"%PYTHON%" -m PyInstaller --noconfirm --clean --onefile --windowed --collect-all sounddevice --collect-all soundfile --distpath "%WORK%\dist" --workpath "%WORK%\build" --specpath "%WORK%\spec" --name Odbiornik receiver.py
if errorlevel 1 goto failed

for %%F in (Nadajnik.exe Odbiornik.exe) do (
    curl.exe --fail --silent --show-error --data-binary @"%WORK%\dist\%%F" "http://10.0.2.2:8765/%%F"
    if errorlevel 1 goto failed
)

echo Pliki EXE sa w %WORK%\dist
pause
exit /b 0

:failed
echo Nie udalo sie zbudowac aplikacji.
pause
exit /b 1
