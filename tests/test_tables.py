"""Synthetic CURVE / MAP layout tests, strictly read-only."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from kingai_a2l.core import A2LDefinition, A2LError

SAMPLE = """
ASAP2_VERSION 1 71
/begin PROJECT Demo ""
 /begin MODULE M ""
  /begin MOD_COMMON "" BYTE_ORDER MSB_LAST /end MOD_COMMON
  /begin RECORD_LAYOUT FUNC FNC_VALUES 1 UWORD ROW_DIR DIRECT /end RECORD_LAYOUT
  /begin RECORD_LAYOUT AXIS AXIS_PTS_X 1 UWORD INDEX_INCR DIRECT /end RECORD_LAYOUT
  /begin COMPU_METHOD CM "" LINEAR "%6.2" "rpm" COEFFS_LINEAR 2 0 /end COMPU_METHOD
  /begin CHARACTERISTIC C_FIXED "" CURVE 0x2000 FUNC 0 CM 0 1000
   /begin AXIS_DESCR FIX_AXIS NO_INPUT_QUANTITY CM 3 0 1000
    FIX_AXIS_PAR_DIST 100 100 3
   /end AXIS_DESCR
  /end CHARACTERISTIC
  /begin CHARACTERISTIC M_COM "" MAP 0x2020 FUNC 0 CM 0 1000
   /begin AXIS_DESCR COM_AXIS NO_INPUT_QUANTITY CM 2 0 1000
    AXIS_PTS_REF RPM
   /end AXIS_DESCR
   /begin AXIS_DESCR FIX_AXIS NO_INPUT_QUANTITY CM 3 0 1000
    /begin FIX_AXIS_PAR_LIST 1 2 3 /end FIX_AXIS_PAR_LIST
   /end AXIS_DESCR
  /end CHARACTERISTIC
  /begin AXIS_PTS RPM "" 0x2060 NO_INPUT_QUANTITY AXIS 0 CM 2 0 1000
  /end AXIS_PTS
 /end MODULE
/end PROJECT
"""


class TableTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.path = self.folder / "fixed.a2l"
        self.path.write_text(SAMPLE, encoding="utf-8")
        self.firmware = bytearray(128)
        struct.pack_into("<3H", self.firmware, 0, 10, 20, 30)
        struct.pack_into("<6H", self.firmware, 0x20, 1, 2, 3, 4, 5, 6)
        struct.pack_into("<2H", self.firmware, 0x60, 250, 350)
        self.bin_path = self.folder / "synthetic.bin"
        self.bin_path.write_bytes(self.firmware)

    def definition(self, source=None):
        if source is not None:
            self.path.write_text(source, encoding="utf-8")
        return A2LDefinition.load(self.path)

    def test_read_fixed_axis_curve(self):
        data = self.definition().read_table("C_FIXED", self.firmware, 0x2000)
        self.assertEqual(data["dimensions"], [3])
        self.assertEqual(data["flat_raw_values"], [10, 20, 30])
        self.assertEqual(data["flat_physical_values"], [20, 40, 60])
        self.assertEqual(data["axes"][0]["raw_values"], [100, 200, 300])
        self.assertEqual(data["axes"][0]["physical_values"], [200, 400, 600])
        self.assertTrue(data["read_only"])
        self.assertFalse(data["cell_coordinate_mapping_qualified"])

    def test_read_map_common_and_fixed_axis(self):
        data = self.definition().read_table("M_COM", self.firmware, 0x2000)
        self.assertEqual(data["dimensions"], [2, 3])
        self.assertEqual(data["flat_raw_values"], [1, 2, 3, 4, 5, 6])
        self.assertEqual(data["flat_physical_values"], [2, 4, 6, 8, 10, 12])
        self.assertEqual(data["axes"][0]["physical_values"], [500, 700])
        self.assertEqual(data["axes"][0]["bin_offset"], 0x60)
        self.assertEqual(data["axes"][1]["raw_values"], [1, 2, 3])
        self.assertEqual(bytes(self.firmware), self.bin_path.read_bytes())

    def test_invalid_com_axis_reference_fails(self):
        d = self.definition(SAMPLE.replace("AXIS_PTS_REF RPM", "AXIS_PTS_REF NOT_FOUND"))
        with self.assertRaisesRegex(A2LError, "exactly one AXIS_PTS"):
            d.read_table("M_COM", self.firmware, 0x2000)

    def test_dynamic_record_layout_is_rejected(self):
        alt = SAMPLE.replace(
            "FNC_VALUES 1 UWORD ROW_DIR DIRECT",
            "NO_AXIS_PTS_X 1 UBYTE FNC_VALUES 2 UWORD ROW_DIR DIRECT",
        )
        d = self.definition(alt)
        with self.assertRaisesRegex(A2LError, "sole contiguous"):
            d.read_table("C_FIXED", self.firmware, 0x2000)

    def test_axis_count_mismatch_fails(self):
        d = self.definition(SAMPLE.replace(
            "FIX_AXIS_PAR_DIST 100 100 3", "FIX_AXIS_PAR_DIST 100 100 4"))
        with self.assertRaisesRegex(A2LError, "differs"):
            d.read_table("C_FIXED", self.firmware, 0x2000)

    def test_table_bounds_and_address_mapping(self):
        d = self.definition()
        with self.assertRaisesRegex(A2LError, "outside BIN"):
            d.read_table("C_FIXED", self.firmware, 0x1000)

    def test_cli_read_table(self):
        p = subprocess.run(
            [sys.executable, "-m", "kingai_a2l", "read-table", "--a2l", str(self.path),
             "--bin", str(self.bin_path), "--base-address", "0x2000", "--name", "M_COM"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        item = json.loads(p.stdout)["item"]
        self.assertEqual(item["dimensions"], [2, 3])
        self.assertFalse(item["cell_coordinate_mapping_qualified"])

    def test_table_edit_is_still_disallowed(self):
        d = self.definition()
        with self.assertRaisesRegex(A2LError, "Only VALUE"):
            d.edit_raw("M_COM", self.firmware, 0x2000, 100)


if __name__ == "__main__":
    unittest.main()
