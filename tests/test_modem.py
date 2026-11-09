from array import array
import random
import unittest

from ipc_reference import ID_BYTES
from modem import (FSKDecoder, HEADER, MAX_FREQUENCY, PROBE, TEST_PAYLOAD, ModemConfig,
                   compare_payload_bits, compare_test_bits, crc16, encode_payload, encode_text, fsk_chunks)


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
        bits[len(HEADER) + len(PROBE) + ID_BYTES * 8 + 16] ^= 1  # first payload bit
        decoder = FSKDecoder(config)
        decoded = []
        for chunk in fsk_chunks(bits, config, 0.5):
            decoded.extend(decoder.feed(chunk))
        self.assertEqual(decoded, [])

    def test_single_message_is_not_duplicated_across_capture_blocks(self):
        config = ModemConfig()
        message = "Laser Polarisation Modulation Transceiver"
        pcm = b"".join(fsk_chunks(encode_text(message), config, 0.4))
        for offset in (0, 713, 960, 1919):
            decoder = FSKDecoder(config)
            stream = array("f", [0.0] * offset).tobytes() + pcm
            found = []
            for start in range(0, len(stream), 2048 * 4):
                found.extend(decoder.feed(stream[start:start + 2048 * 4]))
            self.assertEqual(found, [message], f"capture offset {offset}")

    def test_ber_counts_corrupted_test_bit_even_when_crc_fails(self):
        config = ModemConfig()
        bits = encode_payload(TEST_PAYLOAD)
        bits[len(HEADER) + len(PROBE) + ID_BYTES * 8 + 16 + 8 * 10] ^= 1
        decoder = FSKDecoder(config)
        frames = []
        for chunk in fsk_chunks(bits, config, 0.5):
            frames.extend(decoder.feed_frames(chunk))
        test_frames = [frame for frame in frames if compare_test_bits(frame.payload) is not None]
        self.assertEqual(len(test_frames), 1)
        self.assertFalse(test_frames[0].crc_ok)
        self.assertEqual(compare_test_bits(test_frames[0].payload), (1, 1024))
        self.assertEqual(test_frames[0].probe_errors, 0)

    def test_ordinary_message_reports_probe_ber(self):
        config = ModemConfig()
        bits = encode_text("Laser Polarisation Modulation Transceiver")
        bits[len(HEADER) + 17] ^= 1
        decoder = FSKDecoder(config)
        frames = []
        for chunk in fsk_chunks(bits, config, 0.5):
            frames.extend(decoder.feed_frames(chunk))
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0].crc_ok)
        self.assertEqual(frames[0].probe_errors, 1)
        self.assertEqual(frames[0].probe_bits, 128)

    def test_message_id_and_local_reference_compare_actual_data(self):
        message_id = bytes.fromhex("0102030405060708")
        expected = b"Laser Polarisation Modulation Transceiver"
        bits = encode_payload(expected, message_id)
        bits[len(HEADER) + len(PROBE) + ID_BYTES * 8 + 16 + 8 * 9] ^= 1
        decoder = FSKDecoder(ModemConfig())
        frames = []
        for chunk in fsk_chunks(bits, ModemConfig(), 0.5):
            frames.extend(decoder.feed_frames(chunk))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].message_id, message_id)
        self.assertFalse(frames[0].crc_ok)
        self.assertEqual(compare_payload_bits(frames[0].payload, expected), (1, len(expected) * 8))

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
