"""Machine-operated A2L CLI, with explicit identity and output boundaries."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .core import A2LDefinition, A2LError, dump_json, sha256


def _int(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected decimal integer or 0x-prefixed hex") from exc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kingai-a2l", description="Conservative A2L/BIN scalar inspector and editor"
    )
    cmds = p.add_subparsers(dest="command", required=True)
    for command in ("inspect", "read", "export-json", "edit-raw"):
        sp = cmds.add_parser(command)
        sp.add_argument("--a2l", required=True)
        sp.add_argument("--module", help="A2L MODULE name, required if ambiguous")
        if command != "inspect":
            sp.add_argument("--bin", required=True, dest="bin_path")
            sp.add_argument("--base-address", required=True, type=_int,
                            help="Explicit ECU address represented by BIN offset zero")
        if command in ("read", "edit-raw"):
            sp.add_argument("--name", required=True, help="Exact CHARACTERISTIC name")
        if command == "edit-raw":
            sp.add_argument("--raw", type=_int, required=True,
                            help="Signed/unsigned raw storage integer, not engineering value")
            sp.add_argument("--expected-sha256", required=True,
                            help="SHA-256 of original BIN, mandatory")
            sp.add_argument("--expected-a2l-sha256", required=True,
                            help="SHA-256 of A2L source, mandatory")
            sp.add_argument("--output", required=True,
                            help="Must be a new path; never replaces source")
        if command == "export-json":
            sp.add_argument("--output", help="New JSON report path, otherwise stdout")
    return p


def execute(args: argparse.Namespace) -> dict:
    definition = A2LDefinition.load(args.a2l, args.module)
    header = {
        "schema": "kingai.a2l-bin.cli-result.v0",
        "command": args.command,
        "a2l_sha256": definition.source_sha256,
        "module": definition.module.words[0],
        "status": "prototype",
        "flash_ready": False,
    }
    if args.command == "inspect":
        return {**header, "characteristics": definition.characteristics()}
    firmware = Path(args.bin_path).read_bytes()
    header.update({"bin_sha256": sha256(firmware), "bin_size": len(firmware),
                   "bin_base_address": args.base_address})
    if args.command == "read":
        return {**header, "item": definition.read_scalar(
            args.name, firmware, args.base_address
        )}
    if args.command == "export-json":
        records = []
        incomplete = False
        for item in definition.characteristics():
            try:
                row = definition.read_scalar(item["name"], firmware, args.base_address)
                records.append({"status": "read", **row})
            except A2LError as exc:
                incomplete = True
                records.append({"name": item["name"], "status": "unsupported",
                                "reason": str(exc)})
        result = {**header, "complete": not incomplete, "items": records}
        if args.output:
            output = Path(args.output)
            if output.exists() or output.resolve() == Path(args.bin_path).resolve():
                raise A2LError("Export report path must be new")
            with output.open("x", encoding="utf-8") as f:
                f.write(dump_json(result) + "\n")
            return {**header, "complete": not incomplete, "report_path": str(output),
                    "item_count": len(records)}
        return result
    if args.command == "edit-raw":
        if args.expected_sha256.lower() != sha256(firmware):
            raise A2LError("Source BIN SHA-256 mismatch: edit refused")
        if args.expected_a2l_sha256.lower() != definition.source_sha256:
            raise A2LError("Source A2L SHA-256 mismatch: edit refused")
        output = Path(args.output)
        audit = Path(str(output) + ".audit.json")
        if (output.exists() or audit.exists()
                or output.resolve() == Path(args.bin_path).resolve()):
            raise A2LError("Output BIN/audit path already exists or equals source")
        modified, change = definition.edit_raw(
            args.name, firmware, args.base_address, args.raw
        )
        # Never overwrite an existing target. Restore on failed audit write.
        receipt = {
            **header, "output_sha256": sha256(modified),
            "changed_bytes_count": sum(a != b for a, b in zip(firmware, modified)),
            "change": change, "checksum_qualified": False,
            "hardware_validated": False, "flash_ready": False,
            "output": str(output),
        }
        with output.open("xb") as f:
            f.write(modified)
        try:
            with audit.open("x", encoding="utf-8") as f:
                f.write(dump_json(receipt) + "\n")
        except Exception:
            output.unlink(missing_ok=True)
            raise
        return receipt
    raise A2LError("Unknown command")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = execute(args)
        print(dump_json({"ok": True, **result}))
        return 0
    except (A2LError, OSError) as exc:
        print(dump_json({"ok": False, "error": str(exc),
                         "error_type": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
