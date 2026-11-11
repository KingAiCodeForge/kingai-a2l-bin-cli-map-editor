"""Conservative, read-only A2L CURVE/MAP decoding for simple contiguous layouts.

This adapter does NOT determine whether a map is used by the firmware.
Only direct FNC_VALUES layouts with fixed or external shared axes are accepted.
"""
from __future__ import annotations

import math
import struct
from typing import TYPE_CHECKING

from .core import A2LError, Block, READ_STORAGE, _float, _lookup, _number

if TYPE_CHECKING:
    from .core import A2LDefinition

MAX_POINTS_PER_AXIS = 1024
MAX_TABLE_ELEMENTS = 65536


def _words_after(words: tuple[str, ...], token: str, count: int) -> list[str]:
    idx = _lookup(words, token)
    if idx + count >= len(words):
        raise A2LError(f"Incomplete {token} keyword")
    return list(words[idx + 1:idx + 1 + count])


def _address(firmware: bytes, base_address: int, address: int, size: int) -> int:
    offset = address - base_address
    if offset < 0 or size < 0 or offset + size > len(firmware):
        raise A2LError("A2L table or axis address lies outside BIN memory window")
    return offset


def _factors(desc: Block) -> tuple[int, float, float]:
    if len(desc.words) < 6:
        raise A2LError("Incomplete AXIS_DESCR")
    count = _number(desc.words[3])
    if count < 1 or count > MAX_POINTS_PER_AXIS:
        raise A2LError("Axis point count is outside supported bounds")
    lower, upper = _float(desc.words[4]), _float(desc.words[5])
    if lower > upper:
        raise A2LError("Axis lower/upper bounds are inverted")
    return count, lower, upper


def _validated_physical(
    definition: "A2LDefinition", conversion: str, raw_values: list[int | float],
    lower: float, upper: float
) -> list[float]:
    physical = [definition._physical(conversion, r) for r in raw_values]
    if any(not math.isfinite(x) or x < lower or x > upper for x in physical):
        raise A2LError("Converted table or axis values exceed A2L bounds")
    return physical


def _fixed_axis(definition: "A2LDefinition", desc: Block) -> dict:
    count, lower, upper = _factors(desc)
    methods = (int("FIX_AXIS_PAR_DIST" in desc.words)
               + int("FIX_AXIS_PAR" in desc.words)
               + len(desc.direct("FIX_AXIS_PAR_LIST")))
    if methods != 1:
        raise A2LError("FIX_AXIS requires exactly one supported point source")
    if "FIX_AXIS_PAR_DIST" in desc.words:
        first_str, step_str, count_str = _words_after(desc.words, "FIX_AXIS_PAR_DIST", 3)
        first, step, stated_count = _float(first_str), _float(step_str), _number(count_str)
        if count != stated_count:
            raise A2LError("FIX_AXIS_PAR_DIST count differs from AXIS_DESCR")
        values = [first + n * step for n in range(count)]
        source = "FIX_AXIS_PAR_DIST"
    elif "FIX_AXIS_PAR" in desc.words:
        first_str, shift_str, count_str = _words_after(desc.words, "FIX_AXIS_PAR", 3)
        first, shift, stated_count = _float(first_str), _float(shift_str), _number(count_str)
        if count != stated_count:
            raise A2LError("FIX_AXIS_PAR count differs from AXIS_DESCR")
        if not -32 <= shift <= 32:
            raise A2LError("FIX_AXIS_PAR shift is outside supported numeric limits")
        values = [first + n * (2.0 ** shift) for n in range(count)]
        source = "FIX_AXIS_PAR"
    else:
        lists = desc.direct("FIX_AXIS_PAR_LIST")
        values = [_float(w) for w in lists[0].words]
        if len(values) != count:
            raise A2LError("FIX_AXIS_PAR_LIST length differs from AXIS_DESCR")
        source = "FIX_AXIS_PAR_LIST"
    converted = _validated_physical(definition, desc.words[2], values, lower, upper)
    return {"kind": "FIX_AXIS", "source": source, "stored": False,
            "count": count, "raw_values": values, "physical_values": converted,
            "conversion": desc.words[2]}


def _external_axis(
    definition: "A2LDefinition", desc: Block, firmware: bytes, base_address: int
) -> dict:
    count, lower, upper = _factors(desc)
    axis_name = _words_after(desc.words, "AXIS_PTS_REF", 1)[0]
    node = definition._by_name("AXIS_PTS", axis_name)
    if len(node.words) < 10:
        raise A2LError("Incomplete AXIS_PTS declaration")
    definition._guard_simple_address(node)
    if "DEPOSIT" in desc.words or "DEPOSIT" in node.words:
        for words in (desc.words, node.words):
            if "DEPOSIT" in words and _words_after(words, "DEPOSIT", 1) != ["ABSOLUTE"]:
                raise A2LError("Differentially stored axis points are unsupported")
    if node.words[6] != desc.words[2]:
        raise A2LError("COM_AXIS conversion differs from AXIS_PTS definition")
    if _number(node.words[7]) != count:
        raise A2LError("COM_AXIS point count differs from referenced AXIS_PTS")
    record = definition._by_name("RECORD_LAYOUT", node.words[4])
    words = record.words
    if (len(words) != 6 or words[1] != "AXIS_PTS_X"
            or words[2] not in ("0", "1")
            or words[3] not in READ_STORAGE or words[4] != "INDEX_INCR"
            or words[5] != "DIRECT"):
        raise A2LError("COM_AXIS requires contiguous direct AXIS_PTS_X record layout")
    fmt_char, size = READ_STORAGE[words[3]]
    address = _number(node.words[2])
    offset = _address(firmware, base_address, address, count * size)
    order = definition._item_byte_order(node)
    if "BYTE_ORDER" in desc.words and definition._item_byte_order(desc) != order:
        raise A2LError("COM_AXIS axis byte-order override conflicts with AXIS_PTS")
    raw_values = list(struct.unpack_from(order + fmt_char * count, firmware, offset))
    converted = _validated_physical(definition, desc.words[2], raw_values, lower, upper)
    return {"kind": "COM_AXIS", "source": axis_name, "stored": True,
            "address": address, "bin_offset": offset,
            "count": count, "raw_values": raw_values, "physical_values": converted,
            "conversion": desc.words[2], "storage_format": order + fmt_char}


def read_table(
    definition: "A2LDefinition", name: str, firmware: bytes, base_address: int
) -> dict:
    node = definition._by_name("CHARACTERISTIC", name)
    words = node.words
    if len(words) < 9:
        raise A2LError("Incomplete CHARACTERISTIC")
    kind = words[2]
    if kind not in ("CURVE", "MAP"):
        raise A2LError(f"Only 1D CURVE and 2D MAP are supported, not {kind}")
    if any(desc.words and desc.words[0] == "STD_AXIS"
           for desc in node.direct("AXIS_DESCR")):
        from .embedded import read_embedded
        return read_embedded(definition, node, firmware, base_address)
    definition._guard_simple_address(node)
    if "BIT_MASK" in words:
        raise A2LError("BIT_MASK table requires mask-aware decoding")
    if "DEPENDENT_CHARACTERISTIC" in words or node.direct("DEPENDENT_CHARACTERISTIC"):
        raise A2LError("Dependent/virtual characteristics require separate evaluation")
    expected_axes = 1 if kind == "CURVE" else 2
    axis_descs = node.direct("AXIS_DESCR")
    if len(axis_descs) != expected_axes:
        raise A2LError(f"{kind} needs exactly {expected_axes} AXIS_DESCR blocks")
    axes = []
    for desc in axis_descs:
        if not desc.words:
            raise A2LError("Empty AXIS_DESCR")
        if desc.words[0] == "FIX_AXIS":
            axes.append(_fixed_axis(definition, desc))
        elif desc.words[0] == "COM_AXIS":
            axes.append(_external_axis(definition, desc, firmware, base_address))
        else:
            raise A2LError(f"Axis kind {desc.words[0]} is unsupported")
    count = 1
    for axis in axes:
        count *= axis["count"]
    if count > MAX_TABLE_ELEMENTS:
        raise A2LError("Table size exceeds bounded read-only capability")
    record = definition._by_name("RECORD_LAYOUT", words[4])
    # The only supported layout is a single contiguous FNC_VALUES stream.
    # All mixed axis/ID/dynamic-length or reserved structures fail closed.
    layout = record.words
    if (len(layout) != 6 or layout[1] != "FNC_VALUES"
            or layout[2] not in ("0", "1")
            or layout[3] not in READ_STORAGE
            or layout[4] not in ("ROW_DIR", "COLUMN_DIR")
            or layout[5] != "DIRECT"):
        raise A2LError("Table requires sole contiguous direct FNC_VALUES layout")
    fmt_char, size = READ_STORAGE[layout[3]]
    address = _number(words[3])
    offset = _address(firmware, base_address, address, count * size)
    order = definition._item_byte_order(node)
    raw_values = list(struct.unpack_from(order + fmt_char * count, firmware, offset))
    lower, upper = _float(words[7]), _float(words[8])
    physical = _validated_physical(definition, words[6], raw_values, lower, upper)
    return {
        "name": name, "kind": kind, "a2l_address": address, "bin_offset": offset,
        "dimensions": [axis["count"] for axis in axes],
        "axes": axes,
        "flat_raw_values": raw_values,
        "flat_physical_values": physical,
        "flat_storage_order": layout[4],
        "storage_format": order + fmt_char,
        "item_count": count,
        "read_only": True,
        "cell_coordinate_mapping_qualified": False,
        "note": "Flat storage order only. Cell coordinate mapping and writes not yet qualified.",
    }
