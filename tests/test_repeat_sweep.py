import unittest

from repeat_sweep import SUMMARY_COLUMNS, aggregate
from sweep import plan


class RepeatedSweepTests(unittest.TestCase):
    def test_five_column_summary_counts_only_recognized_bits_for_ber(self):
        trial = plan()[0]
        identity = {"bit_0_hz": "100", "bit_1_hz": "200", "speed_bps": "25"}
        attempts = [
            {**identity, "status": "no_frame", "bit_errors": "", "compared_bits": "",
             "signal_rms_dbfs": "-60"},
            {"bit_0_hz": 100, "bit_1_hz": 200, "speed_bps": 25,
             "status": "id_mismatch", "bit_errors": 1, "compared_bits": 328,
             "signal_rms_dbfs": "-54"},
        ]
        summary, coverage = aggregate([trial], attempts)
        self.assertEqual(len(SUMMARY_COLUMNS), 5)
        self.assertEqual(set(summary[0]), set(SUMMARY_COLUMNS))
        self.assertAlmostEqual(summary[0]["ber_percent"], 100 / 328)
        self.assertEqual(coverage[0]["transmissions"], 2)
        self.assertEqual(coverage[0]["recognized_frames"], 1)
        self.assertEqual(coverage[0]["comparable_frames"], 1)
        self.assertGreater(summary[0]["signal_rms_dbfs"], -60)
        self.assertLess(summary[0]["signal_rms_dbfs"], -54)

    def test_no_recognized_frame_has_blank_ber(self):
        trial = plan()[0]
        attempts = [{"bit_0_hz": "100", "bit_1_hz": "200", "speed_bps": "25",
                     "status": "no_frame", "bit_errors": "", "compared_bits": "",
                     "signal_rms_dbfs": "-55"}]
        summary, coverage = aggregate([trial], attempts)
        self.assertEqual(summary[0]["ber_percent"], "")
        self.assertEqual(coverage[0]["recognized_frames"], 0)


if __name__ == "__main__":
    unittest.main()
