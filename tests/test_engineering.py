"""Exact-decimal engineering-value edits with explicit quantization tolerances."""
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from kingai_a2l.core import A2LDefinition, A2LError

SAMPLE = '''
ASAP2_VERSION 1 71
/begin PROJECT P ""
 /begin MODULE M ""
  /begin MOD_COMMON "" BYTE_ORDER MSB_LAST /end MOD_COMMON
  /begin RECORD_LAYOUT R FNC_VALUES 1 UWORD ROW_DIR DIRECT /end RECORD_LAYOUT
  /begin COMPU_METHOD L "" LINEAR "%5.2" "kPa"
   COEFFS_LINEAR 0.1 1
  /end COMPU_METHOD
  /begin COMPU_METHOD RF "" RAT_FUNC "%5.2" "rpm"
   COEFFS 0 2 0 0 0 1
  /end COMPU_METHOD
  /begin CHARACTERISTIC ONE "" VALUE 0x3000 R 0 L 0 1000 /end CHARACTERISTIC
  /begin CHARACTERISTIC TWO "" VALUE 0x3002 R 0 RF 0 1000 /end CHARACTERISTIC
 /end MODULE
/end PROJECT
'''


class EngineeringTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.a2l = root / "synthetic.a2l"
        self.a2l.write_text(SAMPLE, encoding="utf-8")
        self.image = bytearray(16)
        struct.pack_into("<2H", self.image, 0, 63, 220)
        self.bin = root / "source.bin"
        self.bin.write_bytes(self.image)
        self.root = root
        self.defn = A2LDefinition.load(self.a2l)

    def test_linear_exact_and_reversible(self):
        result, receipt = self.defn.edit_physical("ONE", self.image, 0x3000, "7.3")
        self.assertEqual(receipt["new_raw"], 63)
        self.assertEqual(receipt["actual_physical_decimal"], "7.3")
        self.assertEqual(receipt["quantization_error_decimal"], "0.0")
        self.assertEqual(result, self.image)

    def test_rational_inverse_direction(self):
        result, receipt = self.defn.edit_physical("TWO", self.image, 0x3000, "110")
        self.assertEqual(receipt["new_raw"], 220)
        self.assertEqual(receipt["actual_physical_decimal"], "110")
        self.assertEqual(result, self.image)

    def test_unrepresentable_target_rejected_without_tolerance(self):
        with self.assertRaisesRegex(A2LError, "Quantization error"):
            self.defn.edit_physical("TWO", self.image, 0x3000, "110.25")
        result, receipt = self.defn.edit_physical(
            "TWO", self.image, 0x3000, "110.25", "0.25"
        )
        self.assertEqual(receipt["new_raw"], 220)
        self.assertEqual(receipt["quantization_rule"], "nearest_integer_half_even")
        self.assertEqual(receipt["quantization_error_decimal"], "0.25")
        self.assertEqual(result, self.image)

    def test_negative_quantization_tolerance_rejected(self):
        with self.assertRaisesRegex(A2LError, "negative"):
            self.defn.edit_physical("ONE", self.image, 0x3000, "7.3", "-1")

    def test_zero_slope_and_nonfinite_rejected(self):
        for invalid in ("nan", "Infinity", "1e100000"):
            with self.assertRaises(A2LError):
                self.defn.edit_physical("ONE", self.image, 0x3000, invalid)
        self.a2l.write_text(SAMPLE.replace("0.1 1", "0 1"), encoding="utf-8")
        d = A2LDefinition.load(self.a2l)
        with self.assertRaisesRegex(A2LError, "zero slope"):
            d.edit_physical("ONE", self.image, 0x3000, "7.3")

    def test_cli_new_bin_and_report(self):
        output = self.root / "output.bin"
        cmd = [
            sys.executable, "-m", "kingai_a2l", "edit-physical",
            "--a2l", str(self.a2l), "--bin", str(self.bin),
            "--base-address", "0x3000", "--name", "ONE",
            "--physical", "8.3", "--max-quantization-error", "0",
            "--expected-sha256", hashlib.sha256(self.bin.read_bytes()).hexdigest(),
            "--expected-a2l-sha256", hashlib.sha256(self.a2l.read_bytes()).hexdigest(),
            "--output", str(output),
        ]
        run = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        receipt = json.loads(run.stdout)
        self.assertEqual(receipt["change"]["new_raw"], 73)
        self.assertEqual(receipt["change"]["requested_physical"], "8.3")
        self.assertTrue(Path(str(output) + ".audit.json").exists())
        self.assertEqual(struct.unpack_from("<H", output.read_bytes())[0], 73)
        self.assertEqual(struct.unpack_from("<H", self.bin.read_bytes())[0], 63)


if __name__ == "__main__":
    unittest.main()
