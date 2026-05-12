---
name: agent-tmux-control
description: "Use when an agent needs to launch, resume, monitor, message, capture, or coordinate another terminal-based Codex/Claude/CLI agent through a safe tmux control channel, including identifying whether a repo's active lane is Codex or Claude before launching, and finding/resuming the latest Codex chat for a repo without asking the user for the thread name. Trigger for agent-tmux, agent-contact, tmux agent sessions, communicating with another terminal Codex/Claude agent, latest Codex chat in a repo, cross-agent terminal coordination, capturing another agent's output, or replacing unsafe raw PTY injection. Do not use for ordinary one-shot shell commands."
---

# Agent Tmux Control

Source: AgentTerminalContact guarded-contact skill, version 0.1.0.

Use `agent-tmux` for launch, resume, capture, transcript, attach, and stop.
On this workstation, the `agent-tmux` command should resolve to the
AgentTerminalContact source-owned user-level wrapper at `~/.local/bin/agent-tmux`,
which delegates normal commands unchanged to the non-owned
`/usr/local/bin/agent-tmux` helper.

Use `agent-contact send` for sending messages to another live terminal agent.
Raw `agent-tmux send` is a low-level transport primitive and must not be used for
cross-agent Codex/Claude messages unless the user explicitly asks for a bypass
for that exact target.

Normal user-launched `codex` chats are not tmux-managed by default. Treat tmux as
a worker/control surface, not as the user's foreground Codex UI. If a foreground
Codex chat is outside tmux, this skill cannot safely inject into it; resume the
intended existing thread into a tmux worker only when worker contact is needed.

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
- Unexpected visible composer text in a tmux-managed agent is user-owned pending
  text. Stop and do not clear it, submit it, or send over it unless the user or
  current operator explicitly approves clearing that exact text.
- Stale contact residue created by a failed `agent-contact` attempt is not a
  message bypass. If the visible composer clearly contains old guarded-contact
  residue such as `CONTACT_ID: ... MESSAGE_JSON: ...` or Codex's collapsed
  `[Pasted Content N chars]` placeholder after `agent-contact` returned
  `mutated_unsubmitted`, and it is not a human draft, clear only that proven
  residue with `agent-tmux clear-input <session>` and rerun guarded
  `agent-contact`.
- Messages with terminal control bytes or bracketed-paste markers are refused; summarize or sanitize captured terminal output before sending it.
- The actual paste payload is one `CONTACT_ID ... MESSAGE_JSON ...` line and does not request tmux bracketed-paste wrapping.
- Real sends to attached tmux sessions are refused; detach or use a tmux-managed worker session for cross-agent contact.
- Multiple plausible same-repo sessions are an identity problem, not a routine choice.
- Include the transcript path from the contact output or `agent-tmux log <session>` when reporting cross-agent work.

## Latest Chat Routing

When the user asks to connect to, resume, contact, or spawn an agent for a repo
and does not provide an exact provider plus thread or session name, do not start
a fresh chat first.

Before spawning any tmux worker, identify whether the repo's active lane is
Codex or Claude. Do not choose the provider from the supervising agent, from
habit, or from whichever launch command is easiest. Provider identity must come
from one of these, in order:

1. The user's explicit provider instruction.
2. An existing tmux-managed owner session for that repo and provider.
3. The latest recorded provider chat for that repo, when the helper supports
   that provider.
4. A clear repo-local handoff note or ticket naming the provider.

If the signals disagree, if both providers have plausible active chats, or if no
provider can be identified, stop and ask instead of launching a guessed worker.

First inspect the latest recorded Codex thread for that repo:

```bash
agent-tmux codex-latest /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2
```

If a tmux-managed worker is needed for contact, resume that latest thread rather
than opening a new one:

```bash
agent-tmux codex-resume-latest sonicgroom /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2
```

If an existing tmux-managed Codex session already targets the repo, prefer
inspecting it before launching anything:

```bash
agent-tmux codex-existing /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2
```

If multiple matching tmux sessions exist, stop and resolve identity instead of
guessing. Only use `agent-tmux codex <session> <repo>` for a genuinely new
worker session when the user asked for a new worker or no prior repo chat
exists.

The source-owned wrapper normalizes `agent-tmux codex-existing <repo>` for
machine callers: a true no-existing-session result is `rc=1`, empty stdout, and
one stderr line beginning `agent-tmux: no Codex tmux session found for workdir:`.
Treat other non-zero shapes as ambiguous or broken helper output.

## Codex Worker Permission Profile

For tmux-launched Codex workers doing autonomous ticket, source-owned repo, or
explicit full-permission work, make the worker permission profile visible in the
launch command. Do not rely on the supervisor's current sandbox or approval
settings carrying into the worker.

Use the first-class full-permission aliases only when the user asked for it,
when the worker was relaunched with `sandbox=danger-full-access` and
`ask-for-approval=never`, or when resuming a worker that was blocked by approval
prompts under a weaker profile:

```bash
agent-tmux codex-full <session> <repo>
```

Resume a known Codex thread with the same visible profile:

```bash
agent-tmux codex-resume-full <session> <repo> <thread-name-or-id>
```

Resume the latest recorded Codex thread for a repo with the same visible
profile. After the requested tmux session preflight passes, this helper resolves
the latest thread and starts `codex ... resume <thread> [prompt]`; it does not
pass a prompt to ambiguous `resume --last` positional parsing:

```bash
agent-tmux codex-resume-latest-full <session> <repo>
```

The wrapper expands these aliases to Codex CLI flags `-s danger-full-access -a
never` in the delegated command line so later captures and process inspection
show the worker was started with `danger-full-access` and `never` approval. Do not use
`--dangerously-bypass-approvals-and-sandbox` for this workflow.
Latest-thread parsing for these aliases is fail-closed: stderr, multi-line
stdout, or anything other than the expected four tab-separated `codex-latest`
fields is refused before a worker launch.

Codex launch/resume routes through this wrapper require the requested tmux
session name to be unused. If that session already exists, the wrapper refuses
before launching so the prompt cannot be lost inside a stale pane. Older
same-repo Codex sessions do not steal these explicit launches; the wrapper tells
the delegated helper to create the requested session. The wrapper also
recognizes the legacy supervise-style shape `agent-tmux codex-resume-latest
<session> <repo> -s danger-full-access -a never [prompt]` and routes it through
the same deterministic latest-thread path.

To inspect source ownership before patching an installed helper, use:

```bash
agent-contact artifact-info agent-tmux --json
agent-contact artifact-info /usr/local/bin/agent-tmux --json
```

The first command should report the source-owned wrapper when `~/.local/bin`
precedes `/usr/local/bin` on `PATH`; the second reports the delegated system
helper as explicitly not owned by AgentTerminalContact.

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

Start a full-permission Codex worker in tmux:

```bash
agent-tmux codex-full sonicgroom /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2
```

Resume the latest recorded Codex thread for a repo:

```bash
agent-tmux codex-resume-latest sonicgroom /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2
```

Resume the latest recorded Codex thread with the explicit full-permission worker
profile:

```bash
agent-tmux codex-resume-latest-full sonicgroom /home/tarkan/Dropbox/work/MyTools/CudaGroomTool2
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
