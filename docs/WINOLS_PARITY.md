# WinOLS functional parity matrix

**Status: ambition and acceptance gates, not a claim of current parity.**

EVC WinOLS 5 product page: https://www.evc.de/en/product/ols/software/Default.asp
ASAM MCD-2 MC: https://www.asam.net/standards/detail/mcd-2-mc/

| Capability | KingAI A2L status | Qualification before claiming parity |
| --- | --- | --- |
| A2L project and symbol import | Limited proof of concept | Real A2L grammar/version fixtures, includes, multiple MODULEs and malformed input tests |
| Scalars and conversion methods | VALUE integer; IDENTICAL/LINEAR only | RAT_FUNC, COMPU_TAB, signed and floating values, quantization, byte-order cases |
| 1D, 2D, 3D and higher maps | Not implemented | RECORD_LAYOUT indexing, offsets, strides, COM_AXIS/STD_AXIS/FIX_AXIS, up to ASAM 5D |
| ECU memory to BIN address mapping | Explicit single base address only | Segment-aware address transforms and proven software identity |
| Binary-safe editing | Limited raw VALUE edit | Engineering-value edit planning, reversible conversions, output re-read, diff receipt |
| A2L and BIN export | Partial JSON export; BIN scalar copy | Bounded all-map import/export, format conversion with explicit loss reporting |
| Automated map finding | Not implemented | Real code/data identification and external trace evidence |
| Project compare and change transfer | Not implemented | Exact identity, map-equivalence proof, offset matching, conflict tests |
| WinOLS project and map-pack formats | Not implemented | Rights, format documentation and separately supported adapters |
| Checksums and signatures | Not implemented | Per-ECU golden fixtures, reproducible checksum tests, independent validation |
| ADX/XDL log corrections | Not implemented | Correct ADX channel resolution, native XDL-vs-CSV fixture parity, time alignment, provenance |
| Human inspection and AI automation | JSON CLI prototype | Machine schemas, deterministic exit codes, dry runs, auditable review records |

WinOLS includes additional hardware, GUI, scripting, plugin, version control and commercial project management features. They are not required for AI-native headless calibration parity, but must not be represented as already implemented.

**Parity acceptance principle:** A parsing success or plausible table is not evidence that the ECU executes it. A supported map must have a matching input image, consistent memory layout, validated numerical conversion and independently checked editing/export behavior.
