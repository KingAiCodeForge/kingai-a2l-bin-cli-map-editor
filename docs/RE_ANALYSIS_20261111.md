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
