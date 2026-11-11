# KingAI A2L/BIN CLI Map Editor

AI-native, headless ECU calibration definition tooling for software agents. Built by KingAI Pty Ltd.

**Development status: 0.2.0a0 development prototype.** This is NOT WinOLS parity, a general A2L parser, a complete calibration editor, a checksum utility, an ECU flasher, or a validated vehicle calibration solution.

## Why a separate repository?

- **KingAI A2L CLI:** read ASAM A2L definitions against matching ECU binary files.
- **KingAI XDF CLI:** [existing TunerPro XDF/BIN editor](https://github.com/KingAiCodeForge/tunerpro-xdf-bin-cli-map-editor).
- **KingAI Universal Exporter:** [existing versioned export project](https://github.com/KingAiCodeForge/TunerPro-XDF-BIN-Universal-Exporter).

They should exchange versioned schemas and share tested upstream components, not copy implementations without provenance. The common editing/export API is **planned**, not already linked here. Avoid dependence on unpublished changes in the existing XDF editor.

## Working prototype features

- Read A2L PROJECT, MODULE, CHARACTERISTIC, RECORD_LAYOUT, MOD_COMMON and selected COMPU_METHOD data using a bounded parser.
- Enumerate named characteristics for agents with JSON output.
- Read VALUE scalars with explicit ECU memory base, byte order, integer storage, IDENTICAL and LINEAR scaling, and analytically invertible affine RAT_FUNC conversion.
- Read 1D CURVE and 2D MAP data with sole contiguous FNC_VALUES layout plus FIX_AXIS or directly stored COM_AXIS axes. Export flat values and axis metadata; cell-coordinate mapping and table writing are not qualified.
- Write supported scalar engineering-unit targets with exact-decimal inversion and a mandatory quantization-error gate if the target is not exactly representable.
- Reject bit-masked scalars, read-only writes, address-space extensions and unsupported record addressing instead of silently modifying unrelated bits.
- Export JSON that marks unsupported items explicitly instead of silently omitting them.
- Write a **new BIN copy** for a strictly scoped raw integer scalar change, with exact SHA-256 checks for original BIN and A2L plus a JSON audit receipt.
- Refuse unsupported map structures, conversion methods, missing byte order, unresolved A2L includes, invalid offsets, source-hash mismatches and output overwrites.

No real ECU family or A2L file is qualified. All current tests use synthetic definitions.

## Install

Python 3.10 or newer:

    python -m pip install .
    kingai-a2l --help
    python -m unittest discover -s tests -v

## Inspect and edit synthetic or matching data

    kingai-a2l inspect --a2l example.a2l
    kingai-a2l read --a2l example.a2l --bin original.bin --base-address 0x80000000 --name SYMBOL
    kingai-a2l read-table --a2l example.a2l --bin original.bin --base-address 0x80000000 --name TABLE_SYMBOL
    kingai-a2l export-json --a2l example.a2l --bin original.bin --base-address 0x80000000
    kingai-a2l edit-raw --a2l example.a2l --bin original.bin --base-address 0x80000000 --name SYMBOL --raw 120 --expected-sha256 ORIGINAL_BIN_SHA256 --expected-a2l-sha256 ORIGINAL_A2L_SHA256 --output review-copy.bin
    kingai-a2l edit-physical --a2l example.a2l --bin original.bin --base-address 0x80000000 --name SYMBOL --physical 120.5 --max-quantization-error 0.1 --expected-sha256 ORIGINAL_BIN_SHA256 --expected-a2l-sha256 ORIGINAL_A2L_SHA256 --output quantized-review.bin

The base address is illustrative, NOT an address to use on an actual ECU. The raw parameter accepts a storage integer, not a physical target. Engineering-unit conversion is limited to affine methods and uses nearest-integer half-even quantization. There is no 1D/2D/3D map writing. Raw or engineering edits are not automatically safe for a vehicle.

The export-json command currently exports supported scalars only; unsupported table items are labelled rather than represented as complete. Use read-table for the supported read-only 1D/2D subset.

## AI agent operating contract

1. Fingerprint the input BIN and definition, identify ECU software and intended memory address window from independently verified evidence.
2. Inspect supported and unsupported items; never infer map purpose from an attractive name.
3. Read before writing. Show units, raw values, method and exact target bytes.
4. Produce a human-reviewable change proposal. Require authorization for ECU-affecting writes.
5. Edit a fresh copy only after matching source hashes; retain the baseline unchanged.
6. Re-read the output, check byte diffs and preserve receipts.
7. Treat checksum verification, calibration validation and flashing as separately qualified processes.

AI handles analysis and proposals. The CLI executes deterministic, bounded operations, and reports failure when definition support or address evidence is insufficient.

## Roadmap

See [WinOLS parity and qualification matrix](docs/WINOLS_PARITY.md) and [cross-repository architecture](docs/ARCHITECTURE.md).

**Not implemented:** A2L includes and full grammar, map writes, general nonlinear RAT_FUNC and conversion-table support, embedded STD_AXIS layouts, full multidimensional maps beyond 2D, DAMOS/KP/OLS proprietary project imports, disassembly/map detection, ADX/XDL import, log-to-cell correction, safe checksum modules, hardware IO, reverse-engineering semantic verification, native WinOLS equivalence tests.

Read [A2L fixture corpus triage](docs/RE_ANALYSIS_20261111.md) for the public test corpus and next unsupported structures.

## Safety and data

Never commit customer BINs, proprietary A2Ls, customer logs, identifiers, credentials or unlicensed map packs. Publishing this library does not grant rights to any ECU firmware or WinOLS proprietary project formats. All releases must include regression fixtures and an explicit support matrix.

MIT license. Copyright 2026 KingAI Pty Ltd.
