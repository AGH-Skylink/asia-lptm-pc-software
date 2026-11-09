# Acoustic transmitter and receiver

Two desktop applications for Windows 11 and macOS. The transmitter can play
an audio file, generate a sine wave from 0 to 23.9 kHz, and send text through a
speaker using FSK. The receiver captures microphone input, decodes text,
displays a normalized waveform and a signal strength meter, measures bit error
rate (BER) on every FSK frame, saves received text, and can optionally monitor
the microphone through a speaker.

## Run from source

Install Python 3.11 or newer. In the project directory on Windows, run:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe transmitter.py
```

Start the receiver in a second terminal window with
`.venv\Scripts\python.exe receiver.py`.

Run the applications on separate computers or use two audio devices. If both
applications run on one computer, select separate input and output devices.
Set the same frequencies for bits `0` and `1` and the same bit rate in both
windows. Start the receiver first, then click **Wyślij tekst** (Send text) in
the transmitter. The default 1200/2200 Hz and 25 bits/s are a starting point.
The bit rate can be set from 5 to 10,000 bits/s. At higher rates, the bit 0
and bit 1 frequencies must be farther apart. For 10,000 bits/s, try
3,000/17,000 Hz with a direct audio connection; actual speakers and
microphones may not carry these frequencies or this data rate reliably.
Reception depends on volume, microphone, distance, and ambient noise. Longer
messages take proportionally longer to transmit. The maximum message size is
2048 UTF-8 bytes.

The level slider sets digital amplitude as a percentage. The physical output
voltage depends on the sound card, operating system settings, and amplifier;
displaying volts would require measurement and calibration. A 23.9 kHz signal
is just below the 24 kHz Nyquist limit of the 48 kHz sample rate; exactly
24 kHz cannot be generated as a usable sine wave. Ordinary speakers and
microphones may not reproduce the top of this range. For monitoring, use headphones
or keep the level low to avoid acoustic feedback.

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
replaces it. If CRC fails, the received-text box remains empty. Both
applications must use the same protocol version. The signal
meter shows AC peak and RMS in dBFS after removal of DC offset and slow drift.
The scope filters out frequencies well below the configured FSK tones, hides
background noise, and normalizes blocks whose filtered level exceeds its noise
gate. The filter affects only the display and meter, not demodulation.

An audio file is **played locally**; it is not transmitted as data for the
receiver to reconstruct. Supported formats depend on the libsndfile library
bundled with `soundfile`. WAV is the safest choice.

## Build the two Windows executables

Run `build_windows.bat` on Windows. The resulting files are
`dist\Nadajnik.exe` and `dist\Odbiornik.exe`. PyInstaller must build on
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
```

The build creates `dist/Nadajnik.app` and `dist/Odbiornik.app` for the
architecture of the Python interpreter used to build them. Select the USB
audio output in the transmitter and the USB audio input in the receiver.
macOS may ask for microphone access when the receiver starts. Both programs
use a 48 kHz audio stream for FSK transmission and reception. A physical
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
attempts. Each chart uses a separate panel for each bit-0 frequency and labels
every plotted point with its bit-1 frequency in hertz.

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

## Test the protocol

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests check UTF-8 text reception with arbitrary audio block boundaries
and noise, BER for ordinary and damaged test frames, a 10,000 bit/s synthetic channel,
and rejection of messages with an invalid checksum. They do not
replace a test using a physical speaker and microphone.
