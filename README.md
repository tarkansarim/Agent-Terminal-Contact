# AgentTerminalContact

AgentTerminalContact is a thin safety layer for contacting live terminal agents.
It does not replace Codex, Claude, tmux, or `agent-tmux`. It guards the risky
operation: sending text into another live agent chat.

V0 supports tmux-managed sessions only.

```bash
bin/agent-contact send \
  --repo /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2 \
  --provider codex \
  --message "Please report the current issue and verifier."
```

Use `--dry-run` to see whether the target would be accepted without sending:

```bash
bin/agent-contact send --repo /path/to/repo --provider codex --message "..." --dry-run
```

The tool refuses to send when the target session is ambiguous, attached to a
client for a real send, the pane is not at an idle empty prompt, pending user
text is visible in the composer, or the message contains terminal control
bytes. Newlines and tabs are allowed in the requested message; the actual paste
payload is encoded onto one `MESSAGE_JSON` line and sent without tmux
bracketed-paste wrapping. Bracketed-paste markers and other C0/C1 controls are
refused before discovery.

Targeting is pane-locked. Discovery selects a tmux `%pane_id`, verifies provider
evidence from the pane TTY's live foreground process, verifies the authoritative
`/proc/<pid>/cmdline` and `/proc/<pid>/exe`, captures that pane, revalidates the
same pane immediately before send, and then sends only to that pane. When
`--session` is provided, discovery scans every pane in every window of that tmux
session before deciding whether the target is unique.

Provider package roots fail closed unless the exact package root is explicitly
trusted for that command invocation. Broad parent directories are rejected. Bare
Node-style launchers also fail closed unless their launcher root is explicitly
trusted. Use `trust-roots` and export narrow roots only:

```bash
bin/agent-contact trust-roots --repo /path/to/repo --provider codex --json

AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS=/home/tarkan/.nvm/versions/node/v22.22.0/lib/node_modules/@openai/codex \
AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS=/home/tarkan/.nvm/versions/node/v22.22.0/bin \
  bin/agent-contact send --repo /path/to/repo --provider codex --message "..." --dry-run
```

`trust-roots` reads the live pane process and prints the narrow package and
launcher roots to export only when the live package root is anchored by the
same provider command found on the caller's `PATH`. Multiple roots are separated
with `:` on Linux. Launcher roots are exact executable directories, not broad
parent directories.

Idle prompt detection uses both text and tmux cursor metadata. Text that merely
prints a prompt marker and model footer in the pane output is not enough to prove
the target composer is idle. The sender performs a final prompt-state recapture
immediately before paste; if later post-send evidence cannot be collected, the
result is reported as `sent_unproven`, not as a pre-send refusal.

## Development

Run the tests from the repo root:

```bash
PYTHONPATH=src python -m unittest discover -s tests
python -m compileall -q src tests
```

For package-style local use, install into a project virtualenv:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/agent-contact --help
```

Install the user-level command and skill:

```bash
bash scripts/install.sh
```

If an installed skill already exists and differs from this repo source, inspect
the diff and use `--force` only when replacing it is intentional:

```bash
diff -u ~/.codex/skills/agent-tmux-control/SKILL.md skills/agent-tmux-control/SKILL.md
bash scripts/install.sh --force
bash scripts/install.sh --check
```

`--check` verifies the installed skill matches this repo source and that
`agent-contact` and the source-owned `agent-tmux` wrapper resolve on `PATH`.

## Installed Artifact Ownership

Use `artifact-info` to identify whether an installed command, skill, hook, or
wrapper is owned by this source repo before patching anything in place:

```bash
agent-contact artifact-info agent-contact --json
agent-contact artifact-info agent-tmux --json
agent-contact artifact-info /usr/local/bin/agent-tmux --json
agent-contact artifact-info --all --json
```

The ownership manifest is `artifact_ownership.json`. Each entry declares the
installed path, source path when owned, install/check commands, and whether this
repo explicitly owns or does not own the artifact. Other repos can follow the
same pattern: keep a source manifest at the repo root, make installed wrappers
or CLIs report it as JSON, and distinguish `owned` from `not_owned` instead of
guessing from filenames.

This repo owns:

- `~/.local/bin/agent-contact`
- `~/.local/bin/agent-tmux`, a wrapper that delegates normal commands to
  `/usr/local/bin/agent-tmux`
- `${CODEX_HOME:-~/.codex}/skills/agent-tmux-control/SKILL.md`

It explicitly does not own `/usr/local/bin/agent-tmux`.

## Full-Permission Codex Workers

The source-owned `agent-tmux` wrapper adds full-permission aliases without
patching the delegated system helper:

```bash
agent-tmux codex-full <session> <repo> [codex-args...]
agent-tmux codex-resume-full <session> <repo> <thread-name-or-id> [prompt]
agent-tmux codex-resume-latest-full <session> <repo> [prompt]
```

These aliases expand to Codex CLI args `-s danger-full-access -a never` and
refuse `--dangerously-bypass-approvals-and-sandbox`. After the requested tmux
session preflight passes, the latest-resume alias resolves the latest thread and
launches `codex ... resume <thread> [prompt]` so a prompt is not misread as the
resume session id. Latest-thread parsing is fail-closed: stderr, multi-line
stdout, or anything other than the expected four tab-separated fields is refused.

Codex launch/resume routes through this wrapper require the requested tmux
session name to be unused. If that session already exists, the wrapper refuses
before launching so a prompt cannot disappear into a stale pane. Older Codex
sessions for the same repo do not steal these launches; the wrapper tells the
delegated helper to create the requested session. The wrapper also recognizes
the legacy supervise-style shape `agent-tmux codex-resume-latest <session>
<repo> -s danger-full-access -a never [prompt]` and routes it through the same
deterministic latest-thread path.

The wrapper also normalizes `agent-tmux codex-existing <repo>` for supervised
machine callers. A true no-existing-session result is `rc=1`, empty stdout, and
one stderr line beginning `agent-tmux: no Codex tmux session found for workdir:`;
ambiguous or broken helper results keep the delegated output and return code.
Other non-wrapper commands are delegated unchanged.

## Code-Map Sidecar Workers

For code-map patch-artifact analysis, use the source-owned wrapper instead of
pasting into an existing owner pane:

```bash
agent-tmux codex-code-map-sidecar /path/to/repo ticket58-pre-edit "Map the tmux/contact entry points."
agent-tmux codex-code-map-sidecar-fork /path/to/repo ticket58-pre-edit <codex-session-id> "Map from the Rewind fork."
```

The wrapper derives a deterministic session name from the resolved repo root and
anchor, for example `codex-map-agentterminalcontact-ticket58-pre-edit-...`.
It refuses if that exact sidecar session already exists; change the anchor to
launch a new sidecar. It does not discover, contact, or reuse old same-repo
owner sessions.

Both sidecar routes launch Codex from an isolated artifact directory with a
visible workspace-write permission profile that disables network access for
model-run shell commands:

```bash
-c sandbox_mode="workspace-write" -c sandbox_workspace_write.network_access=false -a never
```

The wrapper sets the sidecar working root to
`${AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT:-${XDG_STATE_HOME:-~/.local/state}/agent-tmux/code-map-sidecars}/<sidecar-session>`
and passes the repository root as a read-only input path in the prompt. The
sidecar may write patch artifacts only under that artifact directory. It must
not edit production source, tests, config, install scripts, user-level files, or
generated artifacts in place; it must not run `apply_patch`, commit, install,
dispatch tickets, contact other agents, or mutate tmux sessions.
The final deterministic artifact directory must not already exist or be a
symlink; the wrapper creates it atomically and refuses paths that resolve inside
the repository root.

The sidecar Codex process also runs inside `bwrap`: there is no host `/` bind,
host home is hidden except for trusted Codex/Node executable paths,
`/usr/local/bin` is hidden, selected host inspection tools are bound by exact
file plus their library dependencies instead of broad `/usr/bin` or `/usr/lib`
binds, `/dev` is a private bwrap device filesystem, the artifact directory is
the writable map-output bind, `/dev/shm` is overlaid read-only, and `/tmp` and
`/run` are private so tmux sockets are not exposed.
`HOME`/`CODEX_HOME` point under a separate wrapper-owned runtime directory next
to the artifact directory. In fork mode, the requested Codex session file plus
the matching `session_index.jsonl` entry when present are copied into that
wrapper-owned Codex home before launch. Codex auth/session files are
wrapper-managed runtime inputs; the wrapper adds a Codex
`permissions.filesystem.deny_read` entry for wrapper-owned `CODEX_HOME` so
model-run shell commands cannot read those credentials or session files. Auth
and session material must not be copied into sidecar artifacts. The wrapper
refuses artifact and runtime roots inside the repository so wrapper-created
state cannot land in the read-only input tree.

If map or project-memory files should change, the sidecar writes reviewable
artifacts such as `MAP_REPORT.md`, `PROPOSED_CHANGES.patch`, or proposed file
contents under `PROPOSED_FILES/` inside the artifact directory. Applyable
artifacts are limited to these map/project-memory targets:

- `.project-memory/**`
- `docs/CODEBASE_ARCHITECTURE_INDEX.md`
- `docs/CODEBASE_SUBSYSTEM_MANIFEST.json`
- direct Markdown files under `docs/SUBSYSTEMS/` (`docs/SUBSYSTEMS/*.md`)
- `CODE_MAP.md`, `PROJECT_MEMORY.md`, `docs/CODE_MAP.md`, `docs/PROJECT_MEMORY.md`

The supervisor validates sidecar artifacts before applying them:

```bash
agent-tmux codex-code-map-validate-artifacts <artifact-dir>
```

The validator requires the wrapper-written sidecar registry stored as a sibling
of the artifact directory, outside the sidecar-writable tree, and checks it
against the artifact-local `SIDECAR_REQUEST.txt` audit copy. The registry binds
the session, repo, and allowed output directory. The validator rejects any
proposed patch or mirrored proposed file targeting source, tests, config, install
scripts, user-level files, generated artifacts, or other non-map paths. It also
rejects unsupported patch path header formats, symlink/non-regular entries
anywhere in the sidecar artifact tree, patch modes that would create symlinks or
other non-regular files, binary content in supervisor-consumed artifacts, and
direct Codex auth material or obvious auth/session key structures in
supervisor-consumed artifacts. Runtime-looking paths such as
`.agent-tmux-runtime/` inside the artifact directory are rejected; wrapper-owned
runtime state lives outside the artifact tree. The artifact directory passed to
the validator must itself be a real directory, not a symlink, and must not
resolve inside the registry repo. The supervisor applies accepted map edits
later through the normal source workflow, with validation and commit evidence.

The wrapper prints the deterministic session, artifact directory, wrapper-owned
runtime directory, sidecar registry path, and transcript log path before launch
so supervisors can audit with:

```bash
agent-tmux log <sidecar-session>
agent-tmux transcript <sidecar-session> all
ls <artifact-dir>
```

When Rewind prints a `codex fork <session-id>` command, pass the UUID session id to
`codex-code-map-sidecar-fork`; do not paste the raw fork command into an
existing live pane. The wrapper rejects flags, thread names, and raw commands in
that position.

If a follow-up message is needed after launch, target only the known sidecar
session and run guarded contact first. For wrapper-launched sidecars,
`agent-contact` accepts the original repository root when an exact session is
provided and validates the sidecar registry outside the writable artifact tree
before selecting the pane:

```bash
agent-contact send --repo /path/to/repo --provider codex --session <sidecar-session> --message "..." --dry-run
```

If `agent-contact` returns `mutated_unsubmitted`, treat delivery as failed and
the visible composer text as guarded-contact residue only if it clearly contains
that failed `CONTACT_ID`/`MESSAGE_JSON` payload or Codex pasted-content
placeholder. Clear only proven residue with `agent-tmux clear-input
<sidecar-session>` and relaunch a new sidecar with a new anchor for the revised
focus. Do not fall back to raw `agent-tmux send` for sidecar contact unless the
current operator explicitly authorizes that exact bypass.
