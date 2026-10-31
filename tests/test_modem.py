from array import array
import random
import unittest

from modem import FSKDecoder, ModemConfig, crc16, encode_text, fsk_chunks


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


if __name__ == "__main__":
    unittest.main()
