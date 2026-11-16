from pathlib import Path
import tempfile
from types import MethodType, SimpleNamespace
import unittest

from modem import ReceiveProgress
from receiver import Receiver


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Text:
    def delete(self, *args):
        self.value = ""

    def insert(self, index, value):
        self.value = value


class ReceiverStreamTests(unittest.TestCase):
    def test_utf8_partial_characters_log_incrementally_and_bad_crc_stays_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "received.txt"
            app = SimpleNamespace(received=None, received_crc=None, received_ber="—", showing_file=False,
                result=Text(), fsk=SimpleNamespace(encoding=Value("utf-8")), references={},
                receive_detail=Value(""), autosave=Value(True), autosave_path=Value(str(path)),
                logged_key=None, logged_text="", logged_final=False)
            app._received_report = MethodType(Receiver._received_report, app)
            app._log_progress = MethodType(Receiver._log_progress, app)
            message_id = b"stream01"
            Receiver._show_progress(app, ReceiveProgress(message_id, b"Za\xc5", 4, 1, 128))
            self.assertEqual(app.result.value, "Za")
            self.assertTrue(path.read_text(encoding="utf-8").endswith("Za"))
            Receiver._show_progress(app, ReceiveProgress(message_id, "Zaż".encode(), 4, 1, 128), False)
            self.assertEqual(app.result.value, "Zaż")
            report = path.read_text(encoding="utf-8")
            self.assertIn("Zaż\n", report)
            self.assertIn("Bajty: 4/4", report)
            self.assertIn("CRC: BŁĘDNE", report)
            self.assertIn("BER wzorca", report)
            # A lagging timing candidate must not overwrite the final frame.
            Receiver._show_progress(app, ReceiveProgress(message_id, b"Za", 4, 1, 128))
            self.assertEqual(app.result.value, "Zaż")
