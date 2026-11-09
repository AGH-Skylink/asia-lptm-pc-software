from threading import Thread
import unittest

from ipc_control import CommandServer, send_command


class CommandChannelTests(unittest.TestCase):
    def test_command_reaches_application_queue_and_returns_reply(self):
        server = CommandServer(port=0)
        server.start()
        try:
            port = server.listener.getsockname()[1]

            def application_loop():
                command, response = server.incoming.get(timeout=2)
                response.put({"seen": command["text"]})

            app = Thread(target=application_loop)
            app.start()
            result = send_command(port, {"text": "Laser Polarisation Modulation Transceiver"})
            app.join(timeout=2)
            self.assertEqual(result["seen"], "Laser Polarisation Modulation Transceiver")
            self.assertFalse(app.is_alive())
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
