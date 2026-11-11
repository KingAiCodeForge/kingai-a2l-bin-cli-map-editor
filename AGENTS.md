# Agent instructions

This repository is AI-first, NOT intended to silently write or flash vehicle ECUs.

- Prefer python -m kingai_a2l inspect before other commands. Use read-table only for the documented contiguous CURVE/MAP subset; report flat values, declared axis order and coordinate-mapping uncertainty.
- Always report commands, input hashes, definition/module and the declared BIN base-address assumption.
- Test on synthetic fixtures before changing parser/storage behavior.
- Fail closed for unknown A2L features, ambiguous names, unsupported memory windows, missing byte order, overlapping or composite layouts.
- Keep original source bytes untouched; all edits require explicit input hashes, a fresh output path and an audit record.
- Never assume a valid A2L/BIN means the described map is actively used in ECU code.
- Never claim WinOLS parity or ADX/XDL processing until golden tests pass.
- Do not publish private firmware, A2Ls, logs, keys, identifiers or proprietary WinOLS assets.
- Upstream neutral fixes to their owning repository and pin the downstream consumer. Do not copy the XDF engine into this repo.
- Run python -m unittest discover -s tests -v and include results in change descriptions.
