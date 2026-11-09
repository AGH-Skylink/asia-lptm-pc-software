"""Measure every FSK setting through the visible desktop applications."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from math import log10
import os
from pathlib import Path

from sweep import (_run_gui_trial, _select_device, make_plots, plan)


RAW_COLUMNS = (
    "bit_0_hz", "bit_1_hz", "speed_bps", "speed_factor", "tx_amplitude",
    "attempt", "input_device", "output_device", "status", "ber_percent",
    "bit_errors", "compared_bits", "signal_rms_dbfs", "noise_rms_dbfs",
    "crc_ok", "received_text", "message_id", "measured_at_utc",
)
SUMMARY_COLUMNS = ("bit_0_hz", "bit_1_hz", "speed_bps", "ber_percent", "signal_rms_dbfs")
COVERAGE_COLUMNS = ("bit_0_hz", "bit_1_hz", "speed_bps", "transmissions",
                    "recognized_frames", "comparable_frames")


def read_attempts(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def _row_key(row: dict) -> tuple[str, str, str]:
    return (str(row["bit_0_hz"]), str(row["bit_1_hz"]),
            f"{float(row['speed_bps']):g}")


def aggregate(trials, attempts: list[dict]) -> tuple[list[dict], list[dict]]:
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in attempts:
        grouped[_row_key(row)].append(row)
    summary = []
    coverage = []
    for trial in trials:
        rows = grouped[trial.key]
        comparable = [row for row in rows if row["compared_bits"] != ""]
        bits = sum(int(row["compared_bits"]) for row in comparable)
        errors = sum(int(row["bit_errors"]) for row in comparable)
        rms_powers = [10 ** (float(row["signal_rms_dbfs"]) / 10)
                      for row in rows if row["signal_rms_dbfs"] != ""]
        rms_dbfs = 10 * log10(sum(rms_powers) / len(rms_powers)) if rms_powers else ""
        identity = {"bit_0_hz": trial.zero_hz, "bit_1_hz": trial.one_hz,
                    "speed_bps": f"{trial.speed_bps:g}"}
        summary.append({**identity, "ber_percent": 100 * errors / bits if bits else "",
                        "signal_rms_dbfs": rms_dbfs})
        coverage.append({**identity, "transmissions": len(rows),
                         "recognized_frames": sum(row["status"] != "no_frame" for row in rows),
                         "comparable_frames": len(comparable)})
    return summary, coverage


def _write_csv(path: Path, columns, rows: list[dict]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def _selected_trials(specifications: list[str] | None):
    trials = plan()
    if not specifications:
        return trials
    requested = set()
    for entry in specifications:
        try:
            zero, one, speed = entry.split(",")
            requested.add((str(int(zero)), str(int(one)), f"{float(speed):g}"))
        except ValueError as exc:
            raise ValueError(f"Niepoprawne --only: {entry}; użyj ZERO,ONE,BPS.") from exc
    available = {trial.key for trial in trials}
    if requested - available:
        raise ValueError(f"Ustawienia spoza planu: {sorted(requested - available)}")
    return [trial for trial in trials if trial.key in requested]


def main() -> None:
    parser = argparse.ArgumentParser(description="Pomiary FSK dla każdej kombinacji.")
    parser.add_argument("--input-device", type=int, help="Wejście USB (domyślnie wykrywane).")
    parser.add_argument("--output-device", type=int, help="Wyjście USB (domyślnie wykrywane).")
    parser.add_argument("--amplitude", type=float, default=0.4, help="Amplituda 0–1, domyślnie 0,4.")
    parser.add_argument("--transmissions", type=int, default=1, help="Nadań na kombinację, domyślnie 1.")
    parser.add_argument("--only", action="append", metavar="ZERO,ONE,BPS", help="Ogranicz próbę do wybranego ustawienia.")
    parser.add_argument("--output", type=Path, default=Path("measurements/ber_1x_raw.csv"),
                        help="CSV pojedynczych nadań; tabela 5 kolumn powstanie obok.")
    parser.add_argument("--resume", action="store_true", help="Kontynuuj istniejący dziennik nadań.")
    parser.add_argument("--dry-run", action="store_true", help="Pokaż liczbę planowanych nadań bez audio.")
    args = parser.parse_args()
    try:
        trials = _selected_trials(args.only)
    except ValueError as exc:
        parser.error(str(exc))
    if not 0 < args.amplitude <= 1 or args.transmissions < 1:
        parser.error("Amplituda musi być w (0,1], a liczba nadań dodatnia.")
    if args.dry_run:
        print(f"Kombinacje: {len(trials)}; nadań na kombinację: {args.transmissions}; "
              f"łącznie: {len(trials) * args.transmissions}")
        return
    if args.output.exists() and not args.resume:
        parser.error("Dziennik już istnieje; użyj --resume albo nowej ścieżki.")
    input_device = _select_device("input", args.input_device)
    output_device = _select_device("output", args.output_device)
    attempts = read_attempts(args.output) if args.resume else []
    for row in attempts:
        if (row["tx_amplitude"] != f"{args.amplitude:g}"
                or int(row["input_device"]) != input_device
                or int(row["output_device"]) != output_device):
            parser.error("Istniejący dziennik ma inny poziom lub inne urządzenia audio.")
    summary_path = args.output.with_name(args.output.stem.replace("_raw", "") + "_summary.csv")
    coverage_path = args.output.with_name(args.output.stem.replace("_raw", "") + "_coverage.csv")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.exists():
        _write_csv(args.output, RAW_COLUMNS, [])
    grouped = defaultdict(list)
    for row in attempts:
        grouped[_row_key(row)].append(row)
    planned_remaining = sum(max(0, args.transmissions - len(grouped[trial.key])) for trial in trials)
    count = 0
    for trial in trials:
        while len(grouped[trial.key]) < args.transmissions:
            count += 1
            attempt_number = len(grouped[trial.key]) + 1
            print(f"[{count}/{planned_remaining}] 0={trial.zero_hz} Hz, 1={trial.one_hz} Hz, "
                  f"{trial.speed_bps:g} bit/s, nadanie {attempt_number}/{args.transmissions}", flush=True)
            result = _run_gui_trial(trial, input_device, output_device, args.amplitude)
            result["received_text"] = "".join(
                f"\\u{ord(character):04x}" if ord(character) < 32
                else character for character in result["received_text"])
            row = {**result, "attempt": attempt_number, "input_device": input_device,
                   "output_device": output_device}
            with args.output.open("a", newline="", encoding="utf-8") as target:
                csv.DictWriter(target, fieldnames=RAW_COLUMNS, lineterminator="\n").writerow(row)
                target.flush()
            attempts.append(row)
            grouped[trial.key].append(row)
            summary, coverage = aggregate(trials, attempts)
            _write_csv(summary_path, SUMMARY_COLUMNS, summary)
            _write_csv(coverage_path, COVERAGE_COLUMNS, coverage)
            print(f"  {row['status']}, BER={row['ber_percent']}, RMS={row['signal_rms_dbfs']}", flush=True)
    summary, coverage = aggregate(trials, attempts)
    _write_csv(summary_path, SUMMARY_COLUMNS, summary)
    _write_csv(coverage_path, COVERAGE_COLUMNS, coverage)
    plots = make_plots(summary_path)
    print("Dziennik:", args.output)
    print("Tabela 5 kolumn:", summary_path)
    print("Liczba rozpoznanych ramek:", coverage_path)
    print("Wykresy:", *plots, sep="\n  ")


if __name__ == "__main__":
    main()
