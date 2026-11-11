"""Cross-reference regressions drawn from ASAM grammar and a2ltool fixture patterns.

Synthetic images only: never rely on a third-party ECU memory image.
"""
from pathlib import Path
import struct
import tempfile
import unittest

from kingai_a2l.core import A2LDefinition, A2LError

TEMPLATE = """
ASAP2_VERSION 1 71
/begin PROJECT CrossReference ""
 /begin MODULE E ""
  /begin MOD_COMMON "" BYTE_ORDER MSB_LAST /end MOD_COMMON
  {layout}
  {conversions}
  {characteristic}
 /end MODULE
/end PROJECT
"""


class CrossReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "synthetic.a2l"

    def definition(self, layout, characteristic, conversions=""):
        self.path.write_text(
            TEMPLATE.format(layout=layout, characteristic=characteristic,
                            conversions=conversions),
            encoding="utf-8",
        )
        return A2LDefinition.load(self.path)

    def test_position_zero_for_single_field_scalar(self):
        definition = self.definition(
            "/begin RECORD_LAYOUT L FNC_VALUES 0 UWORD ROW_DIR DIRECT /end RECORD_LAYOUT",
            '/begin CHARACTERISTIC K "" VALUE 0x8000 L 0 NO_COMPU_METHOD 0 65535 /end CHARACTERISTIC',
        )
        self.assertEqual(definition.read_scalar("K", struct.pack("<H", 513), 0x8000)["raw"], 513)

    def test_position_zero_for_float_scalar(self):
        definition = self.definition(
            "/begin RECORD_LAYOUT L FNC_VALUES 0 FLOAT32_IEEE ROW_DIR DIRECT /end RECORD_LAYOUT",
            '/begin CHARACTERISTIC K "" VALUE 0x8000 L 0 NO_COMPU_METHOD -1000 1000 /end CHARACTERISTIC',
        )
        blob = struct.pack("<f", 0.625)
        self.assertEqual(definition.read_scalar("K", blob, 0x8000)["raw"], 0.625)
        with self.assertRaisesRegex(A2LError, "floating-point"):
            definition.edit_raw("K", blob, 0x8000, 2)

    def test_float64_reads_and_rejects_float_writes(self):
        definition = self.definition(
            "/begin RECORD_LAYOUT L FNC_VALUES 1 FLOAT64_IEEE COLUMN_DIR DIRECT /end RECORD_LAYOUT",
            '/begin CHARACTERISTIC K "" VALUE 0x8000 L 0 NO_COMPU_METHOD -1000 1000 /end CHARACTERISTIC',
        )
        blob = struct.pack("<d", -99.125)
        self.assertEqual(definition.read_scalar("K", blob, 0x8000)["raw"], -99.125)
        with self.assertRaisesRegex(A2LError, "floating-point"):
            definition.edit_raw("K", blob, 0x8000, 10)

    def test_nan_float_fails_closed(self):
        d = self.definition(
            "/begin RECORD_LAYOUT L FNC_VALUES 1 FLOAT32_IEEE ROW_DIR DIRECT /end RECORD_LAYOUT",
            '/begin CHARACTERISTIC K "" VALUE 0x8000 L 0 NO_COMPU_METHOD -1000 1000 /end CHARACTERISTIC',
        )
        with self.assertRaisesRegex(A2LError, "bounds"):
            d.read_scalar("K", struct.pack("<f", float("nan")), 0x8000)

    def test_composite_scalar_layout_identification_is_rejected(self):
        for composite in ("IDENTIFICATION 0 UBYTE",
                          "RESERVED 2 BYTE",
                          "AXIS_PTS_X 2 UWORD INDEX_INCR DIRECT",
                          "NO_AXIS_PTS_X 0 UBYTE",
                          "ALIGNMENT_WORD 2"):
            with self.subTest(composite=composite):
                d = self.definition(
                    "/begin RECORD_LAYOUT L FNC_VALUES 1 UWORD ROW_DIR DIRECT "
                    + composite + " /end RECORD_LAYOUT",
                    '/begin CHARACTERISTIC K "" VALUE 0x8000 L 0 NO_COMPU_METHOD 0 65535 /end CHARACTERISTIC',
                )
                with self.assertRaisesRegex(A2LError, "sole contiguous"):
                    d.read_scalar("K", struct.pack("<H", 513), 0x8000)

    def test_map_float_values_and_fixed_axis_list_floats(self):
        layout = "/begin RECORD_LAYOUT L FNC_VALUES 0 FLOAT32_IEEE COLUMN_DIR DIRECT /end RECORD_LAYOUT"
        characteristic = """
        /begin CHARACTERISTIC M "" MAP 0x8000 L 0 NO_COMPU_METHOD -100 100
         /begin AXIS_DESCR FIX_AXIS NO_INPUT_QUANTITY NO_COMPU_METHOD 2 -1 1
          /begin FIX_AXIS_PAR_LIST -0.5 0.5 /end FIX_AXIS_PAR_LIST
         /end AXIS_DESCR
         /begin AXIS_DESCR FIX_AXIS NO_INPUT_QUANTITY NO_COMPU_METHOD 3 0 3
          FIX_AXIS_PAR_DIST 0.0 1.5 3
         /end AXIS_DESCR
        /end CHARACTERISTIC
        """
        d = self.definition(layout, characteristic)
        image = struct.pack("<6f", 0.25, 0.5, 1, 2, 3.5, 4)
        m = d.read_table("M", image, 0x8000)
        self.assertEqual(m["dimensions"], [2, 3])
        self.assertEqual(m["flat_raw_values"], [0.25, 0.5, 1, 2, 3.5, 4])
        self.assertEqual(m["axes"][0]["raw_values"], [-0.5, 0.5])
        self.assertEqual(m["axes"][1]["raw_values"], [0., 1.5, 3.])
        self.assertTrue(m["read_only"])

    def test_fixed_axis_shift_formula(self):
        d = self.definition(
            "/begin RECORD_LAYOUT L FNC_VALUES 1 UBYTE ROW_DIR DIRECT /end RECORD_LAYOUT",
            """
            /begin CHARACTERISTIC C "" CURVE 0x8000 L 0 NO_COMPU_METHOD 0 255
             /begin AXIS_DESCR FIX_AXIS NO_INPUT_QUANTITY NO_COMPU_METHOD 4 0 15
              FIX_AXIS_PAR 1 2 4
             /end AXIS_DESCR
            /end CHARACTERISTIC
            """,
        )
        curve = d.read_table("C", bytes([4, 5, 6, 7]), 0x8000)
        self.assertEqual(curve["axes"][0]["raw_values"], [1., 5., 9., 13.])

    def test_conflicting_fixed_axis_sources_rejected(self):
        d = self.definition(
            "/begin RECORD_LAYOUT L FNC_VALUES 1 UBYTE ROW_DIR DIRECT /end RECORD_LAYOUT",
            """
            /begin CHARACTERISTIC C "" CURVE 0x8000 L 0 NO_COMPU_METHOD 0 255
             /begin AXIS_DESCR FIX_AXIS NO_INPUT_QUANTITY NO_COMPU_METHOD 2 0 10
              FIX_AXIS_PAR_DIST 0 1 2
              /begin FIX_AXIS_PAR_LIST 1 2 /end FIX_AXIS_PAR_LIST
             /end AXIS_DESCR
            /end CHARACTERISTIC
            """,
        )
        with self.assertRaisesRegex(A2LError, "exactly one"):
            d.read_table("C", bytes([4, 5]), 0x8000)

    def test_float_external_axis_position_zero(self):
        d = self.definition(
            """
            /begin RECORD_LAYOUT L FNC_VALUES 0 UWORD ROW_DIR DIRECT /end RECORD_LAYOUT
            /begin RECORD_LAYOUT A AXIS_PTS_X 0 FLOAT32_IEEE INDEX_INCR DIRECT /end RECORD_LAYOUT
            """,
            """
            /begin AXIS_PTS RPM "" 0x8010 NO_INPUT_QUANTITY A 0 NO_COMPU_METHOD 2 -10 10 /end AXIS_PTS
            /begin CHARACTERISTIC C "" CURVE 0x8000 L 0 NO_COMPU_METHOD 0 255
             /begin AXIS_DESCR COM_AXIS NO_INPUT_QUANTITY NO_COMPU_METHOD 2 -10 10
              AXIS_PTS_REF RPM
             /end AXIS_DESCR
            /end CHARACTERISTIC
            """,
        )
        image = bytearray(32)
        struct.pack_into("<2H", image, 0, 10, 20)
        struct.pack_into("<2f", image, 16, -2.5, 3.75)
        curve = d.read_table("C", image, 0x8000)
        self.assertEqual(curve["axes"][0]["raw_values"], [-2.5, 3.75])
        self.assertEqual(curve["flat_raw_values"], [10, 20])

    def test_rejects_discontinuous_layout(self):
        d = self.definition(
            "/begin RECORD_LAYOUT L FNC_VALUES 2 UWORD ROW_DIR DIRECT /end RECORD_LAYOUT",
            '/begin CHARACTERISTIC K "" VALUE 0x8000 L 0 NO_COMPU_METHOD 0 65535 /end CHARACTERISTIC',
        )
        with self.assertRaisesRegex(A2LError, "position"):
            d.read_scalar("K", bytes(4), 0x8000)


if __name__ == "__main__":
    unittest.main()
