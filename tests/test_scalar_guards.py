"""Regression tests for byte and access guards using synthetic A2L."""
import struct
import tempfile
import unittest
from pathlib import Path

from kingai_a2l.core import A2LDefinition, A2LError

HEAD = '''
ASAP2_VERSION 1 71
/begin PROJECT Demo ""
/begin MODULE M1 ""
 /begin MOD_COMMON "" BYTE_ORDER MSB_LAST /end MOD_COMMON
 /begin RECORD_LAYOUT L FNC_VALUES 1 UWORD COLUMN_DIR DIRECT /end RECORD_LAYOUT
 /begin COMPU_METHOD C "" RAT_FUNC "%6.2" "kPa"
   COEFFS 0 2 0 0 0 1
 /end COMPU_METHOD
 /begin CHARACTERISTIC VAL "" VALUE 0x1004 L 0 C 0 1000
   {extra}
 /end CHARACTERISTIC
/end MODULE
/end PROJECT
'''


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "test.a2l"
        self.bin = bytearray(16)
        struct.pack_into("<H", self.bin, 4, 200)

    def d(self, extra="", overrides=None):
        source = HEAD.replace("{extra}", extra)
        if overrides:
            for old, new in overrides:
                source = source.replace(old, new)
        self.path.write_text(source, encoding="utf-8")
        return A2LDefinition.load(self.path)

    def test_affine_rational_direction(self):
        d = self.d()
        self.assertEqual(d.read_scalar("VAL", bytes(self.bin), 0x1000)["physical"], 100.0)
        new, receipt = d.edit_raw("VAL", bytes(self.bin), 0x1000, 220)
        self.assertEqual(receipt["new_physical"], 110.0)
        self.assertEqual(d.read_scalar("VAL", new, 0x1000)["raw"], 220)

    def test_non_linear_rat_func_is_rejected(self):
        d = self.d(overrides=[("COEFFS 0 2 0 0 0 1", "COEFFS 1 2 0 0 0 1")])
        with self.assertRaisesRegex(A2LError, "Nonlinear"):
            d.read_scalar("VAL", bytes(self.bin), 0x1000)

    def test_bit_mask_never_erases_neighbouring_fields(self):
        d = self.d(extra="BIT_MASK 0x0FF0")
        with self.assertRaisesRegex(A2LError, "BIT_MASK"):
            d.read_scalar("VAL", bytes(self.bin), 0x1000)
        with self.assertRaisesRegex(A2LError, "BIT_MASK"):
            d.edit_raw("VAL", bytes(self.bin), 0x1000, 100)

    def test_read_only_and_access_controls_block_edits(self):
        for restriction in ("READ_ONLY", "CALIBRATION_ACCESS NO_CALIBRATION"):
            with self.subTest(restriction=restriction):
                d = self.d(extra=restriction)
                self.assertEqual(d.read_scalar("VAL", bytes(self.bin), 0x1000)["raw"], 200)
                with self.assertRaises(A2LError):
                    d.edit_raw("VAL", bytes(self.bin), 0x1000, 210)

    def test_item_byte_order_override(self):
        d = self.d(extra="BYTE_ORDER MSB_FIRST", overrides=[("C 0 1000", "C 0 50000")])
        self.assertEqual(d.read_scalar("VAL", bytes(self.bin), 0x1000)["raw"], 0xC800)
        d2 = self.d(extra="BYTE_ORDER MSB_LAST")
        self.assertEqual(d2.read_scalar("VAL", bytes(self.bin), 0x1000)["raw"], 200)

    def test_address_space_extension_rejected(self):
        for marker in ("ECU_ADDRESS_EXTENSION 1", "REF_MEMORY_SEGMENT SECONDARY"):
            d = self.d(extra=marker)
            with self.assertRaisesRegex(A2LError, "mapping"):
                d.read_scalar("VAL", bytes(self.bin), 0x1000)

    def test_invalid_record_addressing_mode_rejected(self):
        d = self.d(overrides=[("COLUMN_DIR DIRECT", "COLUMN_DIR INDIRECT")])
        with self.assertRaisesRegex(A2LError, "addressing mode"):
            d.read_scalar("VAL", bytes(self.bin), 0x1000)


if __name__ == "__main__":
    unittest.main()
