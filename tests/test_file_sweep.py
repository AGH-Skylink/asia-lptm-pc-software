import tempfile
import unittest
from pathlib import Path

from file_sweep import read_plan, summary_rows


class FileSweepTests(unittest.TestCase):
    def test_each_line_is_one_measurement_even_for_duplicate_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.csv"
            path.write_text("bit_0_hz,bit_1_hz,speed_bps\n100,200,25\n100,200,25\n",
                            encoding="utf-8")
            trials = read_plan(path)
        self.assertEqual([line for line, _ in trials], [2, 3])
        attempts = [{"plan_line": "2", "status": "no_frame", "ber_percent": "",
                     "signal_rms_dbfs": "-60"},
                    {"plan_line": "3", "status": "ok", "ber_percent": "0",
                     "signal_rms_dbfs": "-59"}]
        summary = summary_rows(trials, attempts)
        self.assertEqual([row["ber_percent"] for row in summary], [100, "0"])

    def test_invalid_frequency_is_rejected_with_line_number(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.csv"
            path.write_text("100,200,25\n100,24000,100\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Wiersz 2"):
                read_plan(path)


if __name__ == "__main__":
    unittest.main()
