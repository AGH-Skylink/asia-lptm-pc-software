from array import array
import random
import unittest

from modem import (FSKDecoder, MAX_FREQUENCY, TEST_PAYLOAD, ModemConfig,
                   compare_test_bits, crc16, encode_payload, encode_text, fsk_chunks)


class ModemTests(unittest.TestCase):
    def test_crc_known_vector(self):
        self.assertEqual(crc16(b"123456789"), 0x29B1)

    def test_text_survives_noise_and_arbitrary_capture_boundaries(self):
        config = ModemConfig()
        raw = array("f", [0.0] * 713)
        for chunk in fsk_chunks(encode_text("Zażółć gęślą jaźń"), config, 0.55):
            raw.frombytes(chunk)
        rng = random.Random(41)
        for index in range(len(raw)):
            raw[index] += rng.uniform(-0.025, 0.025)
        decoder = FSKDecoder(config)
        data = raw.tobytes()
        decoded = []
        position = 0
        while position < len(data):
            size = rng.randrange(100, 6_000) * 4
            decoded.extend(decoder.feed(data[position:position + size]))
            position += size
        self.assertEqual(decoded, ["Zażółć gęślą jaźń"])

    def test_corrupt_payload_is_rejected(self):
        config = ModemConfig()
        bits = encode_text("TEST")
        bits[80] ^= 1  # first payload bit; checksum is intentionally unchanged
        decoder = FSKDecoder(config)
        decoded = []
        for chunk in fsk_chunks(bits, config, 0.5):
            decoded.extend(decoder.feed(chunk))
        self.assertEqual(decoded, [])

    def test_ber_counts_corrupted_test_bit_even_when_crc_fails(self):
        config = ModemConfig()
        bits = encode_payload(TEST_PAYLOAD)
        bits[80 + 8 * 10] ^= 1
        decoder = FSKDecoder(config)
        frames = []
        for chunk in fsk_chunks(bits, config, 0.5):
            frames.extend(decoder.feed_frames(chunk))
        test_frames = [frame for frame in frames if compare_test_bits(frame.payload) is not None]
        self.assertEqual(len(test_frames), 1)
        self.assertFalse(test_frames[0].crc_ok)
        self.assertEqual(compare_test_bits(test_frames[0].payload), (1, 1024))

    def test_10000_bits_per_second_with_fractional_sample_boundaries(self):
        config = ModemConfig(zero_hz=3000, one_hz=17000, baud=10000)
        raw = array("f", [0.0] * 713)
        for chunk in fsk_chunks(encode_payload(TEST_PAYLOAD), config, 0.5):
            raw.frombytes(chunk)
        rng = random.Random(7)
        for index in range(len(raw)):
            raw[index] += rng.uniform(-0.02, 0.02)
        decoder = FSKDecoder(config)
        data = raw.tobytes()
        frames = []
        position = 0
        while position < len(data):
            size = rng.randrange(100, 2000) * 4
            frames.extend(decoder.feed_frames(data[position:position + size]))
            position += size
        self.assertTrue(any(frame.crc_ok and compare_test_bits(frame.payload) == (0, 1024)
                            for frame in frames))

    def test_frequency_limit_stays_below_nyquist(self):
        self.assertLess(MAX_FREQUENCY, 24000)
        ModemConfig(zero_hz=1000, one_hz=MAX_FREQUENCY).validate()
        with self.assertRaises(ValueError):
            ModemConfig(zero_hz=1000, one_hz=24000, max_hz=24000).validate()
        with self.assertRaises(ValueError):
            ModemConfig(zero_hz=3000, one_hz=17000, baud=10001).validate()
        with self.assertRaises(ValueError):
            ModemConfig(zero_hz=1200, one_hz=2200, baud=10000).validate()


if __name__ == "__main__":
    unittest.main()
