"""Run one acoustic FSK measurement for each line of a user-provided plan."""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path

from modem import MAX_TEXT_BYTES, ModemConfig
from plot_results import make_combined_plots
from repeat_sweep import RAW_COLUMNS, SUMMARY_COLUMNS, _write_csv, read_attempts
from sweep import MESSAGE, Trial, _run_gui_trial, _select_device


PLAN_RAW_COLUMNS = ("plan_line",) + RAW_COLUMNS


def read_plan(path: Path) -> list[tuple[int, Trial]]:
    trials = []
    for line_number, source in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = source.strip()
        if not line or line.startswith("#"):
            continue
        if ";" in line:
            fields = next(csv.reader([line], delimiter=";"))
        elif "," in line:
            fields = next(csv.reader([line]))
        else:
            fields = line.split()
        fields = [field.strip() for field in fields]
        if fields == ["bit_0_hz", "bit_1_hz", "speed_bps"]:
            continue
        if len(fields) != 3:
            raise ValueError(f"Wiersz {line_number}: podaj bit_0_hz,bit_1_hz,speed_bps.")
        try:
            zero, one = int(fields[0]), int(fields[1])
            speed = float(fields[2])
            ModemConfig(zero_hz=zero, one_hz=one, baud=speed).validate()
        except ValueError as exc:
            raise ValueError(f"Wiersz {line_number}: {exc}") from exc
        trials.append((line_number, Trial(zero, one, speed, speed / abs(one - zero))))
    if not trials:
        raise ValueError("Plik planu nie zawiera żadnego pomiaru.")
    return trials


def summary_rows(trials: list[tuple[int, Trial]], attempts: list[dict]) -> list[dict]:
    by_line = {int(row["plan_line"]): row for row in attempts}
    rows = []
    for line_number, trial in trials:
        result = by_line.get(line_number)
        rows.append({"bit_0_hz": trial.zero_hz, "bit_1_hz": trial.one_hz,
                     "speed_bps": f"{trial.speed_bps:g}",
                     "ber_percent": (100 if result["status"] == "no_frame"
                                     else result["ber_percent"]) if result else "",
                     "signal_rms_dbfs": result["signal_rms_dbfs"] if result else ""})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Jeden pomiar audio na wiersz planu CSV.")
    parser.add_argument("--plan-file", type=Path, required=True,
                        help="Wiersze: bit_0_hz,bit_1_hz,speed_bps; nagłówek opcjonalny.")
    parser.add_argument("--message-file", type=Path,
                        help="Tekst UTF-8 do nadania; domyślnie 41-bajtowy wzorzec.")
    parser.add_argument("--input-device", type=int)
    parser.add_argument("--output-device", type=int)
    parser.add_argument("--amplitude", type=float, default=0.4)
    parser.add_argument("--output", type=Path, default=Path("measurements/file_sweep_raw.csv"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        trials = read_plan(args.plan_file)
        message = args.message_file.read_text(encoding="utf-8") if args.message_file else MESSAGE
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    if not message or len(message.encode("utf-8")) > MAX_TEXT_BYTES:
        parser.error(f"Wiadomość musi mieć 1–{MAX_TEXT_BYTES} bajtów UTF-8.")
    if not 0 < args.amplitude <= 1:
        parser.error("Amplituda musi być w zakresie (0,1].")
    if args.dry_run:
        print(f"Pomiarów: {len(trials)}; wiadomość: {len(message.encode('utf-8'))} bajtów")
        for line_number, trial in trials:
            print(f"wiersz {line_number}: {trial.zero_hz}/{trial.one_hz} Hz, "
                  f"{trial.speed_bps:g} bit/s")
        return
    if args.output.exists() and not args.resume:
        parser.error("Dziennik już istnieje; użyj --resume albo innej ścieżki.")
    input_device = _select_device("input", args.input_device)
    output_device = _select_device("output", args.output_device)
    summary_path = args.output.with_name(args.output.stem.replace("_raw", "") + "_summary.csv")
    metadata_path = args.output.with_name(args.output.stem.replace("_raw", "") + "_metadata.json")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"plan_sha256": sha256(args.plan_file.read_bytes()).hexdigest(),
                "plan_rows": len(trials), "message": message,
                "message_sha256": sha256(message.encode("utf-8")).hexdigest(),
                "amplitude": args.amplitude, "input_device": input_device,
                "output_device": output_device}
    if args.resume:
        if not metadata_path.exists() or json.loads(metadata_path.read_text(encoding="utf-8")) != metadata:
            parser.error("Plan, wiadomość lub urządzenia nie zgadzają się z istniejącym dziennikiem.")
    else:
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        _write_csv(args.output, PLAN_RAW_COLUMNS, [])
    attempts = read_attempts(args.output)
    completed = {int(row["plan_line"]) for row in attempts}
    for index, (line_number, trial) in enumerate(trials, 1):
        if line_number in completed:
            continue
        print(f"[{index}/{len(trials)}] wiersz {line_number}: {trial.zero_hz}/{trial.one_hz} Hz, "
              f"{trial.speed_bps:g} bit/s", flush=True)
        result = _run_gui_trial(trial, input_device, output_device, args.amplitude, message)
        result["received_text"] = "".join(f"\\u{ord(char):04x}" if ord(char) < 32 else char
                                          for char in result["received_text"])
        row = {"plan_line": line_number, **result, "attempt": 1,
               "input_device": input_device, "output_device": output_device}
        with args.output.open("a", newline="", encoding="utf-8") as target:
            csv.DictWriter(target, fieldnames=PLAN_RAW_COLUMNS, lineterminator="\n").writerow(row)
        attempts.append(row)
        _write_csv(summary_path, SUMMARY_COLUMNS, summary_rows(trials, attempts))
        print(f"  {row['status']}; BER={row['ber_percent']}; RMS={row['signal_rms_dbfs']}", flush=True)
    _write_csv(summary_path, SUMMARY_COLUMNS, summary_rows(trials, attempts))
    charts = make_combined_plots(summary_path, f"{len(message.encode('utf-8'))} B, nadajnik {args.amplitude * 100:g}%")
    print("Dziennik:", args.output, "\nSkrót:", summary_path,
          "\nMetadane:", metadata_path, "\nWykresy:", *charts, sep="\n")


if __name__ == "__main__":
    main()
