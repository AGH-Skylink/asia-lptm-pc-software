import tkinter as tk
from tkinter import ttk
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modem import FSKDecoder, encode_text, fsk_chunks
from receiver import Receiver
from transceiver import Transceiver, VariableLinks


class LinkTests(unittest.TestCase):
    def test_values_sync_both_ways_and_disconnect(self):
        interpreter = tk.Tcl()
        first = tk.StringVar(interpreter, value="500")
        second = tk.StringVar(interpreter, value="25")
        links = VariableLinks()
        links.link(first, second)
        self.assertEqual(second.get(), "500")
        second.set("1000")
        self.assertEqual(first.get(), "1000")
        links.close()
        first.set("2000")
        self.assertEqual(second.get(), "1000")


class TransceiverTests(unittest.TestCase):
    def test_jpeg_button_transfers_binary_and_interface_has_no_tabs(self):
        with patch("gui_common.devices", return_value=[(1, "1: Test audio")]), \
             patch("ipc_control.CommandServer.start"), patch("ipc_reference.ReferenceServer.start"), \
             patch("transmitter.OutputPlayer.play_chunks") as play, \
             patch("transmitter.messagebox.showerror") as error, tempfile.TemporaryDirectory() as directory:
            try:
                app = Transceiver()
            except tk.TclError as exc:
                self.skipTest(str(exc))
            app.withdraw()
            try:
                def has_tabs(widget):
                    return isinstance(widget, ttk.Notebook) or any(has_tabs(child) for child in widget.winfo_children())
                self.assertFalse(has_tabs(app))
                app.receiver.chat.compose.insert("1.0", "Zażółć gęślą jaźń 🙂")
                app.receiver.fsk.encoding.set("ascii")
                self.assertEqual(app.receiver.chat.compose.get("1.0", "end-1c"), "Zazolc gesla jazn ?")
                app.receiver.chat.compose.delete("1.0", "end")
                source = Path(__file__).parent / "fixtures" / "photo.jpg"
                self.assertEqual(source.read_bytes()[:2], b"\xff\xd8")
                rx, tx = app.receiver, app.transmitter
                rx.auto_settings.set(False)
                rx.fsk.modulation.set("4FSK")
                rx.fsk.zero.set("4000")
                rx.fsk.one.set("22000")
                rx.fsk.baud.set("10000")
                rx.file_directory.set(directory)
                rx.decoder = FSKDecoder(rx.fsk.config())
                tx.binary_path.set(str(source))
                tx.send_file()
                error.assert_not_called()
                chunks, _, _ = play.call_args.args
                rx.after_cancel(rx.poll_id)
                for chunk in chunks:
                    rx.audio.captured.put(chunk)
                    rx._poll()
                    rx.after_cancel(rx.poll_id)
                self.assertEqual((Path(directory) / "photo.jpg").read_bytes(), source.read_bytes())
                self.assertIn("SHA-256 OK", rx.file_status.get())
                self.assertEqual(rx.file_progress.get(), 100)
                # Selecting a JPEG through the legacy text path must use binary transfer.
                tx.text_source.set("file")
                tx.text_path.set(str(source))
                tx.send_text()
                error.assert_not_called()
                self.assertEqual(play.call_count, 2)
            finally:
                app._close()

    def test_standalone_receiver_can_reply_without_transmitter_process(self):
        with patch("gui_common.devices", return_value=[(1, "1: Test audio")]), \
             patch("ipc_control.CommandServer.start"), patch("ipc_reference.ReferenceServer.start"), \
             patch("receiver.send_reference", return_value=False), \
             patch("receiver.OutputPlayer.play_chunks") as play:
            try:
                app = Receiver()
            except tk.TclError as exc:
                self.skipTest(str(exc))
            app.window.withdraw()
            try:
                app.auto_settings.set(False)
                app.fsk.zero.set("4000")
                app.fsk.one.set("8000")
                app.fsk.baud.set("1000")
                config = app.fsk.config()
                app.decoder = FSKDecoder(config)
                self.assertTrue(app._send_chat("Odpowiadam"))
                chunks, device, rate = play.call_args.args
                frames = FSKDecoder(config).feed_frames(b"".join(chunks))
                self.assertEqual([f.payload for f in frames if f.crc_ok], [b"Odpowiadam"])
                self.assertEqual((device, rate), (1, 48000))
                app.chat_player.events.put(("done", "Zakończono."))
                app.after_cancel(app.poll_id)
                app._poll()
                self.assertIn("Ty · Nadano", app.chat.history.transcript())
            finally:
                app._close()

    def test_chat_uses_transmitter_and_receiver_preserves_both_directions(self):
        with patch("gui_common.devices", return_value=[(1, "1: Test audio")]), \
             patch("ipc_control.CommandServer.start"), patch("ipc_reference.ReferenceServer.start"), \
             patch("transmitter.send_reference", return_value=False), \
             patch("transmitter.OutputPlayer.play_chunks") as play:
            try:
                app = Transceiver()
            except tk.TclError as exc:
                self.skipTest(str(exc))
            app.withdraw()
            try:
                app.receiver.auto_settings.set(False)
                app.receiver.fsk.zero.set("4000")
                app.receiver.fsk.one.set("8000")
                app.receiver.fsk.baud.set("1000")
                self.assertEqual(app.transmitter.fsk.baud.get(), "1000")
                app.transmitter.fsk.sample_rate.set("192000")
                app.transmitter.fsk._rate_changed()
                self.assertEqual(app.receiver.fsk.max_hz.get(), 48000)
                app.receiver.fsk.sample_rate.set("48000")
                app.receiver.fsk._rate_changed()
                config = app.receiver.fsk.config()
                app.receiver.decoder = FSKDecoder(config)
                app.receiver.chat.compose.insert("1.0", "Cześć")
                app.receiver.chat._send()
                self.assertEqual(app.receiver.chat.compose.get("1.0", "end-1c"), "")
                chunks, device, rate = play.call_args.args
                self.assertEqual((device, rate), (1, 48000))
                own_pcm = b"".join(chunks)
                decoded = FSKDecoder(config).feed_frames(own_pcm)
                self.assertEqual([f.payload.decode() for f in decoded if f.crc_ok], ["Cześć"])

                # Feed both our own echo and another station through the real RX poll.
                remote_pcm = b"".join(fsk_chunks(encode_text("Odpowiedź", b"remote01"), config, .5))
                app.receiver.after_cancel(app.receiver.poll_id)
                stream = own_pcm + remote_pcm
                for start in range(0, len(stream), 2048 * 4):
                    app.receiver.audio.captured.put(stream[start:start + 2048 * 4])
                    app.receiver._poll()
                    app.receiver.after_cancel(app.receiver.poll_id)
                self.assertEqual(len(app.receiver.chat.history.messages), 2)
                transcript = app.receiver.chat.history.transcript()
                self.assertIn("Cześć", transcript)
                self.assertIn("Rozmówca · CRC OK", transcript)
                self.assertIn("Odpowiedź", transcript)
                app.transmitter.player.events.put(("done", "Zakończono."))
                app.transmitter.after_cancel(app.transmitter.poll_id)
                app.transmitter._poll()
                self.assertIn("Ty · Nadano", app.receiver.chat.history.transcript())
            finally:
                app._close()
