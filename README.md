# Acoustic transmitter and receiver

Three desktop applications for Windows 11 and macOS. The transmitter can play
an audio file, generate a sine wave from 0 to 48 kHz, and send text through a
speaker using 2FSK, 4FSK or 16QAM. The receiver captures microphone input, decodes text,
displays a fixed-scale waveform and a signal strength meter, measures bit error
rate (BER) on every FSK frame, saves received text, and can optionally monitor
the microphone through a speaker.

**Transceiver** combines the existing transmitter and receiver in one window.
It has two columns without tabs: chat and file transfers on the left, and
the oscilloscope and shared modem settings on the right. Frequency, modulation, encoding, sample rate,
automatic announcements, transmission output and transmit level stay synchronized.
Start this app on each station for two-way chat and file transfer; separate
transmitter/receiver processes are not required.
The default Transceiver bit rate is 500 bit/s. The **Wyślij plik / zdjęcie**
panel has a JPEG chooser, byte progress and an estimated transmission time.
Generator, local audio playback, logging and CSV measurements are available
through **Narzędzia dodatkowe** on the same page.

Audio outputs are selected independently: **Nadawanie** carries modulated text,
chat and binary files; **Odsłuch mikrofonu** routes the captured audio when
**Odsłuch** is enabled; **Odtwarzanie / generator** plays local audio files and
the sine generator. For example, transmission can use a USB sound card while
monitoring uses headphones. Changing the monitoring device or enabling/disabling
monitoring during reception preserves the capture stream, decoder and WAV
recording. The selected devices must support the active sample rate.

The standalone receiver also has a **Czat** field with message history and a
composer. Choose **Wyjście nadawania czatu**, type a reply and press **Wyślij**
or Ctrl+Enter. It sends audio directly and starts reception if necessary. In
Transceiver the same composer uses the integrated transmitter. Received text
updates progressively in its history, including incomplete and bad-CRC messages.
The chat keeps both directions, excludes echoes of its own message IDs, and
can export the conversation through **Zapisz czat**. Outgoing status **Nadano**
means audio playback finished; it is not a delivery acknowledgement.
Switching the text encoding to ASCII converts the composer contents to readable
ASCII (for example Polish diacritics to plain Latin letters). Unsupported symbols
become `?`. Text pasted after switching is also converted before sending. Binary
files are unaffected by this setting.

Chat and the oscilloscope share a two-column layout: chat on the left and the
scope on the right. The scope voltage axis is fixed at −1…+1 V with 0.5 V
divisions, assuming PCM ±1 corresponds to ±1 V. There is no amplitude
normalization. A display-gain control magnifies the trace and marks values that
exceed the axis range. The time axis uses the actual capture sample rate and
offers 5, 10, 20, 50 or 100 ms windows. The trace displays raw capture samples;
the signal-strength meter separately measures filtered AC levels.

## Run from source

Install Python 3.11 or newer. In the project directory on Windows, run:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe transmitter.py
```

Start the receiver in a second terminal window with
`.venv\Scripts\python.exe receiver.py`.
Alternatively, run `.venv\Scripts\python.exe transceiver.py` for the combined app.

Run the applications on separate computers or use two audio devices. If both
applications run on one computer, select separate input and output devices.
Automatic receiver settings are enabled by default in both windows. Start the
receiver first, then click **Wyślij tekst** (Send text) in
the transmitter. The default 1200/2200 Hz and 25 bits/s are a starting point.
The bit rate can be set from 5 to 10,000 bits/s. At higher rates, the bit 0
and bit 1 frequencies must be farther apart. For 10,000 bits/s, try
3,000/17,000 Hz with a direct audio connection; actual speakers and
microphones may not carry these frequencies or this data rate reliably.
Reception depends on volume, microphone, distance, and ambient noise. Longer
messages take proportionally longer to transmit. The maximum message size is
2048 bytes in the selected text encoding (ASCII or UTF-8). Binary files are
transferred in multiple frames and are not limited to 2048 bytes.

Before a normal transmission, the transmitter announces its modulation,
frequencies, bit rate, sample rate and text encoding through an acoustic
1200/2200 Hz, 500 bit/s 2FSK frame. The receiver listens for this announcement
alongside its current mode and applies the settings automatically. A two-second
guard interval allows audio-device reconfiguration before data starts. This
works across computers without the local IPC connection. It is a one-way
announcement, without acknowledgement or automatic retransmission. Start the
receiver before sending; its audio hardware must support the announced rate.
Changing sample rate closes an active WAV recording. Disable automatic settings
at both ends to configure everything manually. CSV measurements use manual
2FSK settings and do not send announcements.

The level slider sets digital amplitude as a percentage. The physical output
voltage depends on the sound card, operating system settings, and amplifier;
displaying volts would require measurement and calibration. A 23.9 kHz signal
is just below the 24 kHz Nyquist limit of the 48 kHz sample rate; exactly
24 kHz cannot be generated as a usable sine wave. To extend the signal range to
48 kHz, select **192000** samples/s in both modem panels (or separately in the
generator tab). At 96000 samples/s the highest tone is 47.9 kHz; at 192000 it
is 48 kHz. The selected input, output and monitor devices must support the
selected sample rate. Ordinary speakers and
microphones may not reproduce the top of this range. For monitoring, use headphones
or keep the level low to avoid acoustic feedback.

The **Dobierz górną z bit/s** button calculates the minimum upper frequency
from the lower frequency and requested bit rate. For 2FSK the minimum spacing
is the bit rate. For 4FSK, the two endpoints define four equally spaced tones
for symbols `00`, `01`, `10`, `11`; intermediate tones are automatic. Each
symbol carries two bits, so its rate is half the bit rate and the endpoint
span must be at least 1.5 times the bit rate.
The **Dobierz bit/s z pasma** button calculates the maximum allowed bit rate
from the selected endpoints, capped at 10000 bit/s. The panel previews the
derived tones (or QAM carrier) and symbol rate.

**16QAM** uses Gray-coded I/Q levels and a carrier at the midpoint of the two
frequency settings. Each symbol carries four bits; the first half of each
symbol is a known carrier pilot for phase and gain recovery, and the second
half carries the constellation point. This is an application-specific framing
format. The lower frequency must be at least twice the symbol rate. Both ends
must select 16QAM. Noisy or nonlinear audio paths can distort its amplitude
levels. The receiver demodulates the original PCM; display gain and the scope
filter do not alter decoded samples. CSV measurement plans continue to use
2FSK at 48000 samples/s.

The receiver shows text as complete bytes arrive, before the final CRC is
available. Incomplete UTF-8 characters wait for the remaining bytes. Partial
messages and messages with bad CRC remain visible with their status, byte count
and BER. **Zapisz wiadomość + BER** saves the displayed message and report on
request, including incomplete messages. Select a destination and enable
**Zapisuj tekst w trakcie odbioru + bajty i BER** to append text as it arrives;
decoding corrections and the final CRC/BER report are marked in the log.
The report files use UTF-8 regardless of the transmission encoding.

**Nagrywaj WAV** selects a file and records unmodified microphone samples in
mono float WAV at the current capture rate. **Zakończ WAV**, stopping reception,
or closing the receiver finishes the recording. Recording uses a separate writer
thread so file I/O does not run in the audio callback.

Use **Wyślij plik / zdjęcie** to transfer an image or any binary file. In the
Transceiver it uses the shared settings; the standalone transmitter uses its
text/modulation settings. JPEG is always sent as binary bytes, independently
of ASCII/UTF-8. Selecting a binary image through the standalone transmitter's
legacy text-file path also routes it to binary file transfer. The receiver automatically saves it
under its original name and extension in **Folder odebranych plików** (default:
`~/Downloads/LPTM`). First comes an ASCII JSON header with name, size, block size
and SHA-256; then numbered 1024-byte binary blocks and an end marker. Each frame
has CRC. The receiver writes each accepted block to its numbered position in
`.part`, preserving later blocks even if an earlier block is missing. It saves
the finished file automatically as soon as all blocks arrive and SHA-256 matches;
the end marker is not required. An early end marker reports missing blocks while
still allowing delayed copies to complete the file. **Otwórz folder** opens the
destination shown in the receiver. Existing files are
preserved by adding the transfer ID to the new name. File packets are sent twice
by default; Transceiver offers 1–3 repetitions. The receiver ignores duplicate
blocks, including repeated end markers, so one lost copy can be recovered from
the next. Missing/corrupted blocks after all repetitions leave `.part`; send the
file again to retry. There is no resume or ACK mechanism.
A 1 MB image takes at least 1600 seconds at 5000 bit/s, plus framing overhead.

When both applications run on the same computer, the transmitter sends the
expected message bytes to the receiver over a local-only connection at
`127.0.0.1:51526` before playing the acoustic frame. The acoustic frame carries
a short message ID so the receiver can match it with that reference. The
receiver shows the locally reported data separately from the audio result and
calculates **BER danych** from the actual received payload bits, even when its
CRC fails. This local connection does not carry the acoustic transmission.
If the receiver is not running or the local connection is unavailable, the
transmitter still sends audio, but payload BER is unavailable.

Every FSK frame also contains a 128-bit known probe for **BER wzorca**. The
receiver measures this on each recognized frame, including when there is no
local reference. **Wyślij test BER** adds 1,024 known data bits to the probe
measurement. Lost frames whose preamble or length is too damaged to recognize
are excluded. **Wyzeruj BER** resets the counters. Starting a new local send
clears the previous received text immediately; any newly decoded frame also
replaces it. If CRC fails, the received text remains visible and is marked as
damaged. Both
applications must use the same protocol version. The signal
meter shows AC peak and RMS in dBFS after removal of DC offset and slow drift.
The meter filters out frequencies well below the configured FSK tones. The
filter affects the meter, not the scope trace or demodulation.

The **Plik audio** tab plays audio locally; the separate **Wyślij plik / zdjęcie**
tab transfers the actual file bytes for reconstruction. Playback formats depend on the libsndfile library
bundled with `soundfile`. WAV is the safest choice.

## Build the Windows executables

Run `build_windows.bat` on Windows. The resulting files are
`dist\Nadajnik.exe`, `dist\Odbiornik.exe` and `dist\Transceiver.exe`. PyInstaller must build on
the target operating system, so run this script on Windows and then check the
audio input and output on the target devices.

On the computer used for testing, executables built in a Windows 11 QEMU
guest are also available at `vm/results/Nadajnik.exe` and
`vm/results/Odbiornik.exe`. Test results are in the same directory.
`vm/results/` contains local artifacts and is not part of the Git repository.
For VM setup and VNC access, see [vm/README.md](vm/README.md).

## Build and run on macOS

On an Apple Silicon Mac, run:

```sh
chmod +x build_macos.sh
./build_macos.sh
open dist/Nadajnik.app
open dist/Odbiornik.app
open dist/Transceiver.app
```

The build creates `dist/Nadajnik.app`, `dist/Odbiornik.app` and `dist/Transceiver.app` for the
architecture of the Python interpreter used to build them. Select the USB
audio output in the transmitter and the USB audio input in the receiver.
macOS may ask for microphone access when the receiver starts. Both programs
use a 48 kHz audio stream by default, with optional 96/192 kHz sampling. A physical
speaker-to-microphone path or a suitable loopback connection is needed to
receive the transmitter's signal.

## Automated BER and signal-strength measurements

Install the additional plotting dependency with
`.venv\Scripts\python.exe -m pip install -r requirements-experiment.txt`
on Windows, or `.venv/bin/python -m pip install -r requirements-experiment.txt`
on macOS. Open **Nadajnik** and **Odbiornik** first. Check the device numbers with
`python sweep.py --list-devices`, then run, for example:

```sh
.venv/bin/python sweep.py --output-device 0 --input-device 1
```

On Windows use `.venv\Scripts\python.exe` in place of `.venv/bin/python`.
The script controls both visible applications through localhost commands. It
sets the same FSK parameters in both windows, sends the fixed text **Laser
Polarisation Modulation Transceiver** through the selected audio output, and
reads the decoded result from the receiver window. Expected bytes for BER
comparison travel locally between the applications; the message itself still
travels through audio. Microsoft Teams Audio is excluded from automatic device
selection. The default output level is 40%.

The plan uses bit-0 frequencies `100, 150, 300, 700` Hz, then the same pattern
times 10 in each higher decade. Bit 1 is 2× or 3× bit 0. For each pair, the bit
rate is `(bit 1 − bit 0) × 0.25`, `× 0.5`, or `× 0.75`. Settings above 23.9 kHz
or 10,000 bit/s are omitted, leaving 50 combinations. Run
`python sweep.py --dry-run` to inspect the full plan without transmitting.
Fractional bit rates such as 37.5 bit/s are supported.

Each setting has one row in `measurements/ber_sweep_gui.csv`, updated after
each attempt, with bit-0 and bit-1 frequencies, bit rate, output amplitude,
BER, error count, received RMS in dBFS, status, and attempt count. The script also creates two PNG plots next
to the CSV. A `no_frame` row has no BER: no data frame was recognized, so that
measurement is **pending**, not a zero-error result. The script tries it up to
three times per run. Use `--resume` to retry pending rows after an interruption
or later hardware change; completed rows stay intact. `id_mismatch` means a
frame was recognized but its audio ID was damaged; during an automated trial,
the one local reference still allows payload BER to be measured. Use
`--retry-status id_mismatch` with `--resume` to repeat a particular status.

For a small controlled subset, repeat `--only ZERO,ONE,BPS` and choose a
separate `--output` path. `--amplitude 0.6` sets the digital output level to
60%. The RMS value is the *received* AC level over the trial; it is not the
normalized height of the oscilloscope trace or a voltage measurement. Higher
output level can improve a weak signal, but it does not guarantee successful
decoding. `--headless` runs the same modem and audio path without the windows.

The 41-byte one-transmission study is in `measurements/ber_1x_summary.csv` and
its two plots. It used the USB audio input and output on the test Mac at 40%
output. The raw log and frame counts are kept alongside the summary. Earlier
sweep and amplitude checks were exploratory.

### One fresh transmission per setting

With both applications open, run:

```sh
.venv/bin/python repeat_sweep.py --output-device 0 --input-device 1
```

This sends the same text **once for every one of the 50 settings** at 40%
output. Every transmission, including `no_frame`, is appended to
`measurements/ber_1x_raw.csv`. The script updates
`measurements/ber_1x_summary.csv` with **exactly five columns**:
`bit_0_hz`, `bit_1_hz`, `speed_bps`, `ber_percent`, and `signal_rms_dbfs`.
For a recognized frame, BER is calculated from wrong payload bits divided by
compared bits. A `no_frame` transmission is assigned **100% in the summary and
plots** as a frame-loss penalty. This is a scoring convention, not a measured
bit error rate; its BER remains blank in the raw log. A setting with no
transmission yet stays blank in the summary. With multiple transmissions per
setting, the summary averages their BER scores. Received signal strength is
the measured RMS level in dBFS. A separate
`measurements/ber_1x_coverage.csv` reports the number of transmitted,
recognized, and comparable frames per setting. The two charts are generated
from the five-column summary. Use `--resume` to continue an interrupted run;
the script does not repeat already logged transmissions. For a later repeated
study, set `--transmissions 10` and use a different `--output` name; its
five-column table averages BER scores and received signal power across all
attempts. Each chart combines all settings on one speed axis and labels each
point with its bit-1 frequency (`k` means 1000 Hz); color represents bit 0.

In the recorded `1x` run, 28 of 50 transmissions produced a recognizable
frame and 22 were `no_frame`. The summary scores those 22 settings as 100% BER;
the signal level is present for all 50. The fixed text contains 41 UTF-8 bytes
(328 payload bits), before protocol overhead.

### 128-byte message scan

`measurements/test_message_128B.txt` contains exactly 128 UTF-8 bytes. To send
it once for each setting at the same 40% output level, run:

```sh
.venv/bin/python repeat_sweep.py --output-device 0 --input-device 1 \
  --message-file measurements/test_message_128B.txt \
  --output measurements/ber_128B_1x_raw.csv
```

This creates `ber_128B_1x_summary.csv` with the same five columns as the 41-byte
scan, plus a raw log, frame-count CSV, two plots, and a metadata JSON file. The
metadata records the exact message, its byte length and SHA-256 hash, amplitude,
and device IDs. Resume with the same arguments and `--resume` after an
interruption; the script checks the metadata before sending more audio.

The recorded `128B` study completed one transmission for each of 50 settings.
The receiver recognized 27 frames; the 23 `no_frame` settings score 100% BER in
the summary and plots while their raw BER fields stay blank.
Received signal level is recorded for all 50 settings. A temporary USB audio
stream error interrupted the run after 31 settings; the applications were
restarted and the remaining 19 settings were measured from the saved log.

### Measurements from a file

Create a UTF-8 plan with one transmission per data line. Use three columns,
`bit_0_hz,bit_1_hz,speed_bps`; a header is optional. Repeated identical lines
still produce separate transmissions. See `measurements/plan_example.csv`.

You can run the plan directly from the two desktop windows:

1. In **Nadajnik**, choose the output device and the text to send. Use either
   the text field or **Plik UTF-8** to select a message file. Set the output
   level there as well.
2. In **Odbiornik**, choose the microphone. Under **Pomiary z pliku**, select
   the plan CSV and the destination for the results CSV, then click **Start**.
   Each plan row causes one transmission. The receiver shows the current row
   and the number of completed measurements.
3. Click **Stop** to interrupt the run. Click **Start** again with the same plan,
   message, devices, level, and result path to continue unfinished rows.

The selected results path stores the detailed `*_raw.csv` log. A five-column
`*_summary.csv` is saved beside it with bit 0 and bit 1 frequencies, speed,
BER, and received signal level. **Zapisz skrót CSV** in the receiver lets you
save another copy of that summary wherever you choose. A `*_metadata.json`
file records the plan and message used for safe resumption. The transmitter
and receiver must both be open on the same computer during the run.

The command-line version remains available:

```sh
.venv/bin/python file_sweep.py --plan-file measurements/plan_example.csv \
  --message-file measurements/test_message_128B.txt \
  --output measurements/my_measurements_raw.csv
```

Use `--dry-run` to validate and list every planned transmission without audio.
The output includes a raw CSV with the source line number, a five-column summary
with one row per plan line, a metadata JSON file, and two plots. `no_frame`
receives a 100% score in the summary while its raw BER stays blank. Use
`--resume` with the same plan, message, and output path to continue after an
interruption. The script checks the plan and message hashes before resuming.

## Test the protocol

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests check UTF-8 text reception with arbitrary audio block boundaries
and noise, BER for ordinary and damaged test frames, a 10,000 bit/s synthetic channel,
and rejection of messages with an invalid checksum. They do not
replace a test using a physical speaker and microphone.
