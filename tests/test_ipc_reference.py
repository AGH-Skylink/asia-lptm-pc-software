import unittest

from ipc_reference import ReferenceServer, send_reference


class ReferenceChannelTests(unittest.TestCase):
    def test_local_reference_round_trip(self):
        server = ReferenceServer(port=0)
        server.start()
        try:
            port = server.listener.getsockname()[1]
            message_id = bytes.fromhex("0102030405060708")
            payload = b"Laser Polarisation Modulation Transceiver"
            self.assertTrue(send_reference(message_id, payload, port=port))
            self.assertEqual(server.incoming.get(timeout=1), (message_id, payload))
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
