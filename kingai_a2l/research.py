"""Read-only A2L research inventory for AI agents.

Structural counts do not imply binary correspondence or calibration validity.
"""
from __future__ import annotations

from collections import Counter

from .core import A2LDefinition, A2LError


def _sorted_counts(counter: Counter) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: item[0]))


def summarize(definition: A2LDefinition) -> dict:
    module = definition.module
    characteristics = module.direct("CHARACTERISTIC")
    layouts = module.direct("RECORD_LAYOUT")
    axes_pts = module.direct("AXIS_PTS")
    methods = module.direct("COMPU_METHOD")
    kinds = Counter()
    axis_kinds = Counter()
    record_field_kinds = Counter()
    positions = Counter()
    layout_use = Counter()
    conversion_use = Counter()
    declaration_features = Counter()
    layout_names = {n.words[0] for n in layouts if n.words}
    ambiguous_layout_names = len(layout_names) != len([x for x in layouts if x.words])
    missing_layout_count = 0
    named_duplicate_count = (
        len(characteristics) - len({c.words[0] for c in characteristics if c.words})
    )
    for n in characteristics:
        w = n.words
        kind = w[2] if len(w) > 2 else "<incomplete>"
        kinds[kind] += 1
        if len(w) > 4:
            layout_use[w[4]] += 1
            if w[4] not in layout_names:
                missing_layout_count += 1
        if len(w) > 6:
            conversion_use[w[6]] += 1
        for desc in n.direct("AXIS_DESCR"):
            axis_kinds[desc.words[0] if desc.words else "<incomplete>"] += 1
            for kw in ("FIX_AXIS_PAR", "FIX_AXIS_PAR_DIST", "FIX_AXIS_PAR_LIST",
                       "AXIS_PTS_REF", "BYTE_ORDER", "DEPOSIT", "MONOTONY"):
                if kw in desc.words or desc.direct(kw):
                    declaration_features["AXIS_DESCR:" + kw] += 1
        for kw in ("BIT_MASK", "READ_ONLY", "CALIBRATION_ACCESS",
                   "ECU_ADDRESS_EXTENSION", "REF_MEMORY_SEGMENT",
                   "DEPENDENT_CHARACTERISTIC", "BYTE_ORDER", "MATRIX_DIM"):
            if kw in w or n.direct(kw):
                declaration_features["CHARACTERISTIC:" + kw] += 1
    for node in layouts:
        words = node.words
        if not words:
            continue
        for kw in (
            "FNC_VALUES", "AXIS_PTS_X", "AXIS_PTS_Y",
            "NO_AXIS_PTS_X", "NO_AXIS_PTS_Y", "FIX_NO_AXIS_PTS_X",
            "FIX_NO_AXIS_PTS_Y", "RESERVED", "IDENTIFICATION",
            "STATIC_RECORD_LAYOUT", "STATIC_ADDRESS_OFFSETS",
            "ALIGNMENT_WORD", "ALIGNMENT_LONG", "AXIS_RESCALE_X"
        ):
            if kw in words or node.direct(kw):
                record_field_kinds[kw] += 1
        if "FNC_VALUES" in words:
            i = words.index("FNC_VALUES")
            positions[words[i + 1] if i + 1 < len(words) else "<missing>"] += 1
    for node in axes_pts:
        w = node.words
        for kw in ("BYTE_ORDER", "DEPOSIT", "READ_ONLY",
                   "ECU_ADDRESS_EXTENSION", "REF_MEMORY_SEGMENT"):
            if kw in w:
                declaration_features["AXIS_PTS:" + kw] += 1
    method_categories = Counter(
        n.words[2] if len(n.words) > 2 else "<incomplete>" for n in methods
    )
    return {
        "schema": "kingai.a2l.structural-inventory.v1",
        "definition_sha256": definition.source_sha256,
        "module": module.words[0] if module.words else None,
        "counts": {
            "characteristics": len(characteristics),
            "record_layouts": len(layouts),
            "axis_pts": len(axes_pts),
            "conversion_methods": len(methods),
            "characteristic_duplicate_names": named_duplicate_count,
            "missing_record_layout_references": missing_layout_count,
            "ambiguous_record_layout_names": ambiguous_layout_names,
        },
        "characteristic_kinds": _sorted_counts(kinds),
        "axis_kinds": _sorted_counts(axis_kinds),
        "record_keywords": _sorted_counts(record_field_kinds),
        "fnc_values_positions": _sorted_counts(positions),
        "conversion_categories": _sorted_counts(method_categories),
        "used_conversion_references": _sorted_counts(conversion_use),
        "declaration_features": _sorted_counts(declaration_features),
        "caveat": (
            "Structure inventory only: no image pairing, validated byte offsets, "
            "physical-value parity, active ECU consumers, or flash qualification."
        ),
    }
