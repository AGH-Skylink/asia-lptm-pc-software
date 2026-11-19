# Dokumentacja LPTM do raportu końcowego

Projekt: **LPTM — Laser Polarisation Modulation Transciever**.

Dokument główny: **LPTM_dokumentacja_do_raportu_grantowego.pdf** — 24 strony,
22 rozdziały, aktywny spis treści, cztery diagramy wektorowe, dwa wykresy
i reprodukcje dwóch odebranych zdjęć. Wersja dokumentu: 1.1.
Data opracowania: 17 listopada 2026 r.

## Zakres

Raport obejmuje oprogramowanie PC, protokół, modulacje, obsługę, transfer plików,
diagnostykę, weryfikację programową oraz analizę ośmiu wybranych serii z archiwum.
Nie dopisano danych uczelni, autorów, numeru grantu ani parametrów optyki,
których nie podano w materiale źródłowym.

Wyniki obliczono z oryginalnych logów CSV. Pomiary historyczne i testy
programowe są opisane osobno. Przyjęcie `no_frame = 100%` w podsumowaniach
wyjaśniono jako konwencję oceny, a nie pomiar BER.

## Uzupełnienie po poprawie toru

Historyczne wykresy oznaczono jako wyniki kanału słabej jakości. Dodano wyniki
przekazane przez zespół: przedwzmacniacz 25 V/V, 2FSK 10/20 kHz przy 5 kbit/s
oraz sprawną transmisję zdjęć 4FSK 5–10 kHz przy 2,5 kbit/s i raportowanym
BER 0,5%. Dalsze próby szybszych 4FSK i 16QAM trwają.

Pliki `TRANSMISJA/karmelini.jpg` i `TRANSMISJA/Bez tytułu.jpg` porównano ze
źródłami: oba mają identyczne bajty i SHA-256. Przekazany BER nie jest
przypisywany błędom w gotowych JPEG ani przedstawiany jako nowa seria CSV.

## Pliki

- `LPTM_dokumentacja_zrodlo.md` — edytowalna treść raportu.
- `zestawienie_serii.csv` — obliczone wskaźniki ośmiu serii.
- `dane_i_proweniencja.json` — identyfikacja kodu, statystyki i SHA-256 źródeł.
- `testy_weryfikacja.json` — wynik uruchomienia 48 testów z 17.11.2026.
- `wyniki_przedwzmacniacz.json` — parametry i wyniki przekazane przez zespół.
- `weryfikacja_TRANSMISJA.json` — zgodność źródeł i odebranych obrazów.
- `zalaczniki/zapisTransmisji16_11.txt` — oryginalny zapis pomocniczy z prób.
- `kontrola_pdf.json` — kontrola struktury, kodowania i granic stron.
- `assets/` — diagramy SVG i wykresy PNG/PDF do ponownego wykorzystania.
- `build_report.py` — generator dokumentu i analizy danych.
- `verify_report.py` — kontrola końcowego PDF.
- `podglad/` — lokalne obrazy kontrolne stron, pominięte w archiwum ZIP.

## Regeneracja

Skrypt należy uruchamiać w pełnym repozytorium, z tym katalogiem pod ścieżką
`docs/raport_grantowy`. Używa plików kodu i pomiarów z repozytorium.
Sam pakiet raportowy ZIP nie zawiera całego repozytorium ani dzienników raw.

```powershell
python -m pip install -r docs/raport_grantowy/requirements-docs.txt
python docs/raport_grantowy/build_report.py
python docs/raport_grantowy/verify_report.py
```

Generator korzysta z fontów Windows Calibri / Segoe UI / Consolas;
na Linuksie przewidziano fonty DejaVu z `/usr/share/fonts/truetype/dejavu`.
Nie uruchamia toru audio ani nowych pomiarów. Zmiana samego Markdown nie
zmienia PDF: treść do regeneracji jest w `build_report.py`.

Testy aplikacji można ponowić oddzielnie:

```powershell
python -m unittest discover -s tests -v
```

Archiwum i raport identyfikują stan źródeł skrótem Git oraz skrótami plików.
Przy aktualizacji oprogramowania trzeba ponowić kontrolę treści, danych i testów.
