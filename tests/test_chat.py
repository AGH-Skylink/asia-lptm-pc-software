import unittest

from chat import ChatHistory
from modem import ReceiveProgress


class ChatTests(unittest.TestCase):
    def test_partial_utf8_updates_one_message_then_keeps_bad_crc(self):
        history = ChatHistory()
        identity = b"remote01"
        history.receive(ReceiveProgress(identity, b"Za\xc5", 4, 1, 128), None, "utf-8")
        message = next(iter(history.messages.values()))
        self.assertEqual(message.text, "Za")
        history.receive(ReceiveProgress(identity, "Zaż".encode(), 4, 1, 128), False, "utf-8")
        self.assertEqual(len(history.messages), 1)
        message = next(iter(history.messages.values()))
        self.assertEqual((message.text, message.state, message.byte_count), ("Zaż", "Błędne CRC", 4))
        self.assertFalse(history.receive(ReceiveProgress(identity, b"Za", 4, 1, 128), None, "utf-8"))

    def test_own_audio_echo_is_not_a_second_chat_message(self):
        history = ChatHistory()
        identity = b"outgoing"
        history.sent(identity, "Hello", 5)
        self.assertFalse(history.receive(ReceiveProgress(identity, b"Hello", 5, 0, 128), True, "ascii"))
        history.sent_status(identity, "Nadano")
        self.assertEqual(len(history.messages), 1)
        self.assertIn("Ty · Nadano", history.transcript())

    def test_new_incoming_message_preserves_previous_conversation(self):
        history = ChatHistory()
        for index in range(3):
            history.receive(ReceiveProgress(index.to_bytes(8, "big"), b"Hello", 5, 0, 128), True, "ascii")
        self.assertEqual(len(history.messages), 3)
        self.assertEqual(history.transcript().count("Rozmówca · CRC OK"), 3)
