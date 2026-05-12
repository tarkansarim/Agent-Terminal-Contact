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
refuse `--dangerously-bypass-approvals-and-sandbox`. The latest-resume alias
resolves the latest thread first, then launches `codex ... resume <thread>
[prompt]` so a prompt is not misread as the resume session id.
