"""Exact-decimal engineering-value proposal and bounded scalar edit."""

from __future__ import annotations

from decimal import (
    Decimal, DecimalException, InvalidOperation, ROUND_HALF_EVEN, localcontext,
)
import math
from typing import TYPE_CHECKING

from .core import A2LError, _lookup

if TYPE_CHECKING:
    from .core import A2LDefinition


def _decimal(value: str | int | Decimal, label: str) -> Decimal:
    text = str(value)
    if len(text) > 72:
        raise A2LError(f"{label} is too long")
    try:
        dec = Decimal(text)
    except InvalidOperation as exc:
        raise A2LError(f"{label} is not a valid decimal") from exc
    if not dec.is_finite() or dec.adjusted() < -50 or dec.adjusted() > 50:
        raise A2LError(f"{label} is nonfinite or outside numeric limits")
    return dec


def _method(definition: "A2LDefinition", name: str) -> tuple[str, tuple[Decimal, ...]]:
    if name in ("NO_COMPU_METHOD", "IDENTICAL"):
        return "IDENTICAL", ()
    node = definition._by_name("COMPU_METHOD", name)
    if len(node.words) < 3:
        raise A2LError("Incomplete COMPU_METHOD")
    category = node.words[2]
    if category == "IDENTICAL":
        return "IDENTICAL", ()
    if category == "LINEAR":
        idx = _lookup(node.words, "COEFFS_LINEAR")
        if idx + 2 >= len(node.words):
            raise A2LError("Incomplete COEFFS_LINEAR")
        return category, tuple(_decimal(x, "COEFFS_LINEAR") for x in node.words[idx+1:idx+3])
    if category == "RAT_FUNC":
        idx = _lookup(node.words, "COEFFS")
        if idx + 6 >= len(node.words):
            raise A2LError("Incomplete COEFFS")
        a, b, c, d, e, f = (
            _decimal(x, "COEFFS") for x in node.words[idx+1:idx+7]
        )
        if a != 0 or d != 0 or e != 0 or b == 0 or f == 0:
            raise A2LError("Only affine invertible RAT_FUNC coefficients supported")
        return category, (a, b, c, d, e, f)
    raise A2LError(f"Inverse for {category} is unsupported")


def edit_physical(
    definition: "A2LDefinition",
    name: str,
    firmware: bytes,
    base_address: int,
    requested_physical: str,
    max_quantization_error: str = "0",
) -> tuple[bytes, dict]:
    requested = _decimal(requested_physical, "Physical target")
    error_limit = _decimal(max_quantization_error, "Quantization error limit")
    if error_limit < 0:
        raise A2LError("Quantization error limit cannot be negative")
    layout = definition.scalar(name)
    category, coefficients = _method(definition, layout["conversion"])
    try:
        with localcontext() as ctx:
            ctx.prec = 50
            if category == "IDENTICAL":
                ideal_raw = requested
            elif category == "LINEAR":
                a, b = coefficients
                if a == 0:
                    raise A2LError("LINEAR conversion has zero slope")
                ideal_raw = (requested - b) / a
            elif category == "RAT_FUNC":
                _, b, c, _, _, f = coefficients
                ideal_raw = (b * requested + c) / f
            else:
                raise A2LError("Unsupported conversion")
            if not ideal_raw.is_finite() or ideal_raw.adjusted() > 45:
                raise A2LError("Requested physical value is not representable")
            raw = int(ideal_raw.to_integral_value(rounding=ROUND_HALF_EVEN))
            # Compute exact decimal engineering result, not a float approximation.
            if category == "IDENTICAL":
                actual = Decimal(raw)
            elif category == "LINEAR":
                a, b = coefficients
                actual = a * Decimal(raw) + b
            else:
                _, b, c, _, _, f = coefficients
                actual = (f * Decimal(raw) - c) / b
            error = abs(actual - requested)
    except DecimalException as exc:
        raise A2LError(f"Decimal conversion cannot be completed: {exc}") from exc
    if error > error_limit:
        raise A2LError(
            f"Quantization error {error} exceeds declared maximum {error_limit}"
        )
    image, receipt = definition.edit_raw(name, firmware, base_address, raw)
    reread = definition.read_scalar(name, image, base_address)
    if reread["raw"] != raw or not math.isfinite(reread["physical"]):
        raise A2LError("Post-edit scalar verification failed")
    return image, {
        **receipt,
        "conversion_category": category,
        "requested_physical": str(requested),
        "actual_physical_decimal": str(actual),
        "quantization_error_decimal": str(error),
        "maximum_quantization_error_decimal": str(error_limit),
        "quantization_rule": "nearest_integer_half_even",
        "re_read_raw": reread["raw"],
    }
