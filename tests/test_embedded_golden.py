"""Synthetic, independently byte-positioned golden fixtures for ASAM inline layouts.

No customer BIN/A2L, native-tool parity, or writable tables. Expected offsets
are constructed by hand and checked against the read-only reader. Sources:
ASAM MCD-2 MC RECORD_LAYOUT / alignment / RESERVED / INDEX_DECR conventions;
Intrepid Control Systems ASAP2 Editor "Create/Edit Record Layouts".
"""
import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from kingai_a2l.core import A2LDefinition, A2LError


def axis(axis_max=4, lower=0, upper=255):
    return ("/begin AXIS_DESCR STD_AXIS NO_INPUT_QUANTITY "
            f"NO_COMPU_METHOD {axis_max} {lower} {upper} /end AXIS_DESCR")


def definition(layout, descriptors=None, kind="CURVE", common="", bounds="0 255"):
    descriptors = descriptors if descriptors is not None else axis()
    a2l = f"""
    ASAP2_VERSION 1 71
    /begin PROJECT P ""
      /begin MODULE M ""
        /begin MOD_COMMON "" BYTE_ORDER MSB_LAST {common} /end MOD_COMMON
        /begin RECORD_LAYOUT L
          {layout}
        /end RECORD_LAYOUT
        /begin CHARACTERISTIC K "" {kind} 0x8000 L 0 NO_COMPU_METHOD {bounds}
          {descriptors}
        /end CHARACTERISTIC
      /end MODULE
    /end PROJECT
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "synthetic_only.a2l"
        path.write_text(a2l, encoding="utf-8")
        return A2LDefinition.load(path)


class ReadOnlyGoldenLayouts(unittest.TestCase):
    def read(self, definition_, image, base=0x8000):
        original = hashlib.sha256(image).hexdigest()
        result = definition_.read_table("K", image, base)
        self.assertEqual(hashlib.sha256(image).hexdigest(), original)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["cell_coordinate_mapping_qualified"])
        return result

    def test_module_declared_word_alignment_expands_cursor(self):
        layout = ("NO_AXIS_PTS_X 1 UBYTE "
                  "AXIS_PTS_X 2 UWORD INDEX_INCR DIRECT "
                  "FNC_VALUES 3 UWORD ROW_DIR DIRECT")
        image = b"\x02\xee" + struct.pack("<4H", 100, 200, 11, 22)
        got = self.read(definition(layout, axis(4, 0, 65535),
                                   common="ALIGNMENT_WORD 2"), image)
        self.assertEqual([p["bin_offset"] for p in got["record_fields"]], [0, 2, 6])
        self.assertEqual([p["padding_before"] for p in got["record_fields"]], [0, 1, 0])
        self.assertEqual(got["record_size_bytes"], 10)
        self.assertEqual(got["axes"][0]["raw_values"], [100, 200])
        self.assertEqual(got["flat_raw_values"], [11, 22])

    def test_record_alignment_overrides_mod_common(self):
        layout = ("NO_AXIS_PTS_X 1 UBYTE "
                  "AXIS_PTS_X 2 UWORD INDEX_INCR DIRECT "
                  "FNC_VALUES 3 UWORD ROW_DIR DIRECT "
                  "ALIGNMENT_WORD 4")
        image = (b"\x03\xde\xad\xbe" + struct.pack("<3H", 100, 200, 300)
                 + b"\x77\x88" + struct.pack("<3H", 11, 22, 33))
        got = self.read(definition(layout, axis(4, 0, 65535),
                                   common="ALIGNMENT_WORD 2"), image)
        self.assertEqual([p["bin_offset"] for p in got["record_fields"]], [0, 4, 12])
        self.assertEqual([p["padding_before"] for p in got["record_fields"]], [0, 3, 2])
        self.assertEqual(got["record_size_bytes"], 18)
        self.assertEqual(got["flat_raw_values"], [11, 22, 33])

    def test_reserved_byte_word_long_are_skipped_uninterpreted(self):
        layout = ("NO_AXIS_PTS_X 1 UBYTE "
                  "RESERVED 2 BYTE "
                  "AXIS_PTS_X 3 SBYTE INDEX_INCR DIRECT "
                  "RESERVED 4 WORD "
                  "FNC_VALUES 5 UWORD ROW_DIR DIRECT "
                  "RESERVED 6 LONG")
        image = (b"\x02\xaa" + struct.pack("<2b", -3, 4) + b"\xc0\xc1"
                 + struct.pack("<2H", 101, 102) + b"\xff\xff"
                 + b"\xdd\xee\xff\x22")
        got = self.read(definition(layout, axis(4, -128, 127),
                                   common="ALIGNMENT_LONG 4"), image)
        self.assertEqual([p["bin_offset"] for p in got["record_fields"]],
                         [0, 1, 2, 4, 6, 12])
        self.assertEqual([p["bytes"] for p in got["record_fields"]],
                         [1, 1, 2, 2, 4, 4])
        self.assertEqual([p["role"] for p in got["record_fields"]].count("RESERVED"), 3)
        self.assertEqual([p["padding_before"] for p in got["record_fields"]],
                         [0, 0, 0, 0, 0, 2])
        self.assertEqual(got["flat_raw_values"], [101, 102])
        self.assertEqual(got["record_size_bytes"], 16)

    def test_index_decr_reverses_logical_index_not_memory_address(self):
        template = ("NO_AXIS_PTS_X 1 UBYTE "
                    "AXIS_PTS_X 2 SBYTE %s DIRECT "
                    "FNC_VALUES 3 SWORD ROW_DIR DIRECT")
        image = b"\x03" + struct.pack("<3b", 30, 20, 10) + struct.pack("<3h", -300, 0, 300)
        dec = self.read(definition(template % "INDEX_DECR",
                                   axis(4, -128, 127), bounds="-32768 32767"), image)
        inc = self.read(definition(template % "INDEX_INCR",
                                   axis(4, -128, 127), bounds="-32768 32767"), image)
        self.assertEqual(dec["axes"][0]["raw_values"], [10, 20, 30])
        self.assertEqual(dec["axes"][0]["memory_order_raw_values"], [30, 20, 10])
        self.assertEqual(dec["axes"][0]["index_bin_offsets"], [3, 2, 1])
        self.assertEqual(inc["axes"][0]["raw_values"], [30, 20, 10])
        self.assertEqual(inc["axes"][0]["index_bin_offsets"], [1, 2, 3])
        self.assertEqual(dec["flat_raw_values"], inc["flat_raw_values"])
        self.assertEqual([p["bin_offset"] for p in dec["record_fields"]], [0, 1, 4])

    def test_mixed_width_map_calculates_function_start_and_axis_order(self):
        layout = ("NO_AXIS_PTS_X 1 UBYTE "
                  "NO_AXIS_PTS_Y 2 UBYTE "
                  "AXIS_PTS_X 3 SWORD INDEX_INCR DIRECT "
                  "AXIS_PTS_Y 4 ULONG INDEX_DECR DIRECT "
                  "FNC_VALUES 5 SBYTE COLUMN_DIR DIRECT")
        descriptors = axis(4, -128, 127) + " " + axis(5, 0, 100000)
        image = (b"\x02\x02" + struct.pack("<2h", -2, 4) + b"\xaa\xbb"
                 + struct.pack("<2I", 20000, 10000) + struct.pack("<4b", -4, 5, -6, 7))
        got = self.read(definition(layout, descriptors, "MAP",
                                   common="ALIGNMENT_WORD 2 ALIGNMENT_LONG 4",
                                   bounds="-128 127"), image)
        self.assertEqual([p["bin_offset"] for p in got["record_fields"]],
                         [0, 1, 2, 8, 16])
        self.assertEqual(got["dimensions"], [2, 2])
        self.assertEqual(got["axes"][0]["raw_values"], [-2, 4])
        self.assertEqual(got["axes"][1]["raw_values"], [10000, 20000])
        self.assertEqual(got["axes"][1]["index_bin_offsets"], [12, 8])
        self.assertEqual(got["flat_raw_values"], [-4, 5, -6, 7])
        self.assertEqual(got["flat_storage_order"], "COLUMN_DIR")
        self.assertEqual(got["record_size_bytes"], 20)

    def test_function_storage_width_matrix(self):
        types = [
            ("UBYTE", "B", 1, 2), ("SBYTE", "b", 1, 2),
            ("UWORD", "H", 2, 2), ("SWORD", "h", 2, 2),
            ("ULONG", "I", 4, 4), ("SLONG", "i", 4, 4),
            ("FLOAT32_IEEE", "f", 4, 4), ("FLOAT64_IEEE", "d", 8, 8),
        ]
        common = ("ALIGNMENT_BYTE 1 ALIGNMENT_WORD 2 ALIGNMENT_LONG 4 "
                  "ALIGNMENT_FLOAT32_IEEE 4 ALIGNMENT_FLOAT64_IEEE 8")
        for dtype, fmt, width, fn_at in types:
            with self.subTest(dtype=dtype):
                layout = ("NO_AXIS_PTS_X 1 UBYTE "
                          "AXIS_PTS_X 2 UBYTE INDEX_INCR DIRECT "
                          f"FNC_VALUES 3 {dtype} ROW_DIR DIRECT")
                value = 5.0 if dtype.startswith("FLOAT") else 5
                image = b"\x01\x09" + bytes(fn_at - 2) + struct.pack("<" + fmt, value)
                got = self.read(definition(layout, axis(), common=common), image)
                self.assertEqual(got["record_fields"][-1]["bin_offset"], fn_at)
                self.assertEqual(got["record_fields"][-1]["bytes"], width)
                self.assertEqual(got["flat_raw_values"], [value])
                self.assertEqual(got["record_size_bytes"], fn_at + width)

    def test_rejects_missing_alignment_or_insufficient_bin(self):
        layout = ("NO_AXIS_PTS_X 1 UBYTE "
                  "AXIS_PTS_X 2 UWORD INDEX_INCR DIRECT "
                  "FNC_VALUES 3 UWORD ROW_DIR DIRECT")
        image = b"\x02\xee" + struct.pack("<4H", 100, 200, 11, 22)
        with self.assertRaisesRegex(A2LError, "padding"):
            definition(layout, axis(4, 0, 65535)).read_table("K", image, 0x8000)
        with self.assertRaisesRegex(A2LError, "outside BIN"):
            definition(layout, axis(4, 0, 65535),
                       common="ALIGNMENT_WORD 2").read_table("K", image[:-1], 0x8000)

    def test_rejects_invalid_reserved_alignment_and_static_modes(self):
        base = ("NO_AXIS_PTS_X 1 UBYTE "
                "AXIS_PTS_X 2 UBYTE INDEX_INCR DIRECT "
                "FNC_VALUES 3 UBYTE ROW_DIR DIRECT ")
        cases = (
            base + "RESERVED 4 UBYTE",
            base + "ALIGNMENT_WORD 3",
            base + "ALIGNMENT_WORD 2 ALIGNMENT_WORD 4",
            base + "STATIC_RECORD_LAYOUT",
            base + "STATIC_ADDRESS_OFFSETS",
            base.replace("INDEX_INCR DIRECT", "INDEX_INCR PWORD"),
        )
        for layout in cases:
            with self.subTest(layout=layout), self.assertRaises(A2LError):
                definition(layout).read_table("K", bytes(24), 0x8000)

    def test_map_writes_remain_disabled(self):
        layout = ("NO_AXIS_PTS_X 1 UBYTE "
                  "AXIS_PTS_X 2 UBYTE INDEX_DECR DIRECT "
                  "FNC_VALUES 3 UBYTE ROW_DIR DIRECT")
        d = definition(layout)
        with self.assertRaisesRegex(A2LError, "Only VALUE"):
            d.edit_raw("K", bytes([2, 2, 1, 4, 5]), 0x8000, 11)

    def test_alignment_uses_absolute_ecu_address_not_bin_offset(self):
        layout = ("NO_AXIS_PTS_X 1 UBYTE "
                  "AXIS_PTS_X 2 UWORD INDEX_INCR DIRECT "
                  "FNC_VALUES 3 UWORD ROW_DIR DIRECT")
        # Item starts at 0x8000 but at offset 3 of an image based at 0x7FFD.
        image = b"\xfe\xfd\xfc\x02\xaa" + struct.pack("<4H", 10, 20, 30, 40)
        got = self.read(definition(layout, axis(4, 0, 65535),
                                   common="ALIGNMENT_WORD 2"), image, base=0x7FFD)
        self.assertEqual([p["bin_offset"] for p in got["record_fields"]], [3, 5, 9])
        self.assertEqual([p["a2l_address"] for p in got["record_fields"]],
                         [0x8000, 0x8002, 0x8006])
        self.assertEqual(got["flat_raw_values"], [30, 40])

    def test_explicit_packed_word_alignment_one(self):
        layout = ("NO_AXIS_PTS_X 1 UBYTE "
                  "AXIS_PTS_X 2 UWORD INDEX_INCR DIRECT "
                  "FNC_VALUES 3 UWORD ROW_DIR DIRECT")
        # Explicit packed WORD storage must not be silently realigned.
        image = b"\x02" + struct.pack("<4H", 10, 20, 30, 40)
        got = self.read(definition(layout, axis(4, 0, 65535),
                                   common="ALIGNMENT_WORD 1"), image)
        self.assertEqual([p["bin_offset"] for p in got["record_fields"]], [0, 1, 5])
        self.assertEqual(got["record_size_bytes"], 9)

    def test_big_endian_index_decr_reverses_elements_not_bytes(self):
        layout = ("NO_AXIS_PTS_X 1 UBYTE "
                  "AXIS_PTS_X 2 UWORD INDEX_DECR DIRECT "
                  "FNC_VALUES 3 UWORD ROW_DIR DIRECT")
        desc = axis(4, 0, 65535).replace(
            "/end AXIS_DESCR", "BYTE_ORDER MSB_FIRST /end AXIS_DESCR"
        )
        image = (b"\x03\xee" + struct.pack(">3H", 0x1234, 0x5678, 0x9ABC)
                 + struct.pack("<3H", 11, 22, 33))
        got = self.read(definition(layout, desc, common="ALIGNMENT_WORD 2"), image)
        self.assertEqual(got["axes"][0]["memory_order_raw_values"],
                         [0x1234, 0x5678, 0x9ABC])
        self.assertEqual(got["axes"][0]["raw_values"],
                         [0x9ABC, 0x5678, 0x1234])
        self.assertEqual(got["axes"][0]["index_bin_offsets"], [6, 4, 2])
        self.assertEqual(got["axes"][0]["storage_format"], ">H")
        self.assertEqual(got["flat_raw_values"], [11, 22, 33])


if __name__ == "__main__":
    unittest.main()
