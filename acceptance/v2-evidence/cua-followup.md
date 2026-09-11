# Parent CUA follow-up, 2026-09-06

Isolated application: http://127.0.0.1:8711, synthetic data root recorded in `../v2-browser-root.txt`.

- PASS: after a fresh page load, Codex executable `codex` and the previously saved synthetic Skill directory appear. This caught and verified the correction of an initial empty-draft cache bug.
- PASS: native model editing disables the actual-model field and hides the API-key form. Changed a synthetic test alias, saved successfully, invoked native discovery again, and verified the alias persisted.
- PASS: clicked the visible `导入资料文件夹` control and used its actual browser FileChooser with the synthetic `uploads` directory. The canvas acquired `本机文件选择验收.md` as a real file node. This was not a stubbed picker response.
- PASS: the analyzer with no explicit model displays discovered CLI effort values; selecting GPT-5.4-Mini narrows these to low/medium/high/xhigh, without the CLI-wide max/ultra values. Verified after normalizing the backend `supported_efforts` field in the frontend.
- Native executable/Skill/export path chooser: the page invoked the real `/api/picker` implementation and an `osascript` process was observed. CUA cannot select that unbundled application's window (`Invalid app`), so actual macOS chooser selection/cancellation remains NOT VERIFIED. Unit tests cover bounded argv and cancellation, and Playwright covers the frontend picker response contract. No permission boundary was bypassed.

The earlier automated browser results are in `browser/results.json`; those tests explicitly stub only `/api/picker` and use the real local backend/LFX for workflow execution.
