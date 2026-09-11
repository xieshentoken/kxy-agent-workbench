# V6 — reusable AI services, literal prompts, and output reception

Approved user scope 2026-09-08. Retain existing kxy stack and implementation session. Parent plans and independently accepts; Luna max implements. No WhatFa/global CLI changes or new tasks/agents. Authorized continuation; no new approval gate.

## Findings and decision

execute_cli currently appends task context, provenance requirements, format commands and other behavioral instructions to every node prompt. Grok command construction appends attachment instructions. Remove these Kxy additions. The CLI's own system prompt and deliberately mounted skills remain distinct. Preserve isolation, originals, snapshots and grant checks as code controls.

Retain React/XYFlow, FastAPI, SQLite, native Keychain and CLI execution. Extend existing functions/UI directly; no new service/adapter architecture or direct HTTP inference engine. References: [pi models](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md), [OpenCode providers](https://opencode.ai/docs/providers/), [Anthropic API](https://platform.claude.com/docs/en/api/overview), [Google models](https://ai.google.dev/api/models). Protocol and provider/display name are separate. Catalog access is not inference proof.

## Reusable AI service editor

- Independent global AI services page, usable without creating an Agent model. Reference image layout: preset, friendly name, endpoint, masked API key, interface format; test/fetch catalog, search/multiselect, selected models, custom model addition, save/edit/cancel.
- Reuse credentials identity and add a small credential_metadata table keyed by credential_id (name/API format/catalog JSON), preserving the original six-column credential contract. Agent models still reference opaque credential_id. One saved service can serve multiple compatible Agents/aliases. Friendly names replace managed IDs as primary UI labels.
- Keychain alone stores keys. Blank edit retains key; never reveal it or persist it in metadata/logs/export/files. Rotation may allocate a new Keychain ref before DB update. Validate metadata before writes. No real user Keychain writes during tests.
- Interfaces: OpenAI Chat Completions, OpenAI Responses, Anthropic Messages, Google Generative AI. ChatGPT/Pi Radius OAuth are distinct from API keys; do not imply API-key support. Presets include Custom/OpenAI/Anthropic/Google/OpenRouter; additional compatible providers are simple metadata.
- Catalog requests bounded, no redirects, protocol-specific headers, sanitized IDs/error messages, no key echo. Persist selected model IDs/aliases and custom entries. Failed catalog allows manual entry; never invent effort capabilities.
- Saved-key tests are locked to saved endpoint/protocol. Changed endpoint/protocol with blank key requires re-entry before sending key to different destination. Preserve existing endpoint and redaction security.
- API analyzer creation selects saved service, service model, alias, known effort. Implement verified native CLI env/config mappings. Unsupported combinations visibly disabled and rejected at create/update/run; no protocol/native-login fallback.
- Codex uses Responses; Claude uses Messages; pi supports documented custom models; OpenCode needs correct SDK/model mapping. Other CLIs only with verified mappings. Service saving independent of executable availability.

## Prompt and returned text

- Effective CLI user prompt equals textarea exactly. No suffix/prefix, fallback prompt or format commands. Explain CLI system instructions and selected skills still apply.
- Keep editable defaults for new analyzers/templates. Workspace instructions needed for files/skills belong visibly in defaults or an explicit insert-hints control: input-context.json, inputs/, skill-manifest.json, outputs/. Never rewrite existing custom prompts or move hidden instructions into runtime AGENTS.md.
- Preserve input manifest, copied attachments and skill mounting; use native file flags without changing prompt.
- New output choice auto follows prompt, preserves reply text and may parse genuine JSON for routing. Legacy markdown/text/json accepted without adding instructions. Explicit JSON/schema is optional local validation, labeled that prompt itself must request JSON.
- No unsolicited answer file in auto mode. Generated-files-only response is valid. Never replace text reply with paths or manifest JSON.

## Container text and real files

- Dedicated readable/selectable text reply area in selected output container, including upstream attribution for multiple replies. Text-only works without disk export. Preserve old run originals.
- Separate optional reply exports (txt/md/json, parsed content vs full metadata clearly labeled) from allowed generated-file extensions. Empty reply export allowed. Do not convert text into every selected file type.
- Allow common research formats (txt/md/json/csv/pdf/docx/xlsx/pptx/png/jpg/jpeg/webp/svg/html/mp4/avi/zip). Copy only real generated allowed files to unique authorized directory. Never rename text into PDF/DOCX. Excluded artifacts remain internal and visibly identified.
- Preserve containment/symlink/size/count/no-overwrite/revocation checks, nested containers and readable old workflows/runs. UI accepted/excluded lists agree with actual exported files. Extension policy is reception, not file conversion or content validation.

## Development and acceptance

1. Timestamped source backups, parent formal data baseline; metadata/service APIs and CLI mappings.
2. Service UI, edit/reuse/catalog/manual entry/protocol gates.
3. Literal prompts and auto results, container text/file UI and runtime.
4. Build frontend/dist-v6 only. No publish or port8710 restart; parent publishes accepted build.
5. Parent independently captures exact synthetic CLI prompt with attachments/skills and validates Keychain references, shared service, protocol gates, no redirects/secret echo, real file allowlist and grants. Browser at 1440x900/1280x720; V5 bindings and relevant V4 security regressions.

Use isolated temporary data and synthetic CLI/provider/Keychain fixtures. No real paid inference or Keychain mutation. Record evidence limits. Do not rebuild historical ZIPs.
