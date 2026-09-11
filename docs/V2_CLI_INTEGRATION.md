# V2 CLI/configuration integration contract

This document is the hand-off contract between `backend/agent_config.py` and the
runtime owner. It is intentionally based on direct functions and one router. The
configuration module does not start model calls, mutate a user's CLI config, or
own workflow scheduling.

## App registration

The runtime owner should register the router after creating the FastAPI app and
before the `StaticFiles` catch-all is mounted:

```python
from backend.agent_config import ensure_agent_config_schema, router as agent_config_router

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    ensure_agent_config_schema()
    yield

app = FastAPI(title="kxy", version="0.1.0", lifespan=lifespan)
app.include_router(agent_config_router)  # before app.mount("/", StaticFiles(...))
```

`ensure_agent_config_schema()` is idempotent, creates all seven seeded profiles,
and preserves existing `credentials`, `analyzers`, `workflows`, runs and files.
The configuration module imports `backend.app` only inside helper calls, so the
router can be imported without a circular import during app construction.

## Callable helpers

The following are the stable call sites. `Path` arguments must already point at
the per-run/per-node workspace or at a user-selected local source. All subprocess
helpers use argv arrays and return no shell command string.

```python
def ensure_agent_config_schema() -> None

def list_agent_profiles() -> list[dict[str, Any]]
def get_agent_profile(agent_id: str) -> dict[str, Any]
def discover_agent(agent_id: str) -> dict[str, Any]

def scan_agent_skills(
    agent_id: str,
    roots: Sequence[str] | None = None,
    *,
    max_skills: int = 200,
    max_depth: int = 8,
) -> list[dict[str, Any]]

def import_agent_skills(
    agent_id: str,
    paths: Sequence[str],
) -> dict[str, list[dict[str, Any]]]

def resolve_model_binding(config: Mapping[str, Any]) -> dict[str, Any]
def snapshot_model_binding(config: Mapping[str, Any]) -> dict[str, Any]

def build_headless_command(
    agent_id: str,
    prompt: str,
    workspace: Path,
    *,
    executable: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    attachments: Sequence[Path] = (),
    skills: Sequence[Path] = (),
    expect_json: bool = False,
    network: bool = True,
    last_message: Path | None = None,
    endpoint: str | None = None,
    credential_env_name: str | None = None,
) -> list[str]

def prepare_headless_environment(
    agent_id: str,
    workspace: Path,
    *,
    credential_id: str | None = None,
    network: bool = True,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]

def wrap_headless_command(
    argv: Sequence[str],
    agent_id: str,
    workspace: Path,
    *,
    network: bool = True,
) -> tuple[list[str], Path | None]

def parse_final_output(
    agent_id: str,
    lines: Sequence[str],
    *,
    last_message: Path | None = None,
    expect_json: bool = False,
) -> dict[str, Any]

def run_native_picker(
    kind: Literal["file", "folder"],
    *,
    timeout: float = 60.0,
) -> dict[str, Any]
```

`prepare_headless_environment()` may hold a selected Keychain secret, or a
verified native CLI credential value from an explicit allowlist, in the
returned process environment. The caller must keep it in memory only, pass it
to the child, redact it from stream output, and never put the environment in a
workflow/run snapshot or API response. The helper reads the existing
`credentials` table and reuses `keychain_secret()`/`keychain_has()` from
`backend.app`; it never receives a secret through workflow JSON. An explicit
`credential_id` wins and suppresses native credential, endpoint, and model-env
inheritance.

CLI-specific argv details are part of this contract. OpenCode treats `--file`
as a greedy array option, so `build_headless_command()` places every file
before a final `--` prompt separator; the OpenCode handler merges that `--`
bucket with its message bucket. Claude Code and WorkBuddy add documented
`--verbose` only for `stream-json` output, which is required for the complete
event stream. Their single-result JSON mode does not add it. pi model discovery
uses an isolated `PI_CODING_AGENT_DIR`; when pi's native `auth.json` has
configured providers, only those provider names are copied into a temporary
placeholder-auth file so the built-in catalog can be listed. No auth value,
models file, or global config is copied or modified, and catalog discovery is
not an authorization check.

For a real node run, `prepare_headless_environment()` places CLI state under
`<node workspace>/.cli-state/<agent>`. Claude uses its config/debug/tmp
variables, pi uses `PI_CODING_AGENT_DIR`, Hermes uses `HERMES_HOME`, and
WorkBuddy uses its config/data variables with compile-cache and background
tasks disabled. OpenCode uses isolated XDG directories. Verified native
compatibility is deliberately narrow: when no explicit credential is bound,
OpenCode gets a read-only reference to the native
`$XDG_DATA_HOME/opencode/auth.json` account file, Claude receives only the
allowlisted `env` keys from `~/.claude/settings.json`, Hermes references its
native `.env` and `config.yaml`, and WorkBuddy reads only the documented
`CODEBUDDY_*` env allowlist from `~/.codebuddy/settings.json` when that regular
file exists. Nothing is copied, native files are never modified, and the
desktop WorkBuddy login/session store is not guessed; if its documented
settings file is absent, an API/Keychain credential or a future verified
session path is required. The current machine also has no verified native pi
auth provider configured; pi catalog discovery uses a placeholder probe only
and does not establish a pi login.

## API routes and response shapes

All routes below are added by `router`, whose prefix is `/api`.

### Agents

`GET /api/agents` returns all seven profiles without running a synchronous
version/model probe:

```json
[
  {
    "id": "codex",
    "label": "Codex",
    "executable": "codex",
    "resolved_executable": "/.../codex",
    "skill_roots": ["/Users/.../.codex/skills"],
    "available": true,
    "version": "codex-cli ...",
    "status": "READY",
    "message": null,
    "supported_efforts": ["low", "medium", "high"],
    "capabilities": {"headless": true, "model_discovery": true},
    "models": [],
    "discovered_at": "..."
  }
]
```

`PUT /api/agents/{id}` accepts only `{ "executable": string,
"skill_roots": string[] }` fields that are present. Executable values are a
single binary name or an explicit file path; they are never interpreted by a
shell. Root paths are canonical-checked on use and are not copied or modified.
`POST /api/agents/{id}/discover` performs bounded `--version`/`--help` probes
and refreshes native model records. A failure is stored as an unavailable
status with an actionable message.

### Models

`GET /api/agent-models` returns every native/API/manual record. Profiles also
embed their records in `models`.

```json
{
  "id": "native-codex-...",
  "agent_id": "codex",
  "cli_id": "codex",
  "model": "gpt-5.6-luna",
  "alias": "GPT-5.6 Luna",
  "source": "native",
  "efforts": ["low", "medium", "high", "xhigh", "max"],
  "default_effort": "medium",
  "discovery_source": "codex models_cache.json",
  "credential_id": null
}
```

Native IDs are deterministic from agent plus CLI model ID. API IDs include the
agent, model ID and credential binding, so a native/API duplicate remains two
records. Manual IDs are created once and remain stable across alias/effort
edits. `cli_id` is always the owning Agent ID (`codex`, `claude`, `opencode`,
`pi`, `hermes`, `workbuddy`, or `deepseek`); `model` is the actual model ID
passed to that CLI. `source` is one of `native`, `api`, or `manual`; native
records are refreshed only by the corresponding discovery call. A refresh
keeps a user-edited native alias and any still-valid native default effort;
native capability fields remain owned by discovery. Native records cannot be
given credentials; create a separate `source: "api"` record for a Keychain
binding. Hidden/internal model cache entries are filtered. No guessed model or
effort list is emitted as a native discovery result: documented CLI-level
effort choices are retained as documented capabilities, while unknown model
defaults stay `null`.

`POST /api/agent-models` creates an explicitly labeled API or manual record.
The minimal create payload may use `cli_id` without a second `agent_id` field.
API records require an existing `credential_id` from `/api/credentials` or
`/api/credentials/store`; only the opaque ID is persisted. `PUT` edits alias,
model, efforts/default effort and the credential binding for manual/API
records without changing the record ID. For native records, `PUT` is limited
to `alias` and `default_effort`; discovery owns model identity and capability
fields. `DELETE` removes the selected record. Unknown or deleted model
references fail with a rebind error rather than selecting a different model.

The current native discovery sources are deliberately explicit:

| Agent | Model source | Effort source | Boundary |
|---|---|---|---|
| Codex | filtered `~/.codex/models_cache.json` | per-model reasoning levels | hidden/internal entries are omitted |
| Claude Code | documented aliases in `claude --help` | documented `--effort` choices | this does not prove login or billing access |
| OpenCode | successful `opencode models` output | documented `--variant` only if listed | catalog availability is not account authorization |
| pi | isolated `pi --list-models` with provider-name-only auth context, plus read-only `models.json`/`models-store.json` | documented `--thinking` choices | probe uses a temporary config dir and offline mode; provider catalog presence is not authorization |
| Hermes | read-only local model catalog plus selected `config.yaml` model/provider | none unless catalog explicitly provides it | scans `~/.hermes/skills`, the hermes-agent skills tree and the desktop bundle; no refresh/auth/config mutation is performed |
| WorkBuddy | documented models in bundled `codebuddy --help` | documented `--effort` choices | bundled CLI is used when no PATH command exists |
| DeepSeek Harness | none unless a real `headless` profile passes help verification | none | `web` profile and generic launcher are not substituted |

Every discovered record includes `discovery_source`. A native/API/manual
record indicates configuration provenance only; it is not a guarantee of
account login, model entitlement, quota, or successful inference.

### Skills

`GET /api/agents/{id}/skills` returns a bounded array of candidates. Each item
contains at least:

```json
{
  "path": "/Users/.../.codex/skills/research",
  "name": "research",
  "description": "...",
  "source": "codex:/Users/.../.codex/skills",
  "category": "...",
  "snapshot_hash": "..."
}
```

The scanner follows an explicitly selected root symlink and safe nested
symlinked entries, rejects escaping descendant links and loops, and stops at
the file/depth/byte limits. It reads only `SKILL.md` metadata during discovery.
`POST /api/agents/{id}/skills/import` accepts
`{ "paths": ["the previously returned skill directory paths"] }` and returns
`{ "imported": [...], "errors": [...] }`. Every path is revalidated against
the configured root immediately before copy-only import. Existing kxy skill
snapshot/import helpers are reused; imported metadata records the native source
and source snapshot. Import never executes a skill and never changes a global
agent directory.

### Native picker

`POST /api/picker` accepts `{ "kind": "file" }` or `{ "kind": "folder" }`.
It returns `{ "cancelled": true }` for a user cancel and
`{ "cancelled": false, "path": "..." }` for an existing selected path. The
macOS implementation uses one fixed AppleScript passed in an argv list to
`/usr/bin/osascript`, a 60 second timeout and a process-wide dialog lock.
`kind` is an argv value, never interpolated into the script. Non-macOS hosts
return an explicit unavailable error. A picker result does not create an
output grant; the existing grant endpoint still requires a separate explicit
folder authorization.

## Minimal runtime integration

At run creation, resolve a model once and put the returned binding in the
immutable run snapshot. Do not resolve it again after a human pause or while a
run is executing:

```python
binding = snapshot_model_binding(node_data)
node_data = {**node_data, "resolved_model": binding}

argv = build_headless_command(
    binding["agent_id"], full_prompt, node_workspace,
    executable=binding["executable"],
    model=binding["model"] or None,
    effort=binding["selected_effort"] or None,
    attachments=attachments,
    skills=mounted_skill_paths,
    expect_json=bool(node_data.get("expect_json")),
    network=bool(node_data.get("network", True)),
    last_message=last_message,
    endpoint=binding.get("credential_endpoint") or None,
    credential_env_name=binding.get("credential_env_name"),
)
env = prepare_headless_environment(
    binding["agent_id"], node_workspace,
    credential_id=binding.get("credential_id"),
    network=bool(node_data.get("network", True)),
)
wrapped, profile_file = wrap_headless_command(
    argv, binding["agent_id"], node_workspace,
    network=bool(node_data.get("network", True)),
)
```

The existing runtime remains responsible for `Popen(start_new_session=True)`,
bounded/redacted event collection, timeout/cancel process-group handling,
artifact confinement, and LFX scheduling. The wrapper grants writes only to the
node workspace; output grants are applied later by kxy and are never handed to
the CLI. Network-off must be technically enforced by the selected sandbox or
the helper raises an unavailable error. No `--yolo`, dangerous bypass, shell
evaluation, global config write or credential export is permitted.

## Verified local boundaries

Codex, Claude, OpenCode, pi and Hermes have installed command names or native
launchers on the current host and are probed only with help/version commands.
WorkBuddy has a bundled `codebuddy` executable under the installed app even
when `workbuddy`/`workbuddy-cli` are absent from `PATH`; the preset keeps that
fact in its executable candidate list. DeepSeek Harness is exposed as a preset
but its configured DSH `headless` profile must exist and pass an explicit help
probe before command construction is available. A generic `dsh` launcher or
the existing `web` profile is not treated as headless execution.
