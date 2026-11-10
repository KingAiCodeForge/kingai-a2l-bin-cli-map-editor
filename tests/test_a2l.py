"""Synthetic fixture tests only. No customer BIN or proprietary A2L data."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from kingai_a2l.core import A2LDefinition, A2LError, parse_a2l

SAMPLE = '''
ASAP2_VERSION 1 71
/begin PROJECT Demo "Synthetic project"
 /begin MODULE M1 "Test module"
  /begin MOD_COMMON "default order" BYTE_ORDER MSB_LAST
  /end MOD_COMMON
  /begin RECORD_LAYOUT U16_LAYOUT
   FNC_VALUES 1 UWORD COLUMN_DIR DIRECT
  /end RECORD_LAYOUT
  /begin COMPU_METHOD SCALE "Linear method" LINEAR "%6.2" "kPa"
   COEFFS_LINEAR 0.5 1
  /end COMPU_METHOD
  /begin CHARACTERISTIC KTEST "My scalar with // inside string" VALUE 0x1004 U16_LAYOUT 0 SCALE 0 1000
  /end CHARACTERISTIC
  /begin CHARACTERISTIC KMAP "Unsupported map" MAP 0x1010 U16_LAYOUT 0 SCALE 0 1000
  /end CHARACTERISTIC
 /end MODULE
/end PROJECT
'''


class A2LTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.a2l = self.root / "synthetic.a2l"
        self.a2l.write_text(SAMPLE, encoding="utf-8")
        self.source = bytearray(32)
        struct.pack_into("<H", self.source, 4, 200)
        self.bin = self.root / "synthetic.bin"
        self.bin.write_bytes(self.source)

    def definition(self):
        return A2LDefinition.load(self.a2l)

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "kingai_a2l", *args],
            capture_output=True, text=True, check=False
        )

    def test_parse_and_read_synthetic_scalar(self):
        self.assertEqual(len(parse_a2l(SAMPLE)), 1)
        item = self.definition().read_scalar("KTEST", self.bin.read_bytes(), 0x1000)
        self.assertEqual(item["raw"], 200)
        self.assertEqual(item["physical"], 101.0)
        self.assertEqual(item["bin_offset"], 4)

    def test_modify_copy_only(self):
        d = self.definition()
        new_bin, diff = d.edit_raw("KTEST", self.bin.read_bytes(), 0x1000, 300)
        self.assertEqual(d.read_scalar("KTEST", new_bin, 0x1000)["physical"], 151.0)
        self.assertEqual(diff["before_hex"], "c800")
        self.assertEqual(diff["after_hex"], "2c01")
        self.assertEqual(self.bin.read_bytes(), bytes(self.source))

    def test_map_is_not_silently_treated_as_scalar(self):
        with self.assertRaisesRegex(A2LError, "Only VALUE"):
            self.definition().read_scalar("KMAP", self.bin.read_bytes(), 0x1000)

    def test_requires_explicit_endianness(self):
        self.a2l.write_text(SAMPLE.replace("BYTE_ORDER MSB_LAST", ""), encoding="utf-8")
        with self.assertRaises(A2LError):
            self.definition().read_scalar("KTEST", self.bin.read_bytes(), 0x1000)

    def test_unknown_address_mapping_is_rejected(self):
        with self.assertRaisesRegex(A2LError, "outside BIN"):
            self.definition().read_scalar("KTEST", self.bin.read_bytes(), 0x2000)

    def test_include_and_unmatched_blocks_are_rejected(self):
        with self.assertRaisesRegex(A2LError, "include"):
            parse_a2l(SAMPLE + '\n#include "not-present.a2l"\n')
        with self.assertRaisesRegex(A2LError, "Unmatched"):
            parse_a2l(SAMPLE.replace("/end CHARACTERISTIC", "/end AXIS_PTS", 1))

    def test_unknown_conversion_fails_closed(self):
        self.a2l.write_text(SAMPLE.replace("LINEAR", "RAT_FUNC", 1), encoding="utf-8")
        with self.assertRaisesRegex(A2LError, "not supported"):
            self.definition().read_scalar("KTEST", self.bin.read_bytes(), 0x1000)

    def test_cli_read_and_export_incomplete_explicitly(self):
        base = ("--a2l", str(self.a2l), "--bin", str(self.bin),
                "--base-address", "0x1000")
        r = self.run_cli("read", *base, "--name", "KTEST")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["item"]["raw"], 200)
        r = self.run_cli("export-json", *base)
        self.assertEqual(r.returncode, 0, r.stderr)
        body = json.loads(r.stdout)
        self.assertFalse(body["complete"])
        self.assertEqual(len(body["items"]), 2)

    def test_cli_raw_edit_receipt_and_hash_gates(self):
        base = ("--a2l", str(self.a2l), "--bin", str(self.bin),
                "--base-address", "0x1000", "--name", "KTEST", "--raw", "300")
        out = self.root / "copy.bin"
        r = self.run_cli("edit-raw", *base, "--expected-sha256", "0"*64,
                         "--expected-a2l-sha256", hashlib.sha256(self.a2l.read_bytes()).hexdigest(),
                         "--output", str(out))
        self.assertEqual(r.returncode, 2)
        self.assertFalse(out.exists())
        r = self.run_cli("edit-raw", *base,
                         "--expected-sha256", hashlib.sha256(self.bin.read_bytes()).hexdigest(),
                         "--expected-a2l-sha256", hashlib.sha256(self.a2l.read_bytes()).hexdigest(),
                         "--output", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(out.exists())
        self.assertTrue(Path(str(out) + ".audit.json").exists())
        self.assertEqual(self.bin.read_bytes(), bytes(self.source))
        self.assertEqual(self.definition().read_scalar("KTEST", out.read_bytes(), 0x1000)["raw"], 300)
        again = self.run_cli("edit-raw", *base,
                             "--expected-sha256", hashlib.sha256(self.bin.read_bytes()).hexdigest(),
                             "--expected-a2l-sha256", hashlib.sha256(self.a2l.read_bytes()).hexdigest(),
                             "--output", str(out))
        self.assertEqual(again.returncode, 2)


if __name__ == "__main__":
    unittest.main()
