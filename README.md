# Agent Terminal Contact

Start here by asking your coding agent to install and run this for you. This
tool is meant to be driven by an agent from the beginning, not hand-wired one
command at a time.

Agent Terminal Contact is a guarded contact tool for tmux-managed Codex and
Claude workers. It gives a coding agent a safer way to find the right worker
pane, prove which repo and provider it belongs to, dry-run a message, send a
guarded payload, and report whether delivery was proven or refused.

It does not replace Codex, Claude, tmux, or the system `agent-tmux` helper. This
repo owns `agent-contact` plus a user-level `agent-tmux` wrapper. The wrapper
delegates normal commands to `/usr/local/bin/agent-tmux` and adds checked routes
for Codex launches, latest-chat resume, log handling, artifact ownership lookup,
and code-map sidecar sessions.

## What It Does

- Finds exactly one tmux-managed Codex or Claude pane for the requested repo and
  provider.
- Locks contact to a specific tmux pane id and rechecks the pane before sending.
- Refuses to send if the target is busy, attached, ambiguous, at a trust prompt,
  at an approval prompt, or otherwise unsafe.
- Sends a guarded one-line payload and checks that it was submitted.
- Cleans up its own failed guarded payload when it can prove the text belongs to
  the failed send.
- Installs a source-owned `agent-tmux` wrapper for safer launch, resume,
  logging, latest-chat lookup, and full-permission Codex worker shortcuts.
- Checks Codex project trust before launch so the wrapper does not report a
  worker as started when Codex would stop at a trust screen.
- Reports installed artifact ownership so an agent can tell whether an installed
  command or skill comes from this repo.
- Provides code-map sidecar workers that write reviewable artifacts without
  editing production files directly.

## Quick Use

Dry-run first:

```bash
agent-contact send \
  --repo /path/to/repo \
  --provider codex \
  --message "Please report current status." \
  --dry-run
```

If the dry-run says it would send, run the same command without `--dry-run`:

```bash
agent-contact send \
  --repo /path/to/repo \
  --provider codex \
  --message "Please report current status."
```

Use `--session <tmux-session>` when you already know the exact tmux session.

## Install On Linux Or WSL

From this repo:

```bash
bash scripts/install.sh --force
bash scripts/install.sh --check
```

This installs:

- `~/.local/bin/agent-contact`
- `~/.local/bin/agent-tmux`
- `${CODEX_HOME:-~/.codex}/skills/agent-tmux-control/SKILL.md`

The installed `agent-tmux` is a wrapper owned by this repo. Normal commands are
passed through to `/usr/local/bin/agent-tmux`. The wrapper only takes over the
commands this repo needs to harden.

## Install On Windows

From PowerShell:

```powershell
pwsh scripts/install.ps1 -Force
pwsh scripts/install.ps1 -Check
```

This installs:

- `agent-contact.ps1`
- `agent-contact.cmd`
- the Codex skill snapshot

The Bash/tmux `agent-tmux` wrapper is for Linux or WSL. The Windows installer
only installs the `agent-contact` shims and skill snapshot.

## Trust Roots

Provider checks are strict. If `agent-contact` cannot prove that a pane is
running the requested provider, it refuses.

Ask it to print the exact roots to trust:

```bash
agent-contact trust-roots --repo /path/to/repo --provider codex --json
```

Then export the printed roots and retry the send:

```bash
AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS="$HOME/.nvm/versions/node/vX.Y.Z/lib/node_modules/@openai/codex" \
AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS="$HOME/.nvm/versions/node/vX.Y.Z/bin" \
  agent-contact send \
    --repo /path/to/repo \
    --provider codex \
    --message "Please report current status." \
    --dry-run
```

Use the narrow paths printed by `trust-roots`. Do not trust a broad parent
folder.

## Codex Worker Shortcuts

The installed `agent-tmux` wrapper adds these Codex launch helpers:

```bash
agent-tmux codex-full <session> <repo> [codex-args...]
agent-tmux codex-resume-full <session> <repo> <thread-name-or-id> [prompt]
agent-tmux codex-resume-latest-full <session> <repo> [prompt]
```

They launch Codex with:

```bash
-s danger-full-access -a never
```

Before launching, the wrapper checks two things:

- the requested tmux session name is not already in use
- Codex already trusts the exact repo path in
  `${CODEX_HOME:-~/.codex}/config.toml`

If the trust entry is missing, the wrapper refuses before starting tmux and
prints the TOML block to add.

## Code-Map Sidecars

For short-lived code-map review work:

```bash
agent-tmux codex-code-map-sidecar /path/to/repo <anchor> "Focus prompt"
agent-tmux codex-code-map-sidecar-fork /path/to/repo <anchor> <codex-session-id> "Focus prompt"
```

Sidecars write only to a generated artifact directory. They should not edit the
source repo directly.

Validate sidecar output before using it:

```bash
agent-tmux codex-code-map-validate-artifacts <artifact-dir>
```

## Artifact Ownership

Use this before editing an installed command or skill:

```bash
agent-contact artifact-info agent-contact --json
agent-contact artifact-info agent-tmux --json
agent-contact artifact-info /usr/local/bin/agent-tmux --json
agent-contact artifact-info --all --json
```

This tells you whether the installed thing is owned by this repo or belongs
somewhere else.

This repo owns:

- `~/.local/bin/agent-contact`
- `~/.local/bin/agent-tmux`
- `${CODEX_HOME:-~/.codex}/skills/agent-tmux-control/SKILL.md`
- Windows `agent-contact.ps1` and `agent-contact.cmd` shims

This repo does not own `/usr/local/bin/agent-tmux`.

## Development

Create a local env:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
```

Run checks:

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall src tests
bash -n bin/agent-tmux scripts/install.sh bin/agent-contact
git diff --check
```

## Notes

- Real sends to attached tmux sessions are refused.
- Ambiguous matching sessions are refused.
- Messages with terminal control bytes are refused.
- If a send is reported as `sent_unproven`, treat it as uncertain and inspect
  the returned reason.
- If a send is reported as `mutated_unsubmitted`, delivery failed. Retry through
  `agent-contact`; do not switch to raw tmux input.
