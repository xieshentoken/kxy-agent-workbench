# V9 bounded multi-agent loop acceptance

Accepted and published locally on 2026-09-09. Implementation: existing GPT-5.6 Luna max session. Parent planned, reviewed execution boundaries, independently ran acceptance and published.

## Delivered
- Enabled loop blackbox; outer and per-round inner workflows remain actual LFX DAGs. Editable executor/reviewer analyzer selection, goal, feedback fields and review JSON mapping; prompt remains solely on the selected analyzer.
- Bounded rounds (default 3, maximum 50) and active CLI time (default 1800 seconds); durable pause, explicit bounded extension or stop. Waiting for a human does not consume active CLI time.
- Round-scoped checkpoints and immutable artifact workspaces; failed current-round calls retry in a new attempt directory while prior-round and current-round successes are reused. V8 ordinary workflow resume remains compatible.
- Visible round context, original files and prior artifacts copied into the receiving analyzer workspace; reviewer receives explicit goal/context alongside the executor output. No hidden loop prompt.
- Round selector, inputs/results/review and change preview; reusable loop presets correctly remap role references. Only passing executor output reaches downstream authorized output. Granted containers inside loops and nested enabled loops are rejected with actionable errors.

## Independent verification
- `.venv/bin/python acceptance/v9_loop_checks.py`: **6/6 PASS**, 3.879 seconds, fresh isolated data. Includes a real local synthetic CLI subprocess reading artifact/context files across two rounds; round-limit pause/continue; second-round reviewer failure and successful-node reuse; malformed review and revoked authorization preventing export; ordinary V8 resume; active budget pause/extension preserving elapsed time.
- `npm run build -- --outDir dist-v9-verified`: TypeScript and production build PASS. Independent output matches Luna's `dist-v9` byte for byte. Vite reports a non-blocking chunk-size advisory; no extra code splitting was added for this bounded change.
- `acceptance/v9_independent_browser.cjs`: one focused UI journey PASS on final backend/build: create/configure loop, save and reinsert preset, pause at round limit, explicitly continue, accept round two, switch rounds and view changes. No page script errors. The preset-reference defect found during parent acceptance was repaired and reverified. Waiting assertions were adjusted for the UI's normal polling interval.
- Evidence: `v9-evidence/browser-result.json`, `loop-paused.png`, `loop-round-two.png`, `publication.json`, `source-hashes.json`.

## Publication and preservation
- Formal URL: http://127.0.0.1:8710/ ; PID 13335 at publication. Started with normal host permissions so macOS Keychain is not confined by the parent tool sandbox. Log: `/private/tmp/kxy-v9-formal-server.log`.
- Health: ok, actual LFX 1.12.0 loaded. Served HTML, JS and CSS bytes match independent production output.
- Original 17 tables' rows and 1911 existing data files verified unchanged after startup; loop_rounds is additive. No active runs existed at publication. Test service on port 8724 closed.
- Backup: `.backups/pre-v9-publish-20260909-023050/` contains consistent SQLite backup and previous front end. Source/data baseline: `.backups/pre-v9-parent-20260909-012625/`.

## Boundaries
These checks use synthetic data/CLI responses, not real paid model inference or a claim about output quality. Interrupted execution was exercised through a deterministic failed reviewer and checkpoint resume; this round did not repeat a full operating-system process-restart campaign. No token/cost accounting is fabricated. Parallel reviewer voting, arbitrary cyclic edges and nested enabled loops are outside this version. Node-settings/human-confirmation redesign remains deferred. Distribution installers were not rebuilt; this acceptance is for the local source and running service.
