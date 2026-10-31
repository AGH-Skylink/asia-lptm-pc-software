# Simulating Windows 11 x64 with QEMU on macOS

This VM is independent of VirtualBox. The `windows11.qcow2` image stores the
guest operating system; `uefi-vars.fd` and the `tpm/` directory store firmware
and TPM state. `run_windows_qemu.sh` starts UEFI, TPM 2.0, an Intel HDA duplex
audio device, NAT networking, and a VNC display at `127.0.0.1:5901`.
`QEMU_CAPTURE=1` adds a second audio device whose output is captured to a WAV
file. `QEMU_CAPTURE=1 QEMU_CAPTURE_PRIMARY=1` captures the first device while
keeping the second as an additional device.

The first device has virtual input and output connected to a silent backend.
In capture mode, the second device writes its output to `guest-output.wav`
unless `QEMU_CAPTURE_PRIMARY=1` is set. The first device's virtual input
provides silence. The first test stage confirms that both applications detect
the devices; the second checks the signal sent from Windows in a captured WAV
file.

The `exchange/` directory is turned into `exchange.iso`, which appears in
Windows as a read-only CD. Rebuild the image after changing files in the
directory:

```sh
hdiutil makehybrid -udf -ov -o vm/exchange.iso vm/exchange
```

It contains the application source files, a Python installer, and Windows
packages. Test results and executables return to `vm/results/` through a
local HTTP server. The read-only image avoids a QEMU emulated FAT filesystem
crash observed while unpacking the Python installer.

After downloading the Windows ISO, run:

```sh
python3 vm/receive_results.py
```

In a second terminal:

```sh
./vm/run_windows_qemu.sh
open vnc://127.0.0.1:5901
```

macOS Screen Sharing will ask for the VNC password: `Sound123`. To change it,
start QEMU with `QEMU_VNC_PASSWORD=newpass ./vm/run_windows_qemu.sh`.
The VNC protocol uses at most the first eight characters of the password.
The connection is available only on this Mac.

The installer may report that the emulated CPU does not meet Windows 11
requirements. On the first installer screen, press `Shift+F10` and enter:

```cmd
reg add HKLM\SYSTEM\Setup\LabConfig /v BypassTPMCheck /t REG_DWORD /d 1 /f
reg add HKLM\SYSTEM\Setup\LabConfig /v BypassSecureBootCheck /t REG_DWORD /d 1 /f
reg add HKLM\SYSTEM\Setup\LabConfig /v BypassCPUCheck /t REG_DWORD /d 1 /f
reg add HKLM\SYSTEM\Setup\LabConfig /v BypassRAMCheck /t REG_DWORD /d 1 /f
reg add HKLM\SYSTEM\Setup\LabConfig /v BypassStorageCheck /t REG_DWORD /d 1 /f
exit
```

Then select `Windows 11 Enterprise LTSC Evaluation` and the 80 GB
`Disk 0 Unallocated Space`. `exchange.iso` contains the project files.

After installing Windows, shut down the VM and restart it with
`QEMU_CAPTURE=1 ./vm/run_windows_qemu.sh` to check the second virtual speaker
and capture the transmitter signal. To capture the first device, which is
also visible through MME and DirectSound, use
`QEMU_CAPTURE=1 QEMU_CAPTURE_PRIMARY=1 ./vm/run_windows_qemu.sh`.

In Windows, open the additional CD and run `install_and_probe.cmd`. The
script copies the installer to the Windows disk, installs Python 3.13 and
offline packages, runs the tests, and sends `device-report.json` to
`vm/results/` on the Mac. `build_apps.cmd` builds both executables and sends
them to `vm/results/` as well. After transmitting text through the captured
output, shut down the VM and check the WAV file:

```sh
.venv/bin/python vm/check_capture.py
```

Tested in a Windows 11 x64 QEMU guest: both executables started, the device
report showed virtual inputs and outputs, and the transmitter sent `TEST`
through the first device. The captured file was 5.33 seconds long with a peak
level of about 0.40; the decoder recovered `TEST`. Results are in
`results/device-report.json`, `results/unit-tests.txt`, and
`results/capture-report.json`. QEMU's WAV backend wrote zero lengths in the
RIFF header; `check_capture.py` repairs the header in a
`guest-output-fixed.wav` copy without changing the samples. The virtual
input provides silence, so this test does not cover the physical
speaker-to-microphone path.

Windows 11 Enterprise LTSC Evaluation is an official Microsoft image for
90-day testing. Running x86 on an ARM Mac uses TCG software emulation, so
installation and operation can be slow.
