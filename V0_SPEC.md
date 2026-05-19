# AgentTerminalContact V0 Spec

## Contract

`agent-contact send` wraps tmux pane contact with a fail-closed contact check.

V0 must prove:

- target repo and provider resolve to exactly one tmux-managed session
- explicit `--session` discovery scans every pane in every window of that session
- the target is locked to one tmux `%pane_id`, not a mutable session target
- the provider process is a live foreground process on the target pane TTY
- provider identity is verified from `/proc/<pid>/cmdline` plus `/proc/<pid>/exe`, not only flattened `ps args`
- provider package roots are accepted only when the exact package root is listed in `AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS`
- bare Node-style launchers are accepted only when their exact executable directory is listed in `AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS`
- `agent-contact trust-roots` can discover narrow package/launcher root candidates without sending only when the package root is anchored by the caller's provider command on `PATH`
- the pane still has the same cwd, process command, pid, and provider evidence immediately before send
- the target pane is a detached tmux-managed worker at an idle prompt or clearable pending composer state proven by provider text plus tmux cursor metadata
- visible composer text in a detached tmux-managed worker is cleared before sending a fresh guarded payload; attached sessions, busy/working panes, trust prompts, approval prompts, dead/unknown panes, ambiguous identity, and wrong-provider matches refuse
- the message payload contains no bracketed-paste markers or terminal control characters except newline and tab
- the guarded contact payload is a single line containing a generated `CONTACT_ID` and `MESSAGE_JSON`, without tmux bracketed-paste wrapping
- Codex starter-placeholder prompts that dry-run accepts report `would_clear_and_send` and are sent with literal key input after clearing instead of `paste-buffer`, so live send can materialize the guarded contact before submit
- pending composer text, including stale `CONTACT_ID`/`MESSAGE_JSON` residue, Codex pasted-content placeholders, wrapped/truncated residue, and arbitrary leftover worker text, dry-runs as `would_clear_and_send` and live send clears before pasting
- the post-send capture gives delivery evidence, or the result is reported as unproven after mutation
- installed AgentTerminalContact artifacts can be resolved through a source
  manifest that reports installed path, source path, install/check commands,
  ownership, and source-match status in JSON
- the source-owned `~/.local/bin/agent-tmux` wrapper delegates normal commands
  unchanged to `/usr/local/bin/agent-tmux` and adds explicit full-permission
  Codex aliases using `-s danger-full-access -a never`
- exact-session `agent-tmux codex-existing <repo> <session>` is source-owned
  for the supplied session name: it verifies that exact tmux session exists, is
  rooted at the requested repo, and is Codex-like before returning it, and exact
  absence or mismatch is reported as precise session evidence rather than a
  delegated multiple-session refusal
- the source-owned `~/.local/bin/agent-tmux` wrapper provides patch-artifact
  code-map sidecar aliases that derive deterministic session names from the
  resolved repo root and anchor, launch Codex from an isolated artifact
  directory with a visible workspace-write permission profile, disabled network
  access for model-run shell commands, wrapper-owned `CODEX_HOME` deny-read for
  model-run shell commands, and print the artifact/runtime directories plus
  transcript log path before launch
- code-map sidecar Codex processes run under `bwrap` with no host `/` bind,
  private `/dev`, read-only `/dev/shm`, private `/tmp` and `/run`,
  wrapper-owned `HOME`/`CODEX_HOME`, hidden host home except trusted Codex/Node
  executable paths, selected host inspection tools bound by exact file plus
  library dependencies instead of broad `/usr/bin` or `/usr/lib` binds, hidden
  `/usr/local/bin`, shared network for Codex API access, the sidecar artifact
  directory as the only writable map-output bind, and a separate wrapper-owned
  runtime bind for Codex state
- fork sidecars copy the requested Codex session file from source
  `CODEX_HOME/sessions` plus the matching `session_index.jsonl` entry when
  present into the wrapper-owned `CODEX_HOME` before launch
- Codex auth/session files are wrapper-managed runtime inputs, not sidecar
  outputs; the sidecar permission profile deny-reads wrapper-owned `CODEX_HOME`
  from model-run shell commands, disables shell network access, and artifact
  validation rejects direct Codex auth material and runtime-looking paths inside
  supervisor-consumed artifacts
- code-map sidecar prompts explicitly forbid production source edits, tests,
  config edits, install/rollout, commits, ticket dispatch, agent contact,
  `apply_patch`, and tmux mutation
- code-map sidecars may write map outputs only under their artifact directory;
  desired map or project-memory updates are emitted as proposed patch/artifact
  files for a supervisor to apply through the normal source workflow
- code-map sidecar artifact directories are created atomically by the wrapper;
  pre-existing final directories, symlink final directories, and paths that
  resolve inside the repository root are refused before launch
- guarded contact to an exact wrapper-launched sidecar session accepts the
  original repository root only after validating the wrapper sidecar registry
  outside the writable artifact tree for the exact wrapper-shaped session, repo,
  anchor, artifact directory, permission, filesystem-isolation, and validator
  fields
- `codex-code-map-validate-artifacts` validates the sidecar artifact directory
  before supervisor application, requires the wrapper sidecar registry outside
  the writable artifact tree to bind session, repo, anchor, allowed output
  directory, sandbox permission, filesystem-isolation description, and validator
  command, checks it against the artifact-local `SIDECAR_REQUEST.txt` audit
  copy as an exact wrapper-shaped schema, rejects artifact directories inside
  the registry repo, and rejects
  proposed patch or mirrored file targets outside the narrow
  code-map/project-memory allowlist
- `codex-code-map-sidecar-fork` maps a Rewind/Codex fork session id into a new
  deterministic tmux sidecar instead of requiring callers to paste a fork
  command into an existing pane
- `codex-code-map-sidecar-fork` accepts only a Codex session UUID; flags, thread
  names, and raw `codex fork ...` command text are refused before launch
- sidecar sessions are created with `tmux new-session`, so an exact session-name
  race fails instead of reusing an existing pane

## Refusals

The command refuses before sending when:

- no matching tmux session exists
- more than one matching session exists
- the matching session has multiple matching panes
- an explicit session does not match the requested repo/provider
- provider evidence is missing from the live foreground pane process, authoritative cmdline/exe, or explicit trusted package root
- provider evidence relies on a broad parent trusted root instead of the exact package root
- provider identity uses a bare Node-style launcher outside explicit trusted launcher roots
- provider identity uses a Node executable with a spoofed provider entrypoint in `argv[0]`
- exact-session `agent-tmux codex-existing <repo> <session>` sees the supplied
  session is absent, rooted at a different path, or not Codex-like
- the selected pane changes cwd, process command, pid, or provider evidence before send
- a real send targets a tmux session currently attached to a client
- the message contains a bracketed-paste marker or C0/C1 control character other than newline or tab
- the target pane shows pending user text
- the target pane shows a trust or approval prompt
- the target pane is working, dead, or unknown
- a full-permission `agent-tmux` alias is asked to pass
  `--dangerously-bypass-approvals-and-sandbox`
- a code-map sidecar launch would reuse an existing deterministic sidecar
  session name
- a code-map sidecar exact session-name race is detected by tmux at creation
- a fork sidecar receives anything other than a Codex session UUID
- the deterministic artifact directory already exists
- the deterministic artifact directory is a symlink
- the configured code-map artifact path resolves inside the repository root
- sidecar artifact validation sees neither `MAP_REPORT.md` nor a proposed map
  update; `MAP_REPORT.md` alone is the report-only lane
- sidecar artifact validation sees proposed patch or mirrored file targets
  outside the explicit map target policy: `.project-memory/code-map-state.json`,
  `.project-memory/project-memory-state.json`, bounded `.project-memory/` policy
  namespaces (`code-map/`, `project-memory/`, `routing/`, `indexes/`,
  `subsystems/`) containing `.md`, `.json`, or `.jsonl` files,
  `docs/CODEBASE_ARCHITECTURE_INDEX.md`,
  `docs/CODEBASE_SUBSYSTEM_MANIFEST.json`, direct Markdown files under
  `docs/SUBSYSTEMS/` (`docs/SUBSYSTEMS/*.md`),
  `CODE_MAP.md`, `PROJECT_MEMORY.md`, `docs/CODE_MAP.md`, or
  `docs/PROJECT_MEMORY.md`; runtime/credential/key/token path components such
  as `codex-home`, `.codex`, `session_index.jsonl`, `credential`, `secret`,
  `token`, `password`, `private-key`, `access-key`, `ssh-key`, or `api-key` are
  rejected even inside allowed namespaces, while ordinary Codex/auth/session map
  topics are allowed when they do not look like runtime files or credential
  material
- sidecar artifact validation sees symlink/non-regular entries anywhere in the
  artifact tree, or patch modes that would create symlinks/non-regular files
- sidecar artifact validation sees unsupported patch header forms, binary
  content, direct Codex auth material, or obvious auth/session key structures in
  supervisor-consumed artifact files

## Non-Goals

V0 does not patch Codex, Claude, or tmux internals. It does not contact
non-tmux live terminals. It does not patch `/usr/local/bin/agent-tmux`; the
source-owned user wrapper delegates to that explicitly non-owned helper.
Code-map sidecar launch does not select or message an existing owner lane; use
guarded `agent-contact send --session <sidecar-session>` only after the exact
sidecar identity is known and a dry-run accepts it.
If guarded contact returns `mutated_unsubmitted`, delivery is failed. Rerun
guarded `agent-contact send --dry-run` rather than switching to raw tmux input.
For detached tmux-managed workers, dry-run reports `would_clear_and_send` when
the composer contains visible text, and live send clears the composer before
sending a fresh guarded payload. Attached sessions, busy/working panes, trust
prompts, approval prompts, dead/unknown panes, ambiguous identity, and
wrong-provider matches continue to refuse.
