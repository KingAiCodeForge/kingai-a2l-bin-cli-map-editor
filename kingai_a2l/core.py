"""Strict, deliberately limited A2L/ASAP2 -> binary scalar operations.

No application-specific memory remapping, checksum repair or ECU access.
Unknown features fail closed rather than being interpreted approximately.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import struct

MAX_A2L_BYTES = 32 * 1024 * 1024
TOKEN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"|/\*[\s\S]*?\*/|//[^\n]*|/begin(?=\s)|/end(?=\s)|[^\s]+'
)
STORAGE = {
    "UBYTE": ("B", 1), "SBYTE": ("b", 1),
    "UWORD": ("H", 2), "SWORD": ("h", 2),
    "ULONG": ("I", 4), "SLONG": ("i", 4),
}
# Float values are read-only until IEEE re-encoding, inverse conversions and
# per-target native-tool parity have been independently qualified.
READ_STORAGE = {**STORAGE, "FLOAT32_IEEE": ("f", 4), "FLOAT64_IEEE": ("d", 8)}
ORDERS = {"MSB_FIRST": ">", "MSB_LAST": "<"}


class A2LError(Exception):
    """Explicitly reported input or unsupported-layout error."""


@dataclass(frozen=True)
class Block:
    kind: str
    words: tuple[str, ...]
    children: tuple["Block", ...]

    def direct(self, kind: str) -> list["Block"]:
        return [c for c in self.children if c.kind == kind]


def _tokens(source: str) -> list[str]:
    out = []
    for found in TOKEN_RE.finditer(source):
        value = found.group()
        if value.startswith("/*") or value.startswith("//"):
            continue
        if value.lower().startswith("#include") or value.lower() == "/include":
            raise A2LError("A2L #include is not supported; resolve includes explicitly first")
        out.append(value)
    if len(out) > 1_500_000:
        raise A2LError("A2L token count exceeds safety limit")
    return out


def _read_block(tokens: list[str], pos: int, depth: int) -> tuple[Block, int]:
    if depth > 60:
        raise A2LError("A2L nesting exceeds safety limit")
    if pos + 1 >= len(tokens) or tokens[pos] != "/begin":
        raise A2LError("Invalid A2L block opener")
    name = tokens[pos + 1]
    pos += 2
    words: list[str] = []
    children: list[Block] = []
    while pos < len(tokens):
        token = tokens[pos]
        if token == "/begin":
            child, pos = _read_block(tokens, pos, depth + 1)
            children.append(child)
            continue
        if token == "/end":
            if pos + 1 >= len(tokens) or tokens[pos + 1] != name:
                raise A2LError(f"Unmatched /end for A2L block {name}")
            return Block(name, tuple(words), tuple(children)), pos + 2
        words.append(token)
        pos += 1
    raise A2LError(f"Unterminated /begin {name}")


def parse_a2l(source: str) -> tuple[Block, ...]:
    tokens = _tokens(source)
    roots: list[Block] = []
    pos = 0
    while pos < len(tokens):
        if tokens[pos] == "/begin":
            node, pos = _read_block(tokens, pos, 0)
            roots.append(node)
        elif tokens[pos] == "/end":
            raise A2LError("Unexpected top-level /end")
        else:
            pos += 1  # global ASAP2_VERSION and similar tokens
    if not any(node.kind == "PROJECT" for node in roots):
        raise A2LError("No PROJECT block found")
    return tuple(roots)


def _number(s: str) -> int:
    try:
        return int(s, 16 if s.lower().startswith("0x") else 10)
    except ValueError as exc:
        raise A2LError(f"Invalid integer: {s}") from exc


def _float(s: str) -> float:
    try:
        v = float(s)
    except ValueError as exc:
        raise A2LError(f"Invalid numeric value: {s}") from exc
    if not (-float("inf") < v < float("inf")):
        raise A2LError("Non-finite numeric value")
    return v


@lru_cache(maxsize=4096)
def _affine_formula(token: str) -> tuple[float, float]:
    """Decode a quoted, numeric, affine FORMULA without executing source text."""
    if len(token) < 3 or len(token) > 258 or token[0] != '"' or token[-1] != '"':
        raise A2LError("Invalid quoted FORMULA")
    expression = token[1:-1].strip()
    if not expression or not re.fullmatch(r"[0-9eE.X+*/() \t-]+", expression):
        raise A2LError("Unsupported FORMULA syntax")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise A2LError("Invalid FORMULA syntax") from exc

    def reduce(node):
        if isinstance(node, ast.Name) and node.id == "X":
            result = (1.0, 0.0)
        elif isinstance(node, ast.Constant) and type(node.value) in (int, float):
            result = (0.0, float(node.value))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            a, b = reduce(node.operand)
            sign = -1 if isinstance(node.op, ast.USub) else 1
            result = (sign*a, sign*b)
        elif isinstance(node, ast.BinOp):
            a, b = reduce(node.left)
            c, d = reduce(node.right)
            if isinstance(node.op, ast.Add):
                result = (a+c, b+d)
            elif isinstance(node.op, ast.Sub):
                result = (a-c, b-d)
            elif isinstance(node.op, ast.Mult) and (a == 0 or c == 0):
                result = (a*d+c*b, b*d)
            elif isinstance(node.op, ast.Div) and c == 0 and d != 0:
                result = (a/d, b/d)
            else:
                raise A2LError("Non-affine or undefined FORMULA operation")
        else:
            raise A2LError("Unsupported FORMULA expression")
        if not all(math.isfinite(v) for v in result):
            raise A2LError("Non-finite FORMULA coefficient")
        return result
    try:
        return reduce(tree.body)
    except (OverflowError, RecursionError) as exc:
        raise A2LError("FORMULA numeric or nesting limit") from exc


def _lookup(words: tuple[str, ...], name: str) -> int:
    try:
        return words.index(name)
    except ValueError as exc:
        raise A2LError(f"Missing A2L keyword {name}") from exc


def _unique(blocks: list[Block], name: str, kind: str) -> Block:
    hits = [b for b in blocks if b.words and b.words[0] == name]
    if len(hits) != 1:
        raise A2LError(f"Expected exactly one {kind} named {name}; got {len(hits)}")
    return hits[0]


@dataclass(frozen=True)
class A2LDefinition:
    path: Path
    source_sha256: str
    module: Block

    @classmethod
    def load(
        cls, source_path: str | Path, module: str | None = None, *,
        source_encoding: str = "utf-8-sig",
    ) -> "A2LDefinition":
        """Source-preserving, explicitly encoded A2L load; never auto-guess codecs.

        Historical source files may use Latin-1 labels/comments. That option
        requires deliberate opt-in; unknown encodings, binary data and
        unresolved A2L includes are rejected without modifying the source.
        """
        if source_encoding not in ("utf-8-sig", "latin-1"):
            raise A2LError("Unsupported explicit A2L encoding")
        path = Path(source_path)
        if path.stat().st_size > MAX_A2L_BYTES:
            raise A2LError("A2L is larger than the bounded import limit")
        blob = path.read_bytes()
        try:
            text = blob.decode(source_encoding)
        except UnicodeDecodeError as exc:
            raise A2LError("Only UTF-8 A2L supported by default; explicitly choose Latin-1 for legacy files") from exc
        if "\x00" in text:
            raise A2LError("NUL bytes are not valid in an A2L source document")
        roots = parse_a2l(text)
        modules = [m for project in roots if project.kind == "PROJECT"
                   for m in project.direct("MODULE")]
        if module is not None:
            modules = [m for m in modules if m.words and m.words[0] == module]
        if len(modules) != 1:
            raise A2LError(
                f"Select exactly one MODULE using --module (matched {len(modules)})"
            )
        return cls(path, hashlib.sha256(blob).hexdigest(), modules[0])

    def _by_name(self, kind: str, name: str) -> Block:
        return _unique(self.module.direct(kind), name, kind)

    def characteristics(self) -> list[dict]:
        out = []
        for node in self.module.direct("CHARACTERISTIC"):
            if len(node.words) < 9:
                out.append({"name": node.words[0] if node.words else "",
                            "supported": False, "reason": "Incomplete characteristic"})
                continue
            name, _, kind, address, layout, _, conversion = node.words[:7]
            supported = kind == "VALUE"
            out.append({"name": name, "kind": kind, "address": address,
                        "layout": layout, "conversion": conversion,
                        "scalar_candidate": supported})
        return out

    def _byte_order(self) -> str:
        commons = self.module.direct("MOD_COMMON")
        if len(commons) != 1:
            raise A2LError("Exactly one MOD_COMMON with explicit BYTE_ORDER required")
        words = commons[0].words
        idx = _lookup(words, "BYTE_ORDER")
        if idx + 1 >= len(words) or words[idx + 1] not in ORDERS:
            raise A2LError("Unsupported or missing BYTE_ORDER")
        return ORDERS[words[idx + 1]]

    def _scalar_layout(self, layout_name: str) -> tuple[str, int]:
        record = self._by_name("RECORD_LAYOUT", layout_name)
        words = record.words
        # The record must contain exactly one sole, contiguous field.
        # A second field (even IDENTIFICATION or ALIGNMENT) changes byte layout.
        if len(words) != 6 or words[1] != "FNC_VALUES":
            raise A2LError("Scalar requires sole contiguous FNC_VALUES record layout")
        position = _number(words[2])
        if position not in (0, 1):
            raise A2LError("Unsupported FNC_VALUES position")
        dtype = words[3]
        if words[4] not in ("ROW_DIR", "COLUMN_DIR") or words[5] != "DIRECT":
            raise A2LError("Unsupported FNC_VALUES orientation or addressing mode")
        if dtype not in READ_STORAGE:
            raise A2LError(f"Unsupported scalar data storage: {dtype}")
        return READ_STORAGE[dtype]

    def _physical(self, method_name: str, raw: int) -> float:
        if method_name in ("NO_COMPU_METHOD", "IDENTICAL"):
            return float(raw)
        method = self._by_name("COMPU_METHOD", method_name)
        if len(method.words) < 3:
            raise A2LError("Incomplete COMPU_METHOD")
        category = method.words[2]
        if category == "IDENTICAL":
            return float(raw)
        if category == "LINEAR":
            idx = _lookup(method.words, "COEFFS_LINEAR")
            if idx + 2 >= len(method.words):
                raise A2LError("Incomplete COEFFS_LINEAR")
            a, b = _float(method.words[idx + 1]), _float(method.words[idx + 2])
            return a * raw + b
        if category == "FORM":
            if method.words.count("FORMULA") != 1 or method.direct("FORMULA"):
                raise A2LError("Exactly one inline FORMULA is required")
            idx = _lookup(method.words, "FORMULA")
            if idx + 1 >= len(method.words):
                raise A2LError("Incomplete FORMULA")
            gain, offset = _affine_formula(method.words[idx+1])
            value = gain * raw + offset
            if not math.isfinite(value):
                raise A2LError("Non-finite FORMULA result")
            return value
        if category == "RAT_FUNC":
            idx = _lookup(method.words, "COEFFS")
            if method.words.count("COEFFS") != 1 or idx + 6 >= len(method.words):
                raise A2LError("Incomplete or ambiguous RAT_FUNC coefficients")
            a, b, c, d, e, f = (_float(x) for x in method.words[idx + 1:idx + 7])
            # The declared direction is physical -> raw. Invert only the
            # single-valued linear/fractional-linear subset for reading.
            if a != 0 or d != 0:
                raise A2LError("Nonlinear RAT_FUNC is unsupported")
            determinant = b*f-c*e
            if not math.isfinite(determinant) or determinant == 0:
                raise A2LError("Noninvertible RAT_FUNC coefficients")
            denominator = b-e*raw
            if not math.isfinite(denominator) or denominator == 0:
                raise A2LError("RAT_FUNC inverse pole")
            value = (f*raw-c)/denominator
            source_denominator = e*value+f
            if not math.isfinite(value) or not math.isfinite(source_denominator) or source_denominator == 0:
                raise A2LError("Undefined or non-finite RAT_FUNC result")
            return value
        raise A2LError(f"Conversion {category} is not supported")

    def _item_byte_order(self, node: Block) -> str:
        words = node.words
        if "BYTE_ORDER" not in words:
            return self._byte_order()
        idx = _lookup(words, "BYTE_ORDER")
        if idx + 1 >= len(words) or words[idx + 1] not in ORDERS:
            raise A2LError("Invalid per-item BYTE_ORDER override")
        return ORDERS[words[idx + 1]]

    @staticmethod
    def _guard_simple_address(node: Block) -> None:
        if "ECU_ADDRESS_EXTENSION" in node.words or "REF_MEMORY_SEGMENT" in node.words:
            raise A2LError("Memory segment/extension addressing requires a qualified mapping")

    def scalar(self, name: str) -> dict:
        node = self._by_name("CHARACTERISTIC", name)
        words = node.words
        if len(words) < 9:
            raise A2LError("Incomplete CHARACTERISTIC")
        if words[2] != "VALUE":
            raise A2LError(f"Only VALUE scalars supported, not {words[2]}")
        self._guard_simple_address(node)
        if "BIT_MASK" in words:
            raise A2LError("BIT_MASK requires mask-aware reads/writes; refusing scalar")
        fmt, size = self._scalar_layout(words[4])
        return {"name": name, "address": _number(words[3]),
                "fmt": self._item_byte_order(node) + fmt, "size": size,
                "conversion": words[6],
                "lower": _float(words[7]), "upper": _float(words[8])}

    def read_scalar(self, name: str, firmware: bytes, base_address: int) -> dict:
        layout = self.scalar(name)
        offset = layout["address"] - base_address
        if offset < 0 or offset + layout["size"] > len(firmware):
            raise A2LError("A2L address is outside BIN memory window")
        raw = struct.unpack_from(layout["fmt"], firmware, offset)[0]
        physical = self._physical(layout["conversion"], raw)
        if not (layout["lower"] <= physical <= layout["upper"]):
            raise A2LError("Decoded physical value violates A2L lower/upper bounds")
        return {"name": name, "a2l_address": layout["address"],
                "bin_offset": offset, "raw": raw, "physical": physical,
                "storage_format": layout["fmt"], "size": layout["size"]}

    def read_table(self, name: str, firmware: bytes, base_address: int) -> dict:
        # Deferred import keeps the narrow scalar and table adapters independent.
        from .tables import read_table
        return read_table(self, name, firmware, base_address)

    def edit_physical(
        self, name: str, firmware: bytes, base_address: int,
        requested_physical: str, max_quantization_error: str = "0"
    ) -> tuple[bytes, dict]:
        from .engineering import edit_physical
        return edit_physical(
            self, name, firmware, base_address,
            requested_physical, max_quantization_error
        )

    def edit_raw(
        self, name: str, firmware: bytes, base_address: int, new_raw: int
    ) -> tuple[bytes, dict]:
        node = self._by_name("CHARACTERISTIC", name)
        if "READ_ONLY" in node.words:
            raise A2LError("A2L declares this characteristic READ_ONLY")
        if "CALIBRATION_ACCESS" in node.words:
            idx = _lookup(node.words, "CALIBRATION_ACCESS")
            if idx + 1 >= len(node.words) or node.words[idx + 1] not in (
                "CALIBRATION", "OFFLINE_CALIBRATION"
            ):
                raise A2LError("A2L CALIBRATION_ACCESS does not permit this write")
        layout = self.scalar(name)
        if layout["fmt"][-1] not in "BbHhIi":
            raise A2LError("Raw writes to IEEE floating-point scalar storage are unsupported")
        # Newly qualified FORM and fractional-linear RAT_FUNC conversions
        # are read-only. Retain the original write-conversion admission.
        conversion = layout["conversion"]
        if conversion not in ("NO_COMPU_METHOD", "IDENTICAL"):
            method = self._by_name("COMPU_METHOD", conversion)
            if len(method.words) < 3:
                raise A2LError("Incomplete COMPU_METHOD")
            if method.words[2] == "FORM":
                raise A2LError("FORM conversion is read-only")
            if method.words[2] == "RAT_FUNC":
                idx = _lookup(method.words, "COEFFS")
                if idx+6 >= len(method.words):
                    raise A2LError("Incomplete RAT_FUNC coefficients")
                if _float(method.words[idx+5]) != 0:
                    raise A2LError("Fractional-linear RAT_FUNC conversion is read-only")
        previous = self.read_scalar(name, firmware, base_address)
        physical = self._physical(layout["conversion"], new_raw)
        if not (layout["lower"] <= physical <= layout["upper"]):
            raise A2LError("Requested raw value violates A2L physical bounds")
        try:
            packed = struct.pack(layout["fmt"], new_raw)
        except (struct.error, OverflowError) as exc:
            raise A2LError("Requested integer cannot fit declared storage") from exc
        offset = previous["bin_offset"]
        result = bytearray(firmware)
        before = bytes(result[offset:offset + layout["size"]])
        result[offset:offset + layout["size"]] = packed
        return bytes(result), {
            "name": name, "bin_offset": offset, "old_raw": previous["raw"],
            "new_raw": new_raw, "old_physical": previous["physical"],
            "new_physical": physical, "before_hex": before.hex(),
            "after_hex": packed.hex(),
        }


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump_json(result: dict) -> str:
    return json.dumps(result, sort_keys=True, indent=2, allow_nan=False)
