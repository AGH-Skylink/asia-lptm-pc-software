from array import array
from math import pi, sin
import unittest

from audio_runtime import HighPass, ac_metrics


class AudioMetricsTests(unittest.TestCase):
    def test_dc_offset_does_not_count_as_signal(self):
        offset, peak, rms = ac_metrics(array("f", [0.0064] * 100))
        self.assertAlmostEqual(offset, 0.0064, places=6)
        self.assertAlmostEqual(peak, 0.0, places=6)
        self.assertAlmostEqual(rms, 0.0, places=6)

    def test_alternating_signal_is_measured_after_dc_removal(self):
        offset, peak, rms = ac_metrics(array("f", [0.3, 0.5] * 50))
        self.assertAlmostEqual(offset, 0.4, places=6)
        self.assertAlmostEqual(peak, 0.1, places=6)
        self.assertAlmostEqual(rms, 0.1, places=6)

    def test_scope_filter_suppresses_slow_drift_and_preserves_fsk_tone(self):
        slow = array("f", (0.01 * sin(2 * pi * 20 * n / 48000) for n in range(24000)))
        tone = array("f", (0.001 * sin(2 * pi * 1200 * n / 48000) for n in range(24000)))
        slow_filtered = HighPass(400).process(slow)
        tone_filtered = HighPass(400).process(tone)
        self.assertLess(ac_metrics(slow_filtered[12000:])[2], 0.0005)
        self.assertGreater(ac_metrics(tone_filtered[12000:])[2], 0.0005)

    def test_scope_filter_keeps_state_between_audio_blocks(self):
        samples = array("f", (sin(2 * pi * 1200 * n / 48000) for n in range(4096)))
        whole = HighPass(400).process(samples)
        filter_in_blocks = HighPass(400)
        chunks = filter_in_blocks.process(samples[:2048]) + filter_in_blocks.process(samples[2048:])
        self.assertEqual(whole, chunks)


if __name__ == "__main__":
    unittest.main()
