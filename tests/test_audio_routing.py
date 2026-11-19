from array import array
from threading import Event
import unittest
from unittest.mock import patch

from audio_runtime import ReceiverAudio


class AudioRoutingTests(unittest.TestCase):
    def test_switch_monitor_without_reopening_input_or_stopping_recording(self):
        opened = {2: Event(), 3: Event()}
        written = {2: Event(), 3: Event()}
        outputs = []
        received = []

        class Output:
            def __init__(self, **settings):
                self.device = settings["device"]
                outputs.append(settings)

            def __enter__(self):
                opened[self.device].set()
                return self

            def __exit__(self, *_args):
                pass

            def write(self, chunk):
                received.append((self.device, chunk))
                written[self.device].set()

        with patch("audio_runtime.sd.RawInputStream") as input_stream, \
             patch("audio_runtime.sd.RawOutputStream", Output):
            audio = ReceiverAudio()
            try:
                audio.start(1, sample_rate=96000)
                capture = audio.input_stream
                callback = input_stream.call_args.kwargs["callback"]
                with patch.object(audio.recorder, "stop") as stop_recording:
                    for device in (2, 3):
                        audio.set_monitor(device)
                        self.assertTrue(opened[device].wait(2))
                        chunk = array("f", [0, .25, -.5]).tobytes()
                        callback(chunk, 3, None, None)
                        self.assertTrue(written[device].wait(2))
                        self.assertIs(audio.input_stream, capture)
                    audio.set_monitor(None)
                    stop_recording.assert_not_called()
                input_stream.assert_called_once()
                capture.stop.assert_not_called()
                capture.close.assert_not_called()
                self.assertEqual([item["device"] for item in outputs], [2, 3])
                self.assertTrue(all(item["samplerate"] == 96000 for item in outputs))
                self.assertEqual([device for device, _ in received], [2, 3])
                self.assertEqual(audio.captured.qsize(), 2)
                self.assertTrue(audio.errors.empty())
            finally:
                audio.stop()
