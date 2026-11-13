import csv
import json
import tempfile
import unittest
from pathlib import Path
from queue import Queue
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from file_sweep import read_plan
from receiver import Receiver
from repeat_sweep import RAW_COLUMNS, SUMMARY_COLUMNS


class ReceiverScanTests(unittest.TestCase):
    def test_scan_saves_summary_and_resumes_duplicate_plan_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.csv"
            plan.write_text("bit_0_hz,bit_1_hz,speed_bps\n1000,2000,250\n1000,2000,250\n",
                            encoding="utf-8")
            output = Path(directory) / "result_raw.csv"
            app = SimpleNamespace(scan_stop=Event(), scan_updates=Queue())
            result = {name: "" for name in RAW_COLUMNS}
            result.update(status="no_frame", signal_rms_dbfs="-42", received_text="")

            def command(_port, request):
                if request["action"] == "measurement_message":
                    return {"text": "test", "output_device": 2, "amplitude": 0.4}
                return {}

            with patch("receiver.send_command", side_effect=command), \
                 patch("receiver._run_gui_trial", return_value=result) as run:
                Receiver._scan_worker(app, plan, output, read_plan(plan), 1)
                self.assertEqual(run.call_count, 2)
                Receiver._scan_worker(app, plan, output, read_plan(plan), 1)
                self.assertEqual(run.call_count, 2)

            with output.open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            self.assertEqual([row["plan_line"] for row in rows], ["2", "3"])
            summary = Path(directory) / "result_summary.csv"
            with summary.open(newline="", encoding="utf-8") as source:
                reader = csv.DictReader(source)
                self.assertEqual(tuple(reader.fieldnames), SUMMARY_COLUMNS)
                rows = list(reader)
            self.assertEqual(len(rows), 2)
            self.assertEqual([row["ber_percent"] for row in rows], ["100", "100"])
            self.assertEqual([row["signal_rms_dbfs"] for row in rows], ["-42", "-42"])
            metadata = json.loads((Path(directory) / "result_metadata.json").read_text())
            self.assertEqual(metadata["message"], "test")


if __name__ == "__main__":
    unittest.main()
