# WinOLS functional parity matrix

**Status: ambition and acceptance gates, not a claim of current parity.**

EVC WinOLS 5 product page: https://www.evc.de/en/product/ols/software/Default.asp
ASAM MCD-2 MC: https://www.asam.net/standards/detail/mcd-2-mc/

| Capability | KingAI A2L status | Qualification before claiming parity |
| --- | --- | --- |
| A2L project and symbol import | Limited proof of concept | Real A2L grammar/version fixtures, includes, multiple MODULEs and malformed input tests |
| Scalars and conversion methods | Integer/IEEE float32/float64 scalar reads; guarded integer VALUE writes for existing conversions; read-only affine FORMULA and invertible fractional-linear RAT_FUNC (synthetic numerical regression) | Float writes, quadratic/nonunique RAT_FUNC, lookup-table and non-affine formula conversion, bitfields, native fixture comparisons |
| 1D, 2D, 3D and higher maps | CURVE/MAP read-only: contiguous FIX_AXIS/COM_AXIS; bounded inline STD_AXIS dynamic counts, explicitly aligned fields, RESERVED datasizes and direct INDEX_DECR axes; flat FNC values only | Undeclared padding, pointers, static-offset variants, row/column cell-coordinate qualification, native licensed reader parity, matching real A2L/BIN proof, map writes, and 3D+ up to ASAM 5D |
| ECU memory to BIN address mapping | Explicit single base address only | Segment-aware address transforms and proven software identity |
| Binary-safe editing | Guarded raw and engineering-value VALUE edits with SHA-256 identity, quantization bound, new BIN copy and audit | Multi-cell edit planning, richer conversions, overlap tests, checksum/hardware qualification |
| A2L and BIN export | Compatible scalar-only JSON default; opt-in bounded read-only CURVE/MAP export with axes, flat values, dynamic offsets, explicit unsupported-item reporting and aggregate value budget; BIN scalar copy | Native reader parity, further layout coverage, coordinate mapping and cross-format conversion with explicit loss reporting |
| Automated map finding | Not implemented | Real code/data identification and external trace evidence |
| Project compare and change transfer | Not implemented | Exact identity, map-equivalence proof, offset matching, conflict tests |
| WinOLS project and map-pack formats | Not implemented | Rights, format documentation and separately supported adapters |
| Checksums and signatures | Not implemented | Per-ECU golden fixtures, reproducible checksum tests, independent validation |
| ADX/XDL log corrections | Not implemented | Correct ADX channel resolution, native XDL-vs-CSV fixture parity, time alignment, provenance |
| Human inspection and AI automation | JSON CLI with compact source-only structural inventory and bounded read/edit commands | Stable versioned API contracts, consistent format-neutral edit plans, golden result comparisons and broader audit fixtures |

WinOLS includes additional hardware, GUI, scripting, plugin, version control and commercial project management features. They are not required for AI-native headless calibration parity, but must not be represented as already implemented.

**Parity acceptance principle:** A parsing success or plausible table is not evidence that the ECU executes it. A supported map must have a matching input image, consistent memory layout, validated numerical conversion and independently checked editing/export behavior.

Release-candidate qualification, 26 November 2026: 86 self-contained Python unittest cases passed on Python 3.13, including synthetic golden RECORD_LAYOUT cases, bounded table exports, affine formulas and fractional-linear inverses. No local OEM source files are needed for this suite. Native tool comparisons, production A2L/BIN pair validation, coordinate-mapping parity and map writes remain unqualified.
