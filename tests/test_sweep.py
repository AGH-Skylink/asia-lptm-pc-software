from array import array
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from modem import FSKDecoder, ModemConfig, encode_text, fsk_chunks
from sweep import _existing_rows, _pending_trials, _save_rows, plan


class SweepTests(unittest.TestCase):
    def test_plan_follows_frequency_pattern_and_limits(self):
        trials = plan()
        self.assertEqual(len(trials), 50)
        self.assertEqual((trials[0].zero_hz, trials[0].one_hz, trials[0].speed_bps),
                         (100, 200, 25))
        self.assertIn((150, 300, 37.5),
                      {(trial.zero_hz, trial.one_hz, trial.speed_bps) for trial in trials})
        self.assertEqual((trials[-1].zero_hz, trials[-1].one_hz, trials[-1].speed_bps),
                         (10000, 20000, 7500))
        self.assertNotIn((7000, 21000, 10500),
                         {(trial.zero_hz, trial.one_hz, trial.speed_bps) for trial in trials})

    def test_fractional_bit_rate_decodes(self):
        config = ModemConfig(zero_hz=150, one_hz=300, baud=37.5)
        decoder = FSKDecoder(config)
        signal = array("f", [0.0] * 713)
        for chunk in fsk_chunks(encode_text("X"), config, 0.4):
            signal.frombytes(chunk)
        received = []
        data = signal.tobytes()
        for start in range(0, len(data), 2048 * 4):
            received.extend(decoder.feed(data[start:start + 2048 * 4]))
        self.assertEqual(received, ["X"])

    def test_repeated_measurement_replaces_csv_row(self):
        trials = plan()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            row = {"bit_0_hz": 100, "bit_1_hz": 200, "speed_bps": "25",
                   "status": "id_mismatch"}
            _save_rows(path, {trials[0].key: row}, trials)
            saved = _existing_rows(path)
            self.assertEqual(len(saved), 1)
            saved[trials[0].key]["status"] = "ok"
            _save_rows(path, saved, trials)
            self.assertEqual(len(_existing_rows(path)), 1)
            self.assertEqual(_existing_rows(path)[trials[0].key]["status"], "ok")

    def test_no_frame_remains_pending_but_id_mismatch_counts(self):
        trials = plan()[:3]
        rows = {
            trials[0].key: {"status": "no_frame"},
            trials[1].key: {"status": "id_mismatch"},
        }
        self.assertEqual(_pending_trials(trials, rows, None), [trials[0], trials[2]])
        self.assertEqual(_pending_trials(trials, rows, {"id_mismatch"}), [trials[1]])


if __name__ == "__main__":
    unittest.main()
