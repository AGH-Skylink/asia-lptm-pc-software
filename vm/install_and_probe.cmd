@echo off
setlocal
set "EXCHANGE=%~dp0"
set "PYHOME=%LOCALAPPDATA%\Programs\Python\Python313"
set "PYTHON=%PYHOME%\python.exe"
set "WORK=%TEMP%\sound-qemu"

if not exist "%WORK%" mkdir "%WORK%"
"%PYTHON%" -V >nul 2>&1
if errorlevel 1 (
    copy /Y "%EXCHANGE%python-3.13.17-amd64.exe" "%WORK%\python-3.13.17-amd64.exe" >nul
    if errorlevel 1 goto failed
    "%WORK%\python-3.13.17-amd64.exe" /quiet InstallAllUsers=0 TargetDir="%PYHOME%" Include_pip=1 Include_tcltk=1 Include_test=0 PrependPath=0
    if errorlevel 1 goto failed
)

"%PYTHON%" -m pip install --no-index --find-links "%EXCHANGE%wheels" -r "%EXCHANGE%project\requirements.txt" "pyinstaller>=6,<7"
if errorlevel 1 goto failed

pushd "%EXCHANGE%project"
"%PYTHON%" -m unittest discover -s tests -v > "%WORK%\unit-tests.txt" 2>&1
if errorlevel 1 goto failed

"%PYTHON%" probe_devices.py --output "%WORK%\device-report.json" > "%WORK%\probe-log.txt" 2>&1
if errorlevel 1 goto failed
popd

for %%F in (unit-tests.txt probe-log.txt device-report.json) do (
    curl.exe --fail --silent --show-error --data-binary @"%WORK%\%%F" "http://10.0.2.2:8765/%%F"
    if errorlevel 1 goto failed
)

echo Testy zakonczone. Raport: %WORK%\device-report.json
echo Uruchom programy:
echo "%PYTHON%" "%EXCHANGE%project\transmitter.py"
echo "%PYTHON%" "%EXCHANGE%project\receiver.py"
pause
exit /b 0

:failed
echo Blad instalacji, testu lub wysylania raportu. Sprawdz %WORK%.
pause
exit /b 1
