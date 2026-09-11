# kxy V3 — SkillHub, appearance and editing

Approved implementation scope: user's request of 2026-09-06. Parent plans and independently accepts; implementation tasks use GPT-5.6 Luna, max. Do not request an additional generic approval. Preserve the running V2 data and all files outside kxy; no changes to native global agent configuration.

## Findings and reuse

- V2 imports frozen Skill snapshots; it does **not** call SkillHub or link MCP. Keep frozen snapshots and the native-login behavior verified in V2.
- Reuse actual upstream `xieshentoken/skillhub` at commit `531ca63d3740fd2ac6f06eee531c1874ada01db2` (MIT). Research copy: `/private/tmp/kxy-v3-research`. Vendor the small upstream Python package, LICENSE and provenance without modifying upstream files. Invoke it in bounded subprocesses with all destination environment variables overridden to kxy-owned paths. No install or write under the user's global agent homes.
- SkillHub has a canonical store plus symlink/copy projection. It is not a translator for agent-specific tools. Upstream identifiers hash only SKILL.md; kxy must additionally validate full snapshot SHA-256 and avoid merging different reference/script content. Guard path/name/category traversal and corrupted index; do not use force-overwrite.
- Upstream MCP generation is version-sensitive (Codex generator emits an array-of-tables, while installed Codex expects a table). Validate generated config against installed CLI conventions, and record any minimal compatibility normalization in kxy. Never claim that configuration generation proves a live server connection.

## Architecture and scope

Keep React/XYFlow, existing FastAPI/LFX runtime, SQLite, direct helper functions. Two implementation tasks own separate trees: Backend owns `backend/**`, `vendor/skillhub/**` and its V3 checks; Frontend owns `frontend/**` and browser checks. Parent owns this plan, independent acceptance, final report and service rollout. No nested tasks.

### SkillHub / MCP

1. Central store lives under `KXY_DATA_ROOT/skillhub`. Cross-agent attachment automatically imports the selected immutable kxy snapshot through actual SkillHub and creates a target-agent projection. Runtime repeats the mapping using the run-frozen snapshot and records source agent, target agent, upstream commit, full snapshot hash and projection in the run manifest. Original Skill directories remain unchanged. Same-agent selected Skills keep working.
2. Mount preview endpoint: `POST /api/skillhub/mount` with `{agent_id, skill_ids}` returns `{skills: [{skill_id, source_agent, target_agent, cross_agent, status, message}], status}`. Errors must be visible and block the dependent run; successful preview is not an execution claim. `GET /api/skillhub/status` reports actual upstream/central-store availability and per-agent MCP support.
3. MCP remains opt-in per analyzer. Read only known configured agent MCP locations. No startup on scan, and no automatic attachment of unrelated servers. Provide `GET /api/agents/{id}/mcps` with public metadata only (`id`, `name`, `transport`, `source_agent`, `supported`, `reason`), and `POST /api/agents/{id}/mcps/import` with `{ids}` to centralize selected definitions. `GET /api/mcps` lists imported public records. Analyzer stores `mcp_ids: string[]` only. Secrets stay in native read-only references or Keychain, never response/database/workflow/log literals. Detect unsupported transports/CLI targets and explain instead of pretending portability. A selected server must have a runnable task-local configuration; a native config projection must not bring unrelated servers along. If scope is changed by user's pending MCP preference, follow that answer.
4. Skill scan adds `modified_at` (ISO date of latest included file modification; use a documented fallback if unavailable). Merge known source-agent provenance on deduplicated imports so cross-agent status is truthful.

### Appearance APIs

Extend existing `/api/settings` with backward-compatible typed defaults:

```
text_font: ""                 // empty = existing preset/system fallback
code_font: ""                 // empty = system monospace
font_size: 14                 // 12..22 px
code_font_size: 13            // 10..22 px
background_image: ""         // empty or app-managed image ID, never arbitrary URL/path
motion_enabled: true
undo_limit: 5                 // integer 1..50
```

Retain palette/accent/canvas/font/custom_font compatibility. `PUT /api/settings` persists selected appearance as default and returns complete typed settings. Validate types/ranges and preserve non-Latin local font family names. Unknown arbitrary CSS must not become executable styles.

- `GET /api/fonts` -> `{fonts: [{family, monospace}], source, error?}`. Enumerate installed families with a bounded cached macOS CoreText or system-font query; do not upload or expose font files. Graceful unsupported-platform fallback, no fake detection claim.
- `POST /api/appearance/background` multipart field `file` -> `{id, url}`. Accept validated raster images (PNG/JPEG/WebP), reject malformed/SVG/oversize (>10 MB)/unreasonable dimensions; store under kxy data, no original-file overwrite. `GET /api/appearance/background/{id}` serves only managed validated images. Save image ID as default; clear image via setting. Keep colors underneath it.

### Frontend

- Extend current warm, muted, rounded flat UI. Consolidate the duplicate appearance forms or route the inspector to the global panel. Local fonts get searchable selects/datalists, separate text/code settings, both font sizes, image upload/clear, live preview, and a clear `保存为默认样式` action. Reset remains available. All settings round-trip and work after refresh.
- Skill discovery list gets case-insensitive name search and explicit name/date sort controls with ascending/descending state; preserve checked items through filtering and show no-match state and dates. Cross-agent attachment calls mount preview and reports actual outcome. Global Skills/MCP inventory and analyzer MCP checkboxes follow backend contract; unsupported targets are labelled and cannot silently run.
- Replace/augment static XYFlow dots with one pointer-events-none Canvas animation. Background pointer movement produces decaying dot trails; selection produces outward particles surrounding the selected card. Track viewport/zoom and selected-node bounds. Cap particle count and frame work, clean up listeners/rAF, pause hidden tabs, respect `prefers-reduced-motion`, provide motion toggle. No React state update each frame, no interaction interception, no extra animation dependency.
- Undo button and Cmd/Ctrl+Z outside text editors, default history 5, settings 1..50. Store graph editing snapshots only in session memory. One drag gesture = one step; don't record selection, dimensions, viewport changes or run-status updates. Include edits/add/delete/connect/import/pack/unpack and nested blackbox edits, restoring a consistent graph/navigation state. Coalesce typing changes. Explain disabled/empty state. Undo cannot cancel external side effects. History is not persisted across refresh; only the depth preference is saved.

## Acceptance

Backend author runs meaningful isolated tests for full-hash collisions, immutable source/run snapshots, cross-agent real upstream projection, corrupted/conflicting mapping, MCP secret exclusion and supported config parsing, fonts, settings migration/range validation and image validation. Use synthetic data; do not spend model tokens for plumbing tests.

Frontend author builds production bundle and executes isolated browser tests for fonts/images/default persistence, search/sort, all main undo paths (including nested graph), animation DOM/canvas behavior and reduced motion. Parent independently reviews changes and exercises browser appearance, undo, import and selection effects, plus a real selected-Skill run when needed to validate changed runtime semantics. Compare source/global CLI config hashes without printing secrets. Keep all V2 regression suites passing.

Parent records `acceptance/V3_REPORT.md` with PASS / NOT RUN / limitations, evidence and fresh code hashes. Only after acceptance, rebuild/restart kxy on 8710 preserving current data. Never reload the user's pre-existing browser tab with unsaved graph edits.

Sources: [SkillHub](https://github.com/xieshentoken/skillhub/tree/531ca63d3740fd2ac6f06eee531c1874ada01db2), installed CLI help/config readers in V2, existing XYFlow implementation.

## Acceptance-driven implementation details

Actual Codex startup can update its native config even with `--ignore-user-config`. Its CODEX_HOME is therefore isolated per node. A necessary native auth file is copied only into ephemeral `.cli-state` with mode 0600, excluded from artifacts and cleared on terminal/error paths and interrupted-run recovery. No whole native configuration or Skill directory is copied. macOS rejects nested Seatbelt execution, so keep Codex's native command sandbox rather than adding a second one.

For an explicitly selected MCP server, Codex uses the documented per-server `default_tools_approval_mode="approve"`; `auto` still requests interaction according to tool annotations and cannot run reliably through a headless CLI. Global approval and sandbox policies remain unchanged. HTTP headers use `env_http_headers`, stdio environment references use `env_vars`, Claude uses `${VAR}`, and OpenCode uses `{env:VAR}`. Composite authentication values are assembled in memory. Unknown OAuth/helper configurations are not silently migrated.
