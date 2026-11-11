"""Synthetic regression fixtures for inline STD_AXIS memory-order decoding."""
import json
import struct
import subprocess
import sys
import unittest
import tempfile
from pathlib import Path

from kingai_a2l.core import A2LDefinition, A2LError


def fixture(layout: str, descriptors: str, kind: str = "CURVE",
            extra: str = "", common: str = "") -> str:
    return f"""
    ASAP2_VERSION 1 71
    /begin PROJECT P ""
     /begin MODULE M ""
      /begin MOD_COMMON "" BYTE_ORDER MSB_LAST {common} /end MOD_COMMON
      /begin RECORD_LAYOUT L {layout} /end RECORD_LAYOUT
      /begin CHARACTERISTIC K "" {kind} 0x8000 L 0 NO_COMPU_METHOD 0 255
       {descriptors}
       {extra}
      /end CHARACTERISTIC
     /end MODULE
    /end PROJECT
    """


X = "/begin AXIS_DESCR STD_AXIS NO_INPUT_QUANTITY NO_COMPU_METHOD 4 0 255 /end AXIS_DESCR"
Y = "/begin AXIS_DESCR STD_AXIS NO_INPUT_QUANTITY NO_COMPU_METHOD 5 0 255 /end AXIS_DESCR"
BYTES_CURVE = """
NO_AXIS_PTS_X 1 UBYTE
AXIS_PTS_X 2 UBYTE INDEX_INCR DIRECT
FNC_VALUES 3 UBYTE ROW_DIR DIRECT
"""
BYTES_MAP = """
NO_AXIS_PTS_X 1 UBYTE
AXIS_PTS_X 2 UBYTE INDEX_INCR DIRECT
NO_AXIS_PTS_Y 3 UBYTE
AXIS_PTS_Y 4 UBYTE INDEX_INCR DIRECT
FNC_VALUES 5 UBYTE COLUMN_DIR DIRECT
"""


class InlineLayoutTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "synthetic.a2l"

    def d(self, layout=BYTES_CURVE, desc=X, kind="CURVE", extra="", common=""):
        self.path.write_text(fixture(layout, desc, kind, extra, common), encoding="utf-8")
        return A2LDefinition.load(self.path)

    def test_dynamic_curve_uses_actual_count_not_declared_max(self):
        data = self.d().read_table("K", bytes([2, 10, 20, 30, 40]), 0x8000)
        self.assertEqual(data["dimensions"], [2])
        self.assertEqual(data["axes"][0]["raw_values"], [10, 20])
        self.assertEqual(data["flat_raw_values"], [30, 40])
        self.assertEqual([x["bin_offset"] for x in data["record_fields"]], [0, 1, 3])
        self.assertEqual(data["axes"][0]["count_source"], "NO_AXIS_PTS_X")
        self.assertEqual(data["bin_offset"], 3)
        self.assertTrue(data["read_only"])

    def test_dynamic_map_with_two_counts(self):
        data = self.d(BYTES_MAP, X + " " + Y, "MAP").read_table(
            "K", bytes([2, 10, 20, 3, 5, 6, 7, 1, 2, 3, 4, 5, 6]), 0x8000
        )
        self.assertEqual(data["dimensions"], [2, 3])
        self.assertEqual(data["axes"][1]["raw_values"], [5, 6, 7])
        self.assertEqual(data["item_count"], 6)
        self.assertEqual(data["flat_raw_values"], [1, 2, 3, 4, 5, 6])
        self.assertEqual(data["bin_offset"], 7)
        self.assertFalse(data["cell_coordinate_mapping_qualified"])

    def test_fixed_max_count_without_dynamic_counter(self):
        layout = "AXIS_PTS_X 1 UWORD INDEX_INCR DIRECT FNC_VALUES 2 UWORD ROW_DIR DIRECT"
        desc = X.replace("4 0 255", "2 0 65535")
        image = struct.pack("<4H", 100, 300, 11, 22)
        data = self.d(layout, desc).read_table("K", image, 0x8000)
        self.assertEqual(data["axes"][0]["raw_values"], [100, 300])
        self.assertEqual(data["flat_raw_values"], [11, 22])
        self.assertEqual(data["axes"][0]["count_source"], "MAX_AXIS_POINTS")
        self.assertEqual(data["record_fields"][-1]["bin_offset"], 4)

    def test_fixed_axis_second_dimension_not_stored(self):
        fix = (
            "/begin AXIS_DESCR FIX_AXIS NO_INPUT_QUANTITY NO_COMPU_METHOD 3 0 255 "
            "FIX_AXIS_PAR_DIST 1 2 3 /end AXIS_DESCR"
        )
        layout = "AXIS_PTS_X 1 UBYTE INDEX_INCR DIRECT FNC_VALUES 2 UBYTE ROW_DIR DIRECT"
        image = bytes([10, 20, 30, 40, 50, 60, 70, 80])
        desc = X.replace("4 0 255", "2 0 255") + " " + fix
        data = self.d(layout, desc, "MAP").read_table("K", image, 0x8000)
        self.assertEqual(data["dimensions"], [2, 3])
        self.assertEqual(data["axes"][1]["raw_values"], [1., 3., 5.])
        self.assertEqual(data["flat_raw_values"], [30, 40, 50, 60, 70, 80])

    def test_position_zero_and_byte_order_override(self):
        layout = "AXIS_PTS_X 0 UWORD INDEX_INCR DIRECT FNC_VALUES 1 UWORD ROW_DIR DIRECT"
        desc = X.replace("4 0 255", "2 0 65535").replace(
            "/end AXIS_DESCR", "BYTE_ORDER MSB_FIRST /end AXIS_DESCR"
        )
        image = struct.pack(">HH", 100, 200) + struct.pack("<HH", 20, 30)
        data = self.d(layout, desc).read_table("K", image, 0x8000)
        self.assertEqual(data["axes"][0]["raw_values"], [100, 200])
        self.assertEqual(data["flat_raw_values"], [20, 30])

    def test_bad_count_zero_or_above_max_is_rejected(self):
        d = self.d()
        for count in (0, 5, 255):
            with self.subTest(count=count):
                with self.assertRaisesRegex(A2LError, "count"):
                    d.read_table("K", bytes([count, 10, 20, 30, 40]), 0x8000)

    def test_no_implicit_alignment_guessing(self):
        layout = (
            "NO_AXIS_PTS_X 1 UBYTE "
            "AXIS_PTS_X 2 UWORD INDEX_INCR DIRECT "
            "FNC_VALUES 3 UWORD ROW_DIR DIRECT"
        )
        d = self.d(layout)
        with self.assertRaisesRegex(A2LError, "padding"):
            d.read_table("K", bytes([2]) + bytes(23), 0x8000)

    def test_explicit_strict_alignment_is_enforced(self):
        layout = "AXIS_PTS_X 1 UWORD INDEX_INCR DIRECT FNC_VALUES 2 UWORD ROW_DIR DIRECT"
        desc = X.replace("4 0 255", "3 0 65535")
        d = self.d(layout, desc, common="ALIGNMENT_WORD 4")
        with self.assertRaisesRegex(A2LError, "padding"):
            d.read_table("K", struct.pack("<6H", 1, 2, 3, 4, 5, 6), 0x8000)

    def test_unsupported_static_record_layout_and_pointers_refused(self):
        variants = [
            BYTES_CURVE + " STATIC_RECORD_LAYOUT",
            BYTES_CURVE.replace("INDEX_INCR DIRECT", "INDEX_INCR PWORD"),
            BYTES_CURVE.replace("INDEX_INCR", "INDEX_DECR"),
            BYTES_CURVE + " RESERVED 4 BYTE",
        ]
        for layout in variants:
            with self.subTest(layout=layout):
                with self.assertRaises(A2LError):
                    self.d(layout).read_table("K", bytes(40), 0x8000)

    def test_repeated_position_is_rejected(self):
        layout = BYTES_CURVE.replace("AXIS_PTS_X 2", "AXIS_PTS_X 1")
        with self.assertRaisesRegex(A2LError, "Overlapping"):
            self.d(layout).read_table("K", bytes([2, 10, 20, 30, 40]), 0x8000)

    def test_count_after_axis_is_refused(self):
        layout = """
        AXIS_PTS_X 1 UBYTE INDEX_INCR DIRECT
        NO_AXIS_PTS_X 2 UBYTE
        FNC_VALUES 3 UBYTE ROW_DIR DIRECT
        """
        with self.assertRaisesRegex(A2LError, "precedes dynamic count"):
            self.d(layout).read_table("K", bytes(12), 0x8000)

    def test_table_write_still_refused(self):
        d = self.d()
        with self.assertRaisesRegex(A2LError, "Only VALUE"):
            d.edit_raw("K", bytes([2, 10, 20, 30, 40]), 0x8000, 33)

    def test_dynamic_layout_via_headless_cli(self):
        self.d()
        image = self.path.with_suffix(".bin")
        image.write_bytes(bytes([2, 10, 20, 30, 40]))
        result = subprocess.run([
            sys.executable, "-m", "kingai_a2l", "read-table",
            "--a2l", str(self.path), "--bin", str(image),
            "--base-address", "0x8000", "--name", "K"
        ], check=False, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        item = json.loads(result.stdout)["item"]
        self.assertEqual(item["record_fields"][-1]["bin_offset"], 3)
        self.assertEqual(item["dimensions"], [2])
        self.assertFalse(item["cell_coordinate_mapping_qualified"])
        self.assertEqual(image.read_bytes(), bytes([2, 10, 20, 30, 40]))


if __name__ == "__main__":
    unittest.main()
