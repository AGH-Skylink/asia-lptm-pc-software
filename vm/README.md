# Symulacja Windows 11 x64 w QEMU na macOS

Maszyna jest całkowicie oddzielona od VirtualBox. Obraz `windows11.qcow2`
przechowuje system gościa; `uefi-vars.fd` i katalog `tpm/` przechowują stan
firmware i TPM. Skrypt `run_windows_qemu.sh` uruchamia UEFI, TPM 2.0, kartę
Intel HDA duplex, sieć NAT oraz ekran VNC na `127.0.0.1:5901`. Tryb
`QEMU_CAPTURE=1` dodaje drugą kartę z przechwytywaniem wyjścia do WAV.
`QEMU_CAPTURE=1 QEMU_CAPTURE_PRIMARY=1` przechwytuje pierwszą kartę,
zachowując drugą jako dodatkowe urządzenie.

Pierwsza karta ma wirtualne wejście i wyjście z niemym backendem. W trybie
przechwytywania druga karta zapisuje wyjście do `guest-output.wav`, chyba że
ustawiono `QEMU_CAPTURE_PRIMARY=1`.
Wirtualne wejście pierwszej karty dostarcza ciszę. Pierwszy etap testu
potwierdza wykrywanie kart przez obie aplikacje, a drugi sprawdza sygnał
nadawany z Windows w przechwyconym pliku WAV.

Folder `exchange/` jest obrazowany do `exchange.iso`, widocznego w Windows
jako płyta CD tylko do odczytu. Po zmianie plików w folderze odtwórz obraz:

```sh
hdiutil makehybrid -udf -ov -o vm/exchange.iso vm/exchange
```

Zawiera źródła programów, instalator Pythona i pakiety Windows. Wyniki testu
oraz binarki wracają do `vm/results/` przez lokalny serwer HTTP. Tryb do
odczytu zapobiega awarii emulowanego systemu plików FAT w QEMU, którą
zaobserwowano podczas rozpakowywania instalatora Pythona.

Po zakończeniu pobierania ISO uruchom:

```sh
python3 vm/receive_results.py
```

W drugim terminalu:

```sh
./vm/run_windows_qemu.sh
open vnc://127.0.0.1:5901
```

Klient „Udostępnianie ekranu” w macOS poprosi o hasło VNC: `Sound123`.
Hasło można zmienić przez `QEMU_VNC_PASSWORD=nowehaslo ./vm/run_windows_qemu.sh`
(protokół VNC używa najwyżej pierwszych ośmiu znaków hasła). Połączenie jest
dostępne tylko na tym Macu.

Instalator na emulowanym CPU może zgłosić niespełnione wymagania Windows 11.
Na pierwszym ekranie instalatora naciśnij `Shift+F10` i wpisz:

```cmd
reg add HKLM\SYSTEM\Setup\LabConfig /v BypassTPMCheck /t REG_DWORD /d 1 /f
reg add HKLM\SYSTEM\Setup\LabConfig /v BypassSecureBootCheck /t REG_DWORD /d 1 /f
reg add HKLM\SYSTEM\Setup\LabConfig /v BypassCPUCheck /t REG_DWORD /d 1 /f
reg add HKLM\SYSTEM\Setup\LabConfig /v BypassRAMCheck /t REG_DWORD /d 1 /f
reg add HKLM\SYSTEM\Setup\LabConfig /v BypassStorageCheck /t REG_DWORD /d 1 /f
exit
```

Następnie wybierz obraz `Windows 11 Enterprise LTSC Evaluation` i dysk
`Disk 0 Unallocated Space` o pojemności 80 GB. `exchange.iso` jest nośnikiem
z plikami projektu.

Po zainstalowaniu Windows zamknij maszynę i uruchom ją ponownie poleceniem
`QEMU_CAPTURE=1 ./vm/run_windows_qemu.sh`, aby sprawdzić drugi wirtualny
głośnik i przechwycić sygnał nadajnika.
Do przechwycenia pierwszej karty, widocznej również przez MME i DirectSound,
użyj `QEMU_CAPTURE=1 QEMU_CAPTURE_PRIMARY=1 ./vm/run_windows_qemu.sh`.

W Windows otwórz dodatkową płytę CD i uruchom `install_and_probe.cmd`. Skrypt skopiuje
instalator na dysk Windows, zainstaluje Python 3.13 oraz pakiety offline,
wykona testy i wyśle `device-report.json` do `vm/results/` na Macu.
`build_apps.cmd` buduje dwie binarki i również wysyła je do `vm/results/`.
Po nadaniu tekstu przez wyjście przechwytujące, zamknij maszynę i sprawdź WAV:

```sh
.venv/bin/python vm/check_capture.py
```

Test wykonany w Windows 11 x64 w QEMU: obie binarki uruchomiły się, raport
wykazał wirtualne wejścia i wyjścia, a nadajnik wysłał `TEST` przez pierwszą
kartę. Przechwycony plik miał 5,33 s i poziom szczytowy około 0,40; dekoder
odczytał `TEST`. Wyniki: `results/device-report.json`, `results/unit-tests.txt`
oraz `results/capture-report.json`. Backend WAV QEMU zapisał zerowe długości
w nagłówku RIFF; `check_capture.py` poprawia nagłówek w kopii
`guest-output-fixed.wav` bez zmiany próbek. Wirtualne wejście dostarcza ciszę,
więc test nie obejmuje fizycznego toru głośnik–mikrofon.

Windows 11 Enterprise LTSC Evaluation jest oficjalnym obrazem Microsoft do
testów przez 90 dni. Uruchomienie x86 na Macu ARM używa emulacji programowej
TCG, więc instalacja i obsługa systemu mogą być wolne.
