# Nadajnik i odbiornik akustyczny

Dwie aplikacje okienkowe dla Windows 11. Nadajnik może odtwarzać plik audio,
generować sinus 0–20 kHz i wysyłać tekst metodą FSK przez głośnik. Odbiornik
przechwytuje mikrofon, dekoduje tekst, pokazuje przebieg na oscyloskopie,
zapisuje tekst i opcjonalnie kieruje dźwięk z mikrofonu na głośnik.

## Uruchomienie ze źródeł

Zainstaluj Python 3.11 lub nowszy. W katalogu projektu na Windows:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe transmitter.py
```

Odbiornik uruchom w drugim oknie terminala poleceniem
`.venv\Scripts\python.exe receiver.py`.

Uruchom programy na osobnych komputerach lub użyj dwóch urządzeń audio.
Przy dwóch programach na jednym komputerze wybierz osobne wejście i wyjście.
W obu oknach ustaw identyczne częstotliwości dla bitów `0` i `1` oraz identyczną
szybkość transmisji. Najpierw włącz odbiornik, potem naciśnij **Wyślij tekst**.
Domyślne 1200/2200 Hz i 25 bitów/s są punktem startowym. Odbiór zależy od
głośności, mikrofonu, odległości i hałasu w pomieszczeniu. Nadawanie długich
wiadomości trwa odpowiednio dłużej; maksymalna wiadomość ma 2048 bajtów UTF-8.

Suwak poziomu ustawia amplitudę cyfrową w procentach. Napięcie w woltach na
fizycznym wyjściu zależy od karty dźwiękowej, ustawień Windows i wzmacniacza;
podanie wartości w V wymaga pomiaru oraz kalibracji. Sygnał 20 kHz jest możliwy
cyfrowo przy próbkowaniu 48 kHz, ale zwykłe głośniki i mikrofony mogą go nie
przenosić. Dla odsłuchu mikrofonu użyj słuchawek lub ogranicz poziom, żeby
uniknąć sprzężenia akustycznego.

Plik audio jest **odtwarzany**, a nie przesyłany jako dane do odtworzenia pliku
na komputerze odbiorcy. Obsługiwane formaty zależą od biblioteki libsndfile
dołączonej do `soundfile`; WAV jest najbezpieczniejszym wyborem.

## Dwie binarki Windows

Na komputerze z Windows uruchom `build_windows.bat`. Pliki wynikowe trafią do
`dist\Nadajnik.exe` i `dist\Odbiornik.exe`. PyInstaller wymaga budowania na
systemie docelowym, więc ten skrypt trzeba uruchomić na Windows, a potem
sprawdzić wejście i wyjście dźwięku na docelowych urządzeniach.

Na komputerze użytym do testów gotowe pliki z kompilacji na Windows 11 w QEMU
znajdują się w `vm/results/Nadajnik.exe` i `vm/results/Odbiornik.exe`.
Wyniki testów są w tym samym folderze. Katalog `vm/results/` zawiera lokalne
artefakty i nie jest częścią repozytorium Git. Opis maszyny i sposób połączenia
VNC: `vm/README.md`.

## Sprawdzenie protokołu

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Test sprawdza odbiór tekstu UTF-8 przy losowych granicach pakietów audio i
szumie oraz odrzucenie wiadomości z błędną sumą kontrolną. Nie zastępuje próby
przez rzeczywisty głośnik i mikrofon.
