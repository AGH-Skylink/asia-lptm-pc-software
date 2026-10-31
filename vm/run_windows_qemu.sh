#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
vm_dir="$project_dir/vm"
iso="$vm_dir/windows11-ltsc-eval.iso"
disk="$vm_dir/windows11.qcow2"
vars="$vm_dir/uefi-vars.fd"
exchange_iso="$vm_dir/exchange.iso"
tpm_socket="$vm_dir/tpm/swtpm-sock"
firmware="$(brew --prefix qemu)/share/qemu/edk2-x86_64-code.fd"

for file in "$iso" "$disk" "$vars" "$firmware" "$exchange_iso"; do
    if [[ ! -f "$file" ]]; then
        echo "Brakuje pliku: $file" >&2
        exit 1
    fi
done

mkdir -p "$vm_dir/tpm"
if [[ ! -S "$tpm_socket" ]]; then
    swtpm socket \
        --tpmstate "dir=$vm_dir/tpm" \
        --ctrl "type=unixio,path=$tpm_socket" \
        --pid "file=$vm_dir/tpm/swtpm.pid" \
        --tpm2 --daemon
fi

audio_args=(-audiodev none,id=silent)
if [[ "${QEMU_CAPTURE:-0}" == "1" ]]; then
    audio_args+=(-audiodev "wav,id=capture,path=$vm_dir/guest-output.wav")
fi
audio_args+=(-device ich9-intel-hda,id=hda0)
if [[ "${QEMU_CAPTURE_PRIMARY:-0}" == "1" ]]; then
    audio_args+=(-device hda-output,bus=hda0.0,audiodev=capture)
else
    audio_args+=(-device hda-duplex,bus=hda0.0,audiodev=silent)
fi
if [[ "${QEMU_CAPTURE:-0}" == "1" ]]; then
    audio_args+=(-device ich9-intel-hda,id=hda1)
    if [[ "${QEMU_CAPTURE_PRIMARY:-0}" == "1" ]]; then
        audio_args+=(-device hda-duplex,bus=hda1.0,audiodev=silent)
    else
        audio_args+=(-device hda-output,bus=hda1.0,audiodev=capture)
    fi
fi

exec qemu-system-x86_64 \
    -machine q35 -accel tcg,thread=multi -cpu max -smp 4 -m 8192 \
    -drive "if=pflash,unit=0,format=raw,readonly=on,file=$firmware" \
    -drive "if=pflash,unit=1,format=raw,file=$vars" \
    -drive "if=none,id=system,format=qcow2,file=$disk" \
    -drive "if=none,id=install,format=raw,media=cdrom,readonly=on,file=$iso" \
    -drive "if=none,id=share,format=raw,media=cdrom,readonly=on,file=$exchange_iso" \
    -device ich9-ahci,id=ahci \
    -device ide-hd,drive=system,bus=ahci.0 \
    -device ide-cd,drive=install,bus=ahci.1 \
    -device ide-cd,drive=share,bus=ahci.2 \
    "${audio_args[@]}" \
    -chardev "socket,id=chrtpm,path=$tpm_socket" \
    -tpmdev emulator,id=tpm0,chardev=chrtpm \
    -device tpm-tis,tpmdev=tpm0 \
    -netdev user,id=net0 \
    -device e1000,netdev=net0 \
    -device qemu-xhci,id=xhci -device usb-tablet,bus=xhci.0 \
    -boot order=cd,menu=on \
    -object "secret,id=vncpass,data=${QEMU_VNC_PASSWORD:-Sound123}" \
    -display none -vnc 127.0.0.1:1,password-secret=vncpass \
    -monitor stdio
