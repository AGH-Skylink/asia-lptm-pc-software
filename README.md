# Acoustic transmitter and receiver

Two desktop applications for Windows 11 and macOS. The transmitter can play
an audio file, generate a sine wave from 0 to 23.9 kHz, and send text through a
speaker using FSK. The receiver captures microphone input, decodes text,
displays a normalized waveform and a signal strength meter, measures bit error
rate (BER) from a known test frame, saves received text, and can optionally monitor
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

To measure BER, start the receiver with the same FSK settings as the
transmitter, then click **Wyślij test BER** (Send BER test) in the transmitter.
The receiver compares the 1,024 known data bits in each recognized test frame
with the expected pattern. It shows wrong bits, total compared bits, frame
count, and checksum failures. The BER excludes frames whose preamble or test
marker is too damaged to recognize; it is a BER for recognized frames, not a
measurement of lost frames. **Wyzeruj BER** resets the counters. The signal
meter shows peak and RMS in dBFS. The oscilloscope rescales each displayed
block to its own peak; its gain indicator shows how much it was enlarged.

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

## Test the protocol

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests check UTF-8 text reception with arbitrary audio block boundaries
and noise, BER for a damaged test frame, a 10,000 bit/s synthetic channel,
and rejection of messages with an invalid checksum. They do not
replace a test using a physical speaker and microphone.
