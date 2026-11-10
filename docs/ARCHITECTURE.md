# Cross-repository development and upstream/downstream policy

Goal: separate **AI-first CLIs** over a shared, tested calibration core and export system.

- XDF frontend: https://github.com/KingAiCodeForge/tunerpro-xdf-bin-cli-map-editor
- A2L frontend: this repository
- XDF exporter: https://github.com/KingAiCodeForge/TunerPro-XDF-BIN-Universal-Exporter
- Proposed neutral calibration model and binary operations: extract into a versioned dependency after comparing current XDF code and proving interface compatibility.
- Proposed log ingestion: standalone ADX-aware CSV and XDL decoding/validation components, with explicit source hashes and normalized session schema.

## Current state

This repository currently contains its own small, conservative A2L scalar adapter. It is not a fork of the XDF editor or its exporter. Its code is provisional until a shared core is extracted. Do not claim existing shared engine integration.

The existing XDF editor remains the only published XDF-oriented CLI. Its published README describes developmental 1.3.0a1 and narrower write limitations. Uncommitted local development may differ from published main, so integration requires pinned public commits and tests.

## Proposed contracts

- kingai.calibration.definition.v1: identity, symbols, axis/storage layouts, conversion capabilities, source evidence.
- kingai.calibration.edit-plan.v1: source BIN and definition SHA-256, exact edit targets, expected values, preservation rules.
- kingai.calibration.audit.v1: preflight outcome, old/new raw and physical values, changed byte regions, errors, validation limits.
- kingai.log-session.v1: source BIN/XDF/A2L/ADX/log SHA-256, channel provenance, ECU platform context, clock and unit metadata.

These are design targets, not active public compatibility guarantees.

## Release dependencies

1. Build and validate common independent data model with synthetic tests.
2. Adapt XDF editor and A2L editor independently to common versioned APIs.
3. Integrate Universal Exporter only through a tested stable adapter and exact pin.
4. Add ADX/CSV read-only normalization, followed by independently qualified XDL decoder.
5. Agent proposes calibration corrections; deterministic executor previews and applies approved changes to fresh copies.
6. Add golden fixture comparisons to native TunerPro/WinOLS where legitimately licensed and available.
7. Introduce checksum and hardware adapters only under separate scope and ECU-specific testing.

Prefer upstream fixes in the owner of a shared interface, then downstream dependency bumps by pinned commit or version. Do not push incomplete XDF worktree changes to this repository.
