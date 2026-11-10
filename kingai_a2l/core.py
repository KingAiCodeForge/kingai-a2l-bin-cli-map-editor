"""Strict, deliberately limited A2L/ASAP2 -> binary scalar operations.

No application-specific memory remapping, checksum repair or ECU access.
Unknown features fail closed rather than being interpreted approximately.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
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
    def load(cls, source_path: str | Path, module: str | None = None) -> "A2LDefinition":
        path = Path(source_path)
        if path.stat().st_size > MAX_A2L_BYTES:
            raise A2LError("A2L is larger than the bounded import limit")
        blob = path.read_bytes()
        try:
            text = blob.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise A2LError("Only UTF-8 A2L supported in this prototype") from exc
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
        idx = _lookup(words, "FNC_VALUES")
        if idx + 2 >= len(words):
            raise A2LError("Incomplete FNC_VALUES record layout")
        position = _number(words[idx + 1])
        dtype = words[idx + 2]
        if position != 1:
            raise A2LError("FNC_VALUES not first in record layout; offset unverified")
        if dtype not in STORAGE:
            raise A2LError(f"Unsupported integer storage: {dtype}")
        if any(w.startswith(("AXIS_PTS_", "NO_AXIS_PTS_", "RESERVED"))
               for w in words):
            raise A2LError("Composite record layout is not supported for scalar edits")
        return STORAGE[dtype]

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
        raise A2LError(f"Conversion {category} is not supported")

    def scalar(self, name: str) -> dict:
        node = self._by_name("CHARACTERISTIC", name)
        words = node.words
        if len(words) < 9:
            raise A2LError("Incomplete CHARACTERISTIC")
        if words[2] != "VALUE":
            raise A2LError(f"Only VALUE scalars supported, not {words[2]}")
        fmt, size = self._scalar_layout(words[4])
        return {"name": name, "address": _number(words[3]),
                "fmt": self._byte_order() + fmt, "size": size,
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

    def edit_raw(
        self, name: str, firmware: bytes, base_address: int, new_raw: int
    ) -> tuple[bytes, dict]:
        layout = self.scalar(name)
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
