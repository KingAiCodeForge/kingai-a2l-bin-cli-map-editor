"""Conservative read-only inline STD_AXIS RECORD_LAYOUT interpreter.

Positions are ordinals, not offsets. Offsets depend on counts, storage widths,
and potential alignment. We refuse layouts requiring an unqualified pad,
pointer dereference, or static-address-offset interpretation. No map writes.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import TYPE_CHECKING

from .core import A2LError, READ_STORAGE, _float, _number
from .tables import (
    MAX_POINTS_PER_AXIS, MAX_TABLE_ELEMENTS,
    _fixed_axis, _validated_physical,
)

if TYPE_CHECKING:
    from .core import A2LDefinition, Block

ROLE_WIDTHS = {
    "FNC_VALUES": 5,
    "AXIS_PTS_X": 5,
    "AXIS_PTS_Y": 5,
    "NO_AXIS_PTS_X": 3,
    "NO_AXIS_PTS_Y": 3,
    "FIX_NO_AXIS_PTS_X": 2,
    "FIX_NO_AXIS_PTS_Y": 2,
}
COUNT_FORMATS = {"UBYTE", "UWORD", "ULONG"}
AXIS_KEYS = ("X", "Y")


@dataclass(frozen=True)
class RecordField:
    role: str
    position: int
    dtype: str
    index: str | None = None
    addressing: str | None = None


def _parse_layout(words: tuple[str, ...]) -> tuple[list[RecordField], dict[str, int]]:
    if not words:
        raise A2LError("Empty record layout")
    pos = 1  # first word is layout name
    fields = []
    fixed = {}
    while pos < len(words):
        role = words[pos]
        if role not in ROLE_WIDTHS:
            raise A2LError(f"Unqualified composite RECORD_LAYOUT feature: {role}")
        width = ROLE_WIDTHS[role]
        if pos + width > len(words):
            raise A2LError(f"Incomplete RECORD_LAYOUT field: {role}")
        tokens = words[pos + 1:pos + width]
        if role.startswith("FIX_NO_AXIS_PTS_"):
            axis = role[-1]
            if axis in fixed:
                raise A2LError("Duplicate fixed axis count")
            fixed[axis] = _number(tokens[0])
        else:
            ordinal = _number(tokens[0])
            dtype = tokens[1]
            if dtype not in READ_STORAGE:
                raise A2LError(f"Unsupported inline storage {dtype}")
            if role.startswith("NO_AXIS_PTS_"):
                if dtype not in COUNT_FORMATS:
                    raise A2LError("Axis count field must be an unsigned integer")
                fields.append(RecordField(role, ordinal, dtype))
            else:
                index, addressing = tokens[2], tokens[3]
                expected = ("ROW_DIR", "COLUMN_DIR") if role == "FNC_VALUES" else ("INDEX_INCR",)
                if index not in expected or addressing != "DIRECT":
                    raise A2LError(f"Unsupported inline indexing or addressing for {role}")
                fields.append(RecordField(role, ordinal, dtype, index, addressing))
        pos += width
    roles = [f.role for f in fields]
    if roles.count("FNC_VALUES") != 1 or len(set(roles)) != len(roles):
        raise A2LError("Expected one FNC_VALUES and no duplicate inline fields")
    ordinals = [f.position for f in fields]
    if len(ordinals) != len(set(ordinals)):
        raise A2LError("Overlapping RECORD_LAYOUT positions")
    fields.sort(key=lambda f: f.position)
    if ordinals and [f.position for f in fields] != list(
        range(fields[0].position, fields[0].position + len(fields))
    ):
        raise A2LError("RECORD_LAYOUT positions must be consecutive for this interpreter")
    if fields and fields[0].position not in (0, 1):
        raise A2LError("Unexpected first RECORD_LAYOUT ordinal")
    return fields, fixed


def _module_alignment(definition: "A2LDefinition", dtype: str, width: int) -> int:
    tag = {
        "UBYTE": "ALIGNMENT_BYTE", "SBYTE": "ALIGNMENT_BYTE",
        "UWORD": "ALIGNMENT_WORD", "SWORD": "ALIGNMENT_WORD",
        "ULONG": "ALIGNMENT_LONG", "SLONG": "ALIGNMENT_LONG",
        "FLOAT32_IEEE": "ALIGNMENT_FLOAT32_IEEE",
        "FLOAT64_IEEE": "ALIGNMENT_FLOAT64_IEEE",
    }.get(dtype)
    if tag is None:
        raise A2LError(f"Unhandled alignment data type {dtype}")
    # Avoid inserting guessed padding: explicit alignment is checked, never
    # silently applied. Unknown record-level alignment was rejected by parser.
    mods = definition.module.direct("MOD_COMMON")
    if len(mods) != 1:
        raise A2LError("Exactly one MOD_COMMON required for inline storage")
    vals = mods[0].words
    if tag in vals:
        at = vals.index(tag)
        if at + 1 >= len(vals):
            raise A2LError("Missing explicit alignment size")
        alignment = _number(vals[at + 1])
        if alignment <= 0 or alignment > 16 or (alignment & (alignment - 1)):
            raise A2LError(f"Unsupported declared alignment: {alignment}")
        return alignment
    return width  # conservative natural alignment: refuse unaligned fields


def read_embedded(
    definition: "A2LDefinition", node: "Block",
    firmware: bytes, base_address: int
) -> dict:
    words = node.words
    if len(words) < 9:
        raise A2LError("Incomplete CHARACTERISTIC")
    kind = words[2]
    if kind not in ("CURVE", "MAP"):
        raise A2LError("Only CURVE and MAP supported")
    definition._guard_simple_address(node)
    if "BIT_MASK" in words:
        raise A2LError("BIT_MASK table is unsupported")
    if "DEPENDENT_CHARACTERISTIC" in words or node.direct("DEPENDENT_CHARACTERISTIC"):
        raise A2LError("Dependent table requires separate evaluation")
    axis_descs = node.direct("AXIS_DESCR")
    if len(axis_descs) != (1 if kind == "CURVE" else 2):
        raise A2LError("Incorrect number of AXIS_DESCR blocks")
    if any(not desc.words or desc.words[0] not in ("STD_AXIS", "FIX_AXIS")
           for desc in axis_descs):
        raise A2LError("Inline interpreter accepts STD_AXIS and FIX_AXIS only")
    if not any(desc.words[0] == "STD_AXIS" for desc in axis_descs):
        raise A2LError("Use simple direct-table reader when no STD_AXIS exists")
    record = definition._by_name("RECORD_LAYOUT", words[4])
    fields, fixed = _parse_layout(record.words)
    if any(x in record.words for x in ("STATIC_RECORD_LAYOUT", "STATIC_ADDRESS_OFFSETS")):
        raise A2LError("Static offset allocation is not qualified")
    axes = [None] * len(axis_descs)
    max_counts = {}
    current_counts = {}
    for i, desc in enumerate(axis_descs):
        if len(desc.words) < 6:
            raise A2LError("Incomplete AXIS_DESCR")
        axis = AXIS_KEYS[i]
        maximum = _number(desc.words[3])
        if not (1 <= maximum <= MAX_POINTS_PER_AXIS):
            raise A2LError("Axis size beyond supported limits")
        if "DEPOSIT" in desc.words:
            at = desc.words.index("DEPOSIT")
            if at + 1 >= len(desc.words) or desc.words[at + 1] != "ABSOLUTE":
                raise A2LError("Differential axis deposits are unqualified")
        max_counts[axis] = maximum
        if desc.words[0] == "FIX_AXIS":
            if axis in fixed:
                raise A2LError("FIX_AXIS must not also declare a stored fixed count")
            axes[i] = _fixed_axis(definition, desc)
            current_counts[axis] = maximum
        else:
            declared_fixed = fixed.get(axis)
            if declared_fixed is not None:
                if declared_fixed != maximum:
                    raise A2LError("FIX_NO_AXIS_PTS contradicts AXIS_DESCR")
                current_counts[axis] = declared_fixed
    for axis in fixed:
        if axis not in max_counts or axis_descs[AXIS_KEYS.index(axis)].words[0] != "STD_AXIS":
            raise A2LError("FIX_NO_AXIS_PTS refers to an unstored axis")
    field_roles = {f.role for f in fields}
    for axis in max_counts:
        if axis_descs[AXIS_KEYS.index(axis)].words[0] == "STD_AXIS":
            if f"AXIS_PTS_{axis}" not in field_roles:
                raise A2LError(f"Missing AXIS_PTS_{axis} for STD_AXIS")
        elif f"AXIS_PTS_{axis}" in field_roles:
            raise A2LError(f"Unexpected stored points for FIX_AXIS_{axis}")
    if any(f"NO_AXIS_PTS_{axis}" in field_roles and axis in fixed for axis in fixed):
        raise A2LError("Fixed and dynamic counts conflict")
    # Dynamic counter and axis data must be read before the table. This is
    # necessary for the correctly calculated actual FNC_VALUES byte count.
    address = _number(words[3])
    offset0 = address - base_address
    if offset0 < 0 or offset0 > len(firmware):
        raise A2LError("Inline table base lies outside the BIN memory window")
    cursor = 0
    function = None
    parts = []
    seen_stored_axes = set()
    for field in fields:
        axis = field.role[-1] if field.role != "FNC_VALUES" else None
        fmt, width = READ_STORAGE[field.dtype]
        absolute = address + cursor
        align = _module_alignment(definition, field.dtype, width)
        if absolute % align != 0:
            raise A2LError(
                f"Unqualified implicit padding before {field.role}: "
                f"absolute address {absolute:#x} needs alignment {align}"
            )
        if field.role.startswith("NO_AXIS_PTS_"):
            if axis not in max_counts or axis_descs[AXIS_KEYS.index(axis)].words[0] != "STD_AXIS":
                raise A2LError("Dynamic counter for unsupported axis")
            if axis in current_counts:
                raise A2LError("Duplicate or contradictory axis count")
            n = 1
        elif field.role.startswith("AXIS_PTS_"):
            if axis not in current_counts:
                # No dynamic NO_AXIS_PTS field means the declared maximum is
                # taken as the stored count for this bounded layout.
                if f"NO_AXIS_PTS_{axis}" in field_roles:
                    raise A2LError("Axis data precedes dynamic count")
                current_counts[axis] = max_counts[axis]
            n = current_counts[axis]
        else:
            for axis in max_counts:
                if axis not in current_counts:
                    if f"NO_AXIS_PTS_{axis}" in field_roles:
                        raise A2LError("FNC_VALUES precedes a dynamic axis-count field")
                    current_counts[axis] = max_counts[axis]
            n = math.prod(current_counts[axis] for axis in max_counts)
            if n > MAX_TABLE_ELEMENTS:
                raise A2LError("Table exceeds bounded element limit")
        byte_count = width * n
        at = offset0 + cursor
        if at < 0 or at + byte_count > len(firmware):
            raise A2LError("Inline record field extends outside BIN")
        if field.role.startswith("AXIS_PTS_"):
            idx = AXIS_KEYS.index(axis)
            order = definition._item_byte_order(axis_descs[idx])
        else:
            order = definition._item_byte_order(node)
        raw = list(struct.unpack_from(order + fmt * n, firmware, at))
        if field.role.startswith("NO_AXIS_PTS_"):
            count = raw[0]
            if not 1 <= count <= max_counts[axis]:
                raise A2LError("Dynamic axis-count value is outside declared bounds")
            current_counts[axis] = count
        elif field.role.startswith("AXIS_PTS_"):
            idx = AXIS_KEYS.index(axis)
            desc = axis_descs[idx]
            lower, upper = _float(desc.words[4]), _float(desc.words[5])
            physical = _validated_physical(
                definition, desc.words[2], raw, lower, upper
            )
            axes[idx] = {
                "kind": "STD_AXIS", "source": "inline_RECORD_LAYOUT",
                "stored": True, "a2l_address": absolute, "bin_offset": at,
                "count": n, "raw_values": raw, "physical_values": physical,
                "conversion": desc.words[2], "storage_format": order + fmt,
                "index_mode": field.index,
                "count_source": ("NO_AXIS_PTS_" + axis if "NO_AXIS_PTS_" + axis in field_roles
                                 else "FIX_NO_AXIS_PTS_" + axis if axis in fixed
                                 else "MAX_AXIS_POINTS"),
            }
            seen_stored_axes.add(axis)
        else:
            lower, upper = _float(words[7]), _float(words[8])
            physical = _validated_physical(
                definition, words[6], raw, lower, upper
            )
            function = {
                "raw": raw, "physical": physical,
                "bin_offset": at, "a2l_address": absolute, "n": n,
                "order": field.index, "storage_format": order + fmt,
            }
        parts.append({
            "role": field.role, "position": field.position, "a2l_address": absolute,
            "bin_offset": at, "bytes": byte_count, "elements": n, "type": field.dtype,
        })
        cursor += byte_count
    if function is None or len(seen_stored_axes) != sum(
        desc.words[0] == "STD_AXIS" for desc in axis_descs
    ):
        raise A2LError("Incomplete inline STD_AXIS record")
    if any(axis is None for axis in axes):
        raise A2LError("Unresolved inline axis declaration")
    return {
        "name": words[0], "kind": kind,
        "a2l_address": address,
        "bin_offset": function["bin_offset"],
        "dimensions": [axis["count"] for axis in axes],
        "axes": axes,
        "flat_raw_values": function["raw"],
        "flat_physical_values": function["physical"],
        "flat_storage_order": function["order"],
        "storage_format": function["storage_format"],
        "item_count": function["n"],
        "record_fields": parts,
        "read_only": True,
        "cell_coordinate_mapping_qualified": False,
        "note": "Inline storage offsets decoded; coordinate mapping and writes not qualified.",
    }
