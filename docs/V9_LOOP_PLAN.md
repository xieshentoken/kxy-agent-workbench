# V9 bounded multi-agent loops

User approved the five loop improvements. Implementation by existing Luna session; parent acceptance. Keep direct functions in existing modules, actual LFX, no new orchestration framework.

## Representation and execution
- Store as blackbox with optional data.loop.enabled; library offers 循环黑盒. Existing normal blackboxes and outer DAG validation retain behavior. The loop body remains a DAG with input/output markers, executor and reviewer analyzer nodes selectable by stable internal node ID. Ordinary nested blackboxes allowed; nested enabled loops explicitly rejected in this version.
- Compile enabled loop into one outer LFX component. Its async method runs a fresh inner LFX graph per round (await, no nested asyncio.run). Reuse component builders. Snapshot traversal must still include child files, model bindings, skills and grants. Add only necessary optional context arguments to existing functions.
- A round has explicit original goal/input, latest executor result, review issues, next action and bounded previous-round summary. UI chooses feedback fields. Send this as visible input context, never append hidden prompt text. Editable template reviewer prompt documents strict JSON passed:boolean, issues:array of strings, next_action:string. Parse only selected reviewer output; invalid/missing review is an actionable failure, never pass. Successful reviewer ends loop; outer output is selected executor result, with review provenance retained separately.
- Defaults 3 rounds and 1800 seconds active execution total; bounded configurable max 50 rounds. Manual cancel uses existing process cancellation. Enforce timeout during CLI calls, not just between rounds. Waiting for human decision must not consume active execution budget. On exhausted budget persist waiting state and explicit controls to extend bounded budget or stop; never auto-accept unpassed output. Reuse existing approval machinery where practical, retaining durable decision and restart behavior. Do not display fabricated token/cost accounting.

## Durability and files
- Identify checkpoints by run + loop path + round + internal node; retry attempt remains a separate dimension. Fresh iteration cannot restore prior iteration output. Preserve immutable per-round artifact files and payload hashes. Current-round resume reuses completed nodes only; completed rounds do not execute again.
- Prefer existing run_nodes with scoped IDs plus one small additive round record table for input/review/output/active-time/status. Keep V8 ordinary-run resume compatible. Snapshot migration must not invalidate existing resumable V8 runs.
- Loop child containers may collect previews but must not export intermediate rounds to granted folders. Explicitly reject granted containers inside loops for this first version with actionable instruction to place authorized output after loop. Final accepted executor artifacts traverse existing authorized export path. No bypass of grant revocation, path containment, CLI sandbox, keychain or literal prompt behavior.

## Frontend
- Library creation and blackbox inspector loop configuration; retain normal nested editing and preset import/export. Display current round/status on card.
- Execution details allow selecting loop and round, inspecting actual round inputs, executor result, parsed review, and previous/current text difference (simple line diff, no new dependency). Show budget pause and actionable bounded continuation/cancel.
- README explains executor/reviewer setup and iteration vs retry; existing human/node interaction redesign remains deferred.

## Focused acceptance
- Production TypeScript build; about 4-6 meaningful synthetic runtime scenarios covering pass on round two with distinct agents, limit pause/continue, interruption within round and checkpoint isolation, malformed reviewer and final-only authorized export/revocation. Include ordinary DAG resume compatibility in these checks. One focused browser walkthrough for loop creation/configuration/round inspection. No large historical test battery or unrelated edge-case expansion. Clearly label fixtures, no paid inference claims.
- Back up touched files first; build candidate dist-v9; leave formal service unchanged until parent accepts. Report changes, exact commands, limitations and source paths. Parent handles independent acceptance and final publication.
