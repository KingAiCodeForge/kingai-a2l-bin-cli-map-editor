"""AXIS_DESCR vs referenced AXIS_PTS byte-order conflicts must not be hidden."""
from pathlib import Path
import struct
import tempfile
import unittest

from kingai_a2l.core import A2LDefinition, A2LError

DOCUMENT = """
ASAP2_VERSION 1 71
/begin PROJECT P ""
 /begin MODULE M ""
  /begin MOD_COMMON "" BYTE_ORDER MSB_LAST /end MOD_COMMON
  /begin RECORD_LAYOUT F FNC_VALUES 1 UWORD ROW_DIR DIRECT /end RECORD_LAYOUT
  /begin RECORD_LAYOUT A AXIS_PTS_X 1 UWORD INDEX_INCR DIRECT /end RECORD_LAYOUT
  /begin AXIS_PTS AX "" 0x8010 NO_INPUT_QUANTITY A 0 NO_COMPU_METHOD 2 0 1000
    {axis_override}
  /end AXIS_PTS
  /begin CHARACTERISTIC M1 "" CURVE 0x8000 F 0 NO_COMPU_METHOD 0 1000
   /begin AXIS_DESCR COM_AXIS NO_INPUT_QUANTITY NO_COMPU_METHOD 2 0 1000
    AXIS_PTS_REF AX
    BYTE_ORDER MSB_FIRST
   /end AXIS_DESCR
  /end CHARACTERISTIC
 /end MODULE
/end PROJECT
"""


class AxisEndianTests(unittest.TestCase):
    def make(self, override):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "fixture.a2l"
        path.write_text(DOCUMENT.format(axis_override=override), encoding="utf-8")
        return A2LDefinition.load(path)

    def test_conflicting_axis_byte_orders_rejected(self):
        image = bytearray(32)
        struct.pack_into("<2H", image, 0, 1, 2)
        struct.pack_into(">2H", image, 16, 3, 4)
        with self.assertRaisesRegex(A2LError, "byte-order override conflicts"):
            self.make("").read_table("M1", image, 0x8000)

    def test_matching_axis_byte_order_override(self):
        image = bytearray(32)
        struct.pack_into("<2H", image, 0, 1, 2)
        struct.pack_into(">2H", image, 16, 3, 4)
        data = self.make("BYTE_ORDER MSB_FIRST").read_table("M1", image, 0x8000)
        self.assertEqual(data["flat_raw_values"], [1, 2])
        self.assertEqual(data["axes"][0]["raw_values"], [3, 4])


if __name__ == "__main__":
    unittest.main()
