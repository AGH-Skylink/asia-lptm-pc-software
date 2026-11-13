"""Find the highest observed FSK speed multiplier for each low-frequency pair."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from ipc_control import RECEIVER_PORT, send_command
from repeat_sweep import RAW_COLUMNS, _write_csv, read_attempts
from sweep import Trial, _run_gui_trial, _select_device, plan


FACTORS = tuple(step / 100 for step in range(100, 4, -5))
SUMMARY_COLUMNS = ("bit_0_hz", "bit_1_hz", "max_multiplier", "speed_bps",
                   "status", "ber_percent", "signal_rms_dbfs", "tested_factors")


def pairs() -> list[tuple[int, int]]:
    return sorted({(trial.zero_hz, trial.one_hz) for trial in plan()
                   if trial.zero_hz < 7000})


def summarize(attempts: list[dict]) -> list[dict]:
    results = []
    for zero, one in pairs():
        rows = [row for row in attempts if int(row["bit_0_hz"]) == zero
                and int(row["bit_1_hz"]) == one]
        recognized = [row for row in rows if row["status"] != "no_frame"]
        best = max(recognized, key=lambda row: float(row["speed_factor"])) if recognized else None
        results.append({"bit_0_hz": zero, "bit_1_hz": one,
                        "max_multiplier": best["speed_factor"] if best else "",
                        "speed_bps": best["speed_bps"] if best else "",
                        "status": best["status"] if best else ("no_frame" if rows else ""),
                        "ber_percent": best["ber_percent"] if best else "",
                        "signal_rms_dbfs": best["signal_rms_dbfs"] if best else "",
                        "tested_factors": len(rows)})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Granica rozpoznania ramki dla bitu 0 poniżej 7 kHz.")
    parser.add_argument("--input-device", type=int, default=1)
    parser.add_argument("--output-device", type=int, default=0)
    parser.add_argument("--amplitude", type=float, default=0.4)
    parser.add_argument("--message-file", type=Path,
                        default=Path("measurements/test_message_128B.txt"))
    parser.add_argument("--output", type=Path,
                        default=Path("measurements/ber_128B_limit_raw.csv"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    message = args.message_file.read_text(encoding="utf-8")
    payload = message.encode("utf-8")
    if not 0 < args.amplitude <= 1:
        parser.error("Amplituda musi być w (0,1].")
    if args.dry_run:
        print(f"Pary: {len(pairs())}; mnożniki: {len(FACTORS)} (1.00 do 0.05, krok 0.05); "
              f"wiadomość: {len(payload)} B")
        return
    input_device = _select_device("input", args.input_device)
    output_device = _select_device("output", args.output_device)
    summary_path = args.output.with_name(args.output.stem.replace("_raw", "") + "_summary.csv")
    metadata_path = args.output.with_name(args.output.stem.replace("_raw", "") + "_metadata.json")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"message": message, "message_bytes": len(payload),
                "message_sha256": sha256(payload).hexdigest(),
                "amplitude": args.amplitude, "input_device": input_device,
                "output_device": output_device, "factor_step": 0.05,
                "minimum_factor": 0.05, "maximum_factor": 1.0,
                "bit_0_limit_hz_exclusive": 7000,
                "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if metadata_path.exists():
        stored = json.loads(metadata_path.read_text(encoding="utf-8"))
        for key, value in metadata.items():
            if key != "started_at_utc" and stored.get(key) != value:
                parser.error(f"Istniejący dziennik ma inną wartość {key}.")
    else:
        if args.output.exists():
            parser.error("Istnieje dziennik bez metadanych; wybierz inną ścieżkę.")
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    if not args.output.exists():
        _write_csv(args.output, RAW_COLUMNS, [])
    attempts = read_attempts(args.output)
    try:
        for index, (zero, one) in enumerate(pairs(), 1):
            for factor in FACTORS:
                rows = [row for row in attempts if int(row["bit_0_hz"]) == zero
                        and int(row["bit_1_hz"]) == one]
                if any(row["status"] != "no_frame" for row in rows):
                    break
                if any(abs(float(row["speed_factor"]) - factor) < 1e-9 for row in rows):
                    continue
                trial = Trial(zero, one, (one - zero) * factor, factor)
                print(f"[{index}/{len(pairs())}] {zero}/{one} Hz, mnożnik {factor:.2f}, "
                      f"{trial.speed_bps:g} bit/s", flush=True)
                row = _run_gui_trial(trial, input_device, output_device, args.amplitude, message)
                row["received_text"] = "".join(
                    f"\\u{ord(char):04x}" if ord(char) < 32 else char
                    for char in row["received_text"])
                row.update({"attempt": 1, "input_device": input_device,
                            "output_device": output_device})
                with args.output.open("a", newline="", encoding="utf-8") as target:
                    csv.DictWriter(target, fieldnames=RAW_COLUMNS, lineterminator="\n").writerow(row)
                    target.flush()
                attempts.append(row)
                _write_csv(summary_path, SUMMARY_COLUMNS, summarize(attempts))
                print(f"  {row['status']} BER={row['ber_percent']}", flush=True)
    finally:
        try:
            send_command(RECEIVER_PORT, {"action": "finish"})
        except OSError:
            pass
    _write_csv(summary_path, SUMMARY_COLUMNS, summarize(attempts))
    print("Wynik:", summary_path, "\nDziennik:", args.output,
          "\nMetadane:", metadata_path)


if __name__ == "__main__":
    main()
