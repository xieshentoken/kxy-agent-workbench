# kxy — implementation scope

The user explicitly approved an independent kxy MVP under this directory. The parent WhatFa business model, Source/Evidence/Claim database, and external-engine-only intake restrictions do not apply to kxy. Preserve all files outside kxy. Keep implementation direct; no speculative abstraction layers.

Read docs/IMPLEMENTATION.md before implementation. The user approved implementation and the supplied visual reference, so proceed without reopening planning or design approval gates. Use React/XYFlow and Langflow's LFX graph execution core; keep kxy data, configuration and server independent. Do not modify the external Langflow checkout or the user's global CLI configuration.

Only report actual verification. Synthetic CLI fixtures are not real model calls. Keep credentials out of workflow JSON, logs, responses, screenshots and source control. Back up existing scripts before substantial modifications. Use versioned output directories. Never overwrite input originals.

Implementer: GPT-5.6 Luna with max reasoning as requested by the user. Parent task owns architecture, supervision and independent acceptance. Do not spawn additional implementation agents or create additional tasks.

## Current SkillHub and release boundary

The vendored `xieshentoken/skillhub` package is pinned to commit `8ae72075fdafb1d9dda5f3a232fd9fd438d6e485`; `vendor/skillhub/UPSTREAM_PROVENANCE.json` and the blob constants in `backend/agent_config.py` are the source-of-truth checks. KXY invokes the vendored CLI plus diagnostic/dependency bridges in bounded subprocesses. KXY-owned full-snapshot, runtime/cache, path, marker, migration, scan/sync, and tombstone gates remain in the backend; do not replace them with upstream GUI behavior or change the upstream package in place.

When updating this dependency, make a timestamped backup first and update the vendored production files, provenance, blob constants, `THIRD_PARTY_NOTICES.md`, and the relevant README facts together. Do not modify external Agent directories, global CLI configuration, or the upstream checkout.

Release artifacts use a new versioned directory and ZIP and must retain the prebuilt frontend, install/start scripts, manifest, standalone verifier, and readable third-party notices. Exclude `data/`, `.venv/`, `node_modules/`, user materials, run history, login state, API keys, Keychain data, native Agent runtimes, and development-machine absolute paths. The supported release boundary is macOS 15+ Apple Silicon; first installation needs network access for Python dependencies, and Agent CLIs plus any CLI-specific Node runtime must be installed and logged in separately. Never overwrite a historical release.
