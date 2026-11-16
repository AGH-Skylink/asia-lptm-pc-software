from array import array
import json
from pathlib import Path
from queue import Queue
import tempfile
import unittest

import soundfile as sf

from audio_runtime import WaveRecorder
from modem import FSKDecoder, ModemConfig, encode_payload, fsk_chunks
from transfers import (FILE_MAGIC, FileReceiver, announcement_chunks, bootstrap_config,
                       file_packets, read_settings, settings_packet)


class TransferTests(unittest.TestCase):
    def test_file_saves_automatically_without_end_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(__file__).parent / "fixtures" / "photo.jpg"
            receiver = FileReceiver()
            try:
                for packet in list(file_packets(source))[:-1]:
                    result = receiver.accept(packet, b"photo123", Path(directory))
                self.assertIn("SHA-256 OK", result)
                self.assertTrue(receiver.completed)
                self.assertEqual((Path(directory) / "photo.jpg").read_bytes(), source.read_bytes())
            finally:
                receiver.close()

    def test_late_missing_block_saves_after_end_and_preserves_later_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(__file__).parent / "fixtures" / "photo.jpg"
            packets = list(file_packets(source))
            receiver = FileReceiver()
            try:
                receiver.accept(packets[0], b"photo123", Path(directory))
                receiver.accept(packets[2], b"photo123", Path(directory))
                with self.assertRaisesRegex(ValueError, "brakuje 1"):
                    receiver.accept(packets[-1], b"photo123", Path(directory))
                self.assertIsNotNone(receiver.target)
                receiver.accept(packets[1], b"photo123", Path(directory))
                self.assertEqual((Path(directory) / "photo.jpg").read_bytes(), source.read_bytes())
            finally:
                receiver.close()

    def test_repeated_packets_recover_missing_copy_and_end_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(__file__).parent / "fixtures" / "photo.jpg"
            receiver = FileReceiver()
            for index, packet in enumerate(file_packets(source)):
                if index != 1:  # Simulate loss of the first copy of one data block.
                    receiver.accept(packet, b"photo123", Path(directory))
                result = receiver.accept(packet, b"photo123", Path(directory))
            self.assertIn("SHA-256 OK", result)
            self.assertEqual((Path(directory) / "photo.jpg").read_bytes(), source.read_bytes())
            self.assertFalse(list(Path(directory).glob("*.part")))

    def test_multiframe_file_survives_modulation_and_arbitrary_capture_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "image.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 9)
            config = ModemConfig(zero_hz=4000, one_hz=22000, baud=10000, modulation="4FSK")
            decoder = FSKDecoder(config)
            receiver = FileReceiver()
            raw = array("f", [0.0] * 713)
            for packet in file_packets(source):
                for chunk in fsk_chunks(encode_payload(packet, b"photo123"), config, .5):
                    raw.frombytes(chunk)
            folder = Path(directory) / "received"
            for start in range(0, len(raw), 997):
                for frame in decoder.feed_frames(raw[start:start + 997].tobytes()):
                    self.assertTrue(frame.crc_ok)
                    receiver.accept(frame.payload, frame.message_id, folder)
            self.assertEqual((folder / "image.png").read_bytes(), source.read_bytes())

    def test_binary_photo_roundtrip_keeps_name_and_verifies_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "zdjęcie.jpg"
            data = b"\xff\xd8" + bytes(range(256)) * 13 + b"\xff\xd9"
            source.write_bytes(data)
            target = FileReceiver()
            for packet in file_packets(source):
                result = target.accept(packet, b"photo123", Path(directory) / "received")
            self.assertIn("SHA-256 OK", result)
            self.assertEqual((Path(directory) / "received" / source.name).read_bytes(), data)
            self.assertFalse(list((Path(directory) / "received").glob("*.part")))

    def test_missing_block_leaves_partial_and_does_not_publish_image(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "picture.png"
            source.write_bytes(bytes(range(256)) * 12)
            packets = list(file_packets(source))
            target = FileReceiver()
            folder = Path(directory) / "received"
            target.accept(packets[0], b"photo123", folder)
            target.accept(packets[1], b"photo123", folder)
            target.accept(packets[3], b"photo123", folder)
            with self.assertRaises(ValueError):
                target.accept(packets[-1], b"photo123", folder)
            self.assertEqual(target.received, 2048)
            self.assertFalse((folder / "picture.png").exists())
            target.close()

    def test_file_header_cannot_escape_target_directory_and_existing_file_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "photo.png"
            source.write_bytes(b"old")
            packets = list(file_packets(source))
            metadata = json.loads(packets[0][len(FILE_MAGIC) + 1:])
            metadata["name"] = "../../photo.png"
            packets[0] = FILE_MAGIC + b"H" + json.dumps(metadata).encode()
            target = FileReceiver()
            for packet in packets:
                target.accept(packet, b"photo123", Path(directory))
            self.assertEqual(source.read_bytes(), b"old")
            self.assertEqual((Path(directory) / "photo_70686f746f313233.png").read_bytes(), b"old")

    def test_settings_are_announced_acoustically_then_new_mode_decodes(self):
        config = ModemConfig(zero_hz=4000, one_hz=10000, baud=2000, modulation="4FSK")
        pcm = b"".join(announcement_chunks(config, "ascii", 0.5))
        frames = FSKDecoder(bootstrap_config()).feed_frames(pcm)
        self.assertEqual(len(frames), 1)
        received, encoding = read_settings(frames[0].payload)
        self.assertEqual((received, encoding), (config, "ascii"))
        frames = FSKDecoder(received).feed_frames(b"".join(fsk_chunks(encode_payload(b"photo"), config, .5)))
        self.assertEqual([f.payload for f in frames if f.crc_ok], [b"photo"])

    def test_invalid_settings_are_rejected(self):
        config = ModemConfig()
        payload = settings_packet(config, "utf-8").replace(b'"baud":25', b'"baud":0')
        with self.assertRaises(ValueError):
            read_settings(payload)

    def test_wav_preserves_raw_samples_and_rate(self):
        errors = Queue()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "capture.wav")
            recorder = WaveRecorder(errors)
            samples = array("f", [0, .25, -.5, .125] * 512)
            recorder.start(path, 192000)
            recorder.feed(samples.tobytes())
            recorder.feed(samples.tobytes())
            recorder.stop()
            with sf.SoundFile(path) as source:
                self.assertEqual(source.samplerate, 192000)
                self.assertEqual(source.channels, 1)
                self.assertEqual(bytes(source.buffer_read(len(samples) * 2, dtype="float32")),
                                 samples.tobytes() * 2)
            self.assertTrue(errors.empty())


if __name__ == "__main__":
    unittest.main()
