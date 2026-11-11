"""AI-focused structural inventory; never claims binary mapping equivalence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from kingai_a2l.core import A2LDefinition
from kingai_a2l.research import summarize

SAMPLE = """
ASAP2_VERSION 1 71
/begin PROJECT P ""
 /begin MODULE ECU ""
  /begin MOD_COMMON "" BYTE_ORDER MSB_LAST /end MOD_COMMON
  /begin COMPU_METHOD LIN "" LINEAR "%5.2" "rpm"
   COEFFS_LINEAR 2 0
  /end COMPU_METHOD
  /begin RECORD_LAYOUT FLOAT32 FNC_VALUES 0 FLOAT32_IEEE ROW_DIR DIRECT /end RECORD_LAYOUT
  /begin RECORD_LAYOUT ARR NO_AXIS_PTS_X 1 UBYTE
   AXIS_PTS_X 2 UBYTE INDEX_INCR DIRECT
   FNC_VALUES 3 UBYTE COLUMN_DIR DIRECT
  /end RECORD_LAYOUT
  /begin CHARACTERISTIC VALUE_A "" VALUE 0x8000 FLOAT32 0 LIN -100 100 /end CHARACTERISTIC
  /begin CHARACTERISTIC TABLE_A "" CURVE 0x8020 ARR 0 LIN 0 250
   /begin AXIS_DESCR STD_AXIS NO_INPUT_QUANTITY LIN 4 0 100
    MONOTONY STRICT_INCREASE
   /end AXIS_DESCR
  /end CHARACTERISTIC
 /end MODULE
/end PROJECT
"""


class ResearchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.file = Path(temp.name) / "example.a2l"
        self.file.write_text(SAMPLE, encoding="utf-8")

    def test_deterministic_summary(self):
        d = A2LDefinition.load(self.file)
        one, two = summarize(d), summarize(d)
        self.assertEqual(one, two)
        self.assertEqual(one["counts"]["characteristics"], 2)
        self.assertEqual(one["characteristic_kinds"], {"CURVE": 1, "VALUE": 1})
        self.assertEqual(one["record_keywords"]["NO_AXIS_PTS_X"], 1)
        self.assertEqual(one["fnc_values_positions"], {"0": 1, "3": 1})
        self.assertEqual(one["axis_kinds"], {"STD_AXIS": 1})
        self.assertIn("no image pairing", one["caveat"].lower())

    def test_summary_requires_no_firmware_image(self):
        p = subprocess.run(
            [sys.executable, "-m", "kingai_a2l", "summary", "--a2l", str(self.file)],
            capture_output=True, text=True, check=False
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        doc = json.loads(p.stdout)
        self.assertTrue(doc["ok"])
        self.assertFalse(doc["flash_ready"])
        self.assertNotIn("bin_sha256", doc)
        self.assertEqual(doc["structural_inventory"]["counts"]["record_layouts"], 2)


if __name__ == "__main__":
    unittest.main()
