# A2L corpus reverse-engineering triage, 11 November 2026

Status: read-only static parser inspection of public reference fixtures plus synthetic regression tests. **No production ECU firmware, native WinOLS project or customer A2L/BIN pair was validated.**

## Source provenance

Local source: A:\repos\a2ltool\fixtures\a2l, from the permissively licensed a2ltool project (DanielT/a2ltool). The source files were inspected in place. No third-party A2L files or customer firmware were copied into this public repository.

Official technical reference: https://www.asam.net/standards/detail/mcd-2-mc/wiki/

The diagnostic script imported each A2L into the experimental KingAI AST and counted CHARACTERISTIC, AXIS_DESCR and COMPU_METHOD structures. This is **syntax observation, not correct-value proof**.

## Observed records

| Fixture | CHARACTERISTICs | Observed kinds | Axis descriptors | Conversion method definitions |
| --- | ---: | --- | --- | --- |
| update_test1.a2l | 6 | CURVE 2, MAP 2, VAL_BLK 1, VALUE 1 | COM_AXIS 3, STD_AXIS 3 | RAT_FUNC 3, TAB_VERB 1 |
| update_test2.a2l | 7 | CURVE 2, MAP 2, VAL_BLK 1, VALUE 2 | COM_AXIS 3, STD_AXIS 3 | RAT_FUNC 3 |
| software_b.a2l | 0 | none | none | TAB_VERB 25, LINEAR 21 |
| software_a.a2l | 3452 | VALUE 3156, ASCII 26, VAL_BLK 101, CURVE 158, MAP 11 | COM_AXIS 161, STD_AXIS 12, FIX_AXIS 7 | TAB_VERB 163, RAT_FUNC 174, LINEAR 58, IDENTICAL 42, FORM 1 |

software_a.a2l is an obfuscated test application with no executable code/data. It is not a valid calibration reference for any vehicle merely because the parser can inspect its declaration tree.

xcp_test.a2l contains multiple MODULE candidates and requires explicit module selection. The default ambiguous-MODULE refusal is expected; it was not included in the above counts.

## Findings and next RE directions

1. **External COM_AXIS** dominates the observed table-axis declarations. The prototype now has a deliberately limited read-only path for one contiguous AXIS_PTS_X record, fixed count, explicit memory base and matching conversion. The larger subset with dynamic axis-count fields is not handled.
2. **STD_AXIS and dynamic RECORD_LAYOUT** remain a major gap. The next investigation should derive correct byte offsets through NO_AXIS_PTS_*, AXIS_PTS_*, FNC_VALUES position, alignment, INDEX_DECR, orientation, storage and total layout size. Read-only golden fixtures must precede editing.
3. **RAT_FUNC** requires correct inverse direction. The prototype only supports the provable affine subset where a=d=e=0, b and f nonzero. Nonlinear rational conversion must not be guessed and will require algebraic root selection, ambiguity checks and native-tool comparison.
4. **Byte-order and memory mapping** require segment-specific qualification. Some public fixtures omit explicit MOD_COMMON; the prototype fails closed unless the item specifies a supported byte-order override. A memory-address window is operator supplied and not inferred.
5. **BIT_MASK** can represent fields sharing a storage word. Prior code read and replaced the complete word; v0.2.0a0 now refuses bit-masked scalars until explicit masking and neighbour-bit preservation are separately tested.
6. **AI-first engineering edits** should invert forward conversion with deterministic numeric handling. The new edit-physical path performs Decimal-based inverse calculation and nearest-even integer quantization. A nonzero error requires a stated maximum tolerance, then original/edited bytes and source hashes are audited.

The parser's ability to traverse the fixtures is not a statement that it has fully implemented the ASAM MCD-2 MC grammar. In particular, include processing, A2ML and embedded vendor extensions remain incomplete or opaque.

## Relationship to other KingAI lanes

- XDF CLI: pinned external Exporter and local XDF editor remains separate, with uncommitted work in the local editor checkout. The A2L repo did not modify it.
- Universal Exporter: intended shared snapshot/diff layer, but there is no tested dependency adapter in the A2L package yet.
- ADX/XDL: existing public XDF documentation describes a proposal, not a working decoder. Develop read-only ADX-aware CSV before binary XDL, then bind each log to exact BIN/definition hashes.
- ECU reverse engineering: proving a calibration consumer or active map selector still requires independent firmware analysis, cross references, dynamic evidence or hardware measurements. Declared A2L symbols alone are insufficient.

## Validation boundaries

Synthetic suite: **30 tests passed locally on both Python 3.11 and Python 3.13** after integrating read-only CURVE/MAP, scalar guards and engineering edit features.

GitHub Actions workflow exists for Python 3.10 and 3.13, but hosted jobs were blocked by the account-level GitHub Actions billing lock. Neither hosted Python version was validated in CI at this stage.

No ECU communication, checksum repair or flashing support was created.

## Follow-up: structure cross-reference and qualified read-only extensions

Checked the experimental reader against publicly available ASAM/A2L reference material, MATLAB A2L conversion documentation, the Rust a2lfile specification and the local permissively licensed a2ltool corpus.

1. **Record positions are ordinals, not byte offsets.** Within a composite RECORD_LAYOUT, each preceding field's actual storage length determines the next field's byte offset. The new bounded inline STD_AXIS interpreter handles direct, consecutive positions and optionally reads NO_AXIS_PTS_X/Y from the supplied BIN before calculating axis and FNC_VALUES lengths. It refuses static-address allocation, pointers, INDEX_DECR, unqualified padding and unsupported fields. Only read operations are allowed. This is a source-layout interpretation, not native ECU parity.
2. **FNC_VALUES position 0 is a real pattern, not malformed.** In software_a.a2l, 539 VALUE symbols reference sole FNC_VALUES at position 0 and 2,539 reference sole FNC_VALUES at position 1. The previous parser rejected position 0 even for a sole contiguous field; the strict bounded reader now supports both.
3. **IEEE data types matter materially.** Of 3,156 VALUE declarations in that obfuscated fixture, 3,078 use a sole contiguous FNC_VALUES record and 1,854 of those reference FLOAT32_IEEE storage. The new reader handles FLOAT32_IEEE/FLOAT64_IEEE raw reading and rejects float writes. These counts prove syntax coverage only: 844 of the 3,078 simple VALUE symbols reference a RAT_FUNC conversion and 237 reference TAB_VERB, neither of which automatically qualifies for physical-value decoding.
4. **Fixed axes require multiple representations.** Added read-only FLOAT-valued FIX_AXIS_PAR_LIST, FIX_AXIS_PAR_DIST and bounded FIX_AXIS_PAR (offset plus indexed powers of two). Declared axis point counts are checked against computed lists. This corrects the previous integer-only fixed-axis assumption.
5. **Composite scalar layouts are not simple scalar storage.** A layout may include IDENTIFICATION, RESERVED, axis count, alignment or other records. The previous scalar reader could silently treat such a declaration as an ordinary first-field scalar. It now requires a sole FNC_VALUES record; unsupported composite scalar reads and writes fail closed.
6. **MONOTONY is defined over internal axis values.** Physical/display ordering alone cannot validate its constraint, especially with conversions and INDEX_DECR. The reader does not claim monotonicity validation or qualified table-coordinate mapping.
7. **Byte-order and segmentation remain explicit risks.** A conflicting AXIS_DESCR byte-order override and AXIS_PTS byte-order is now rejected. Memory-segment mapping and a source BIN's software identity must still be independently proven.

Reference material:
- ASAM MCD-2 MC: https://www.asam.net/standards/detail/mcd-2-mc/
- ASAM record-layout and static-offset release explanation: https://www.asam.net/index.php?eID=dumpFile&f=734&t=f&token=aff3202720d0a044bd82491c9354a93b7cf43d61
- Rust a2lfile specification: https://docs.rs/a2lfile/latest/a2lfile/struct.RecordLayout.html
- MATLAB conversion documentation: https://github.com/matlab/simulink-agentic-toolkit/blob/main/skills-catalog/code-generation/simulink-customize-a2l/references/compu-method-guidance.md

The repo now has a **summary** CLI operation producing a compact, versioned structural inventory. This is preferable to flooding the agent's context with thousands of CHARACTERISTIC records.

Cross-repository check: The existing local XDF editor source still contains multiple unpublished/dirty changes and a local pyproject version distinct from its published README. The local XDF checkout pins a specific Universal Exporter commit; it must not be silently overwritten, imported or synchronized by copying modules into the A2L repo. The XDF editor and Universal Exporter were inspected read-only.

Remaining research gates: full ASAM grammar/includes, real A2L/BIN exact-pair validation, vendor extensions and calibration-page addressing, non-affine RAT_FUNC and verbal conversions, static address layouts and compiler padding, INDEX_DECR and monotonicity, 3D+ maps, native WinOLS/TunerPro parity, deterministic format-neutral export adapter and a qualified ADX/XDL log decoder. No flash/checksum tool was introduced.
