---
name: agent-tmux-control
description: "Use when an agent needs to launch, resume, monitor, message, capture, or coordinate another terminal-based Codex/Claude/CLI agent through a safe tmux control channel, including finding or resuming the latest Codex chat for a repo without asking the user for the thread name. Trigger for agent-tmux, agent-contact, tmux agent sessions, communicating with another terminal Codex/Claude agent, latest Codex chat in a repo, cross-agent terminal coordination, capturing another agent's output, or replacing unsafe raw PTY injection. Do not use for ordinary one-shot shell commands."
---

# Agent Tmux Control

Source: AgentTerminalContact guarded-contact skill, version 0.1.0.

Use `agent-tmux` for launch, resume, capture, transcript, attach, and stop.

Use `agent-contact send` for sending messages to another live terminal agent.
Raw `agent-tmux send` is a low-level transport primitive and must not be used for
cross-agent Codex/Claude messages unless the user explicitly asks for a bypass
for that exact target.

`agent-contact` verifies provider package identity against explicitly trusted
exact package roots only. Set `AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS` to the
narrow provider package root printed by `agent-contact trust-roots`, and set
`AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS` to the launcher root for bare Node-style
launches, before contacting local Codex/Claude processes. Do not guess broad
roots. Launcher roots are exact executable directories, not broad parent
directories. `trust-roots` only prints roots when the live pane package is
anchored by the provider command found on your current `PATH`.

## Hard Safety Rules

- Never inject keystrokes into a raw PTY such as `/dev/pts/*` unless the user explicitly authorizes that exact terminal.
- Existing non-tmux agents cannot be safely contacted through this skill. Report that they are outside the guarded channel.
- Before sending to another Codex/Claude chat, run `agent-contact send --dry-run` or use `agent-contact send` directly.
- If `agent-contact` refuses, stop. Do not fall back to raw `agent-tmux send`.
- Unexpected visible composer text in a tmux-managed agent is stale session
  state to clear, not a message to submit. If a target composer contains text
  that the current operator did not intentionally put there or ask to preserve,
  run `agent-tmux clear-input <session>`, capture or dry-run again, and only
  continue through guarded `agent-contact` after the prompt is idle. Stop
  instead only when the text is known to be a human draft or the user asked to
  preserve it.
- Stale contact residue created by a failed `agent-contact` attempt is not a
  message bypass. If the visible composer clearly contains old guarded-contact
  residue such as `CONTACT_ID: ... MESSAGE_JSON: ...` or Codex's collapsed
  `[Pasted Content N chars]` placeholder after `agent-contact` returned
  `mutated_unsubmitted`, clear it with `agent-tmux clear-input <session>` and
  rerun guarded `agent-contact`.
- Messages with terminal control bytes or bracketed-paste markers are refused; summarize or sanitize captured terminal output before sending it.
- The actual paste payload is one `CONTACT_ID ... MESSAGE_JSON ...` line and does not request tmux bracketed-paste wrapping.
- Real sends to attached tmux sessions are refused; detach or use a tmux-managed worker session for cross-agent contact.
- Multiple plausible same-repo sessions are an identity problem, not a routine choice.
- Include the transcript path from the contact output or `agent-tmux log <session>` when reporting cross-agent work.

## Contact Workflow

Dry-run first when the target state matters:

```bash
agent-contact send \
  --repo /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2 \
  --provider codex \
  --message "Please brief me on the active issue." \
  --dry-run
```

If discovery reports no matching provider pane because no roots are trusted,
ask `agent-contact` to inspect the live pane and print narrow roots:

```bash
agent-contact trust-roots \
  --repo /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2 \
  --provider codex \
  --json
```

Then rerun with those explicit roots:

```bash
AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS=/home/tarkan/.nvm/versions/node/v22.22.0/lib/node_modules/@openai/codex \
AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS=/home/tarkan/.nvm/versions/node/v22.22.0/bin \
  agent-contact send \
    --repo /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2 \
    --provider codex \
    --message "Please brief me on the active issue." \
    --dry-run
```

If the dry-run reports `status: would_send`, run the same command without
`--dry-run`:

```bash
agent-contact send \
  --repo /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2 \
  --provider codex \
  --message "Please brief me on the active issue."
```

Use `--session <tmux-session>` only when the user named the intended session or
you have independently verified the exact session identity.

Expected refusal states:

- `multiple tmux-managed ... sessions found`: stop and resolve identity
- `pending_user_text`: stop; do not send over the user's visible draft
- `approval_prompt` or `trust_prompt`: stop; the target needs local handling
- `agent_working`: wait, capture later, or ask the user
- `dead_or_unknown`: stop; there is no safe idle prompt

## Launch And Observe

Start a Codex agent in tmux:

```bash
agent-tmux codex sonicgroom /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2
```

Resume the latest recorded Codex thread for a repo:

```bash
agent-tmux codex-resume-latest sonicgroom /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2
```

Find an existing tmux-managed Codex session for a repo:

```bash
agent-tmux codex-existing /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2
```

Capture and inspect:

```bash
agent-tmux capture sonicgroom 160
agent-tmux log sonicgroom
agent-tmux tail sonicgroom 160
```

Attach manually:

```bash
agent-tmux attach sonicgroom
```

Stop only a session you intentionally started or the user explicitly named:

```bash
agent-tmux stop sonicgroom
```

## Reporting

When cross-agent contact is attempted, report:

- target repo and provider
- selected tmux session or refusal reason
- pane state from `agent-contact`
- transcript path
- whether delivery was proven, unproven, or refused
