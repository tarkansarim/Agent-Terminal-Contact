---
name: agent-tmux-control
description: "Tmux-managed Codex/Claude/CLI agents via agent-tmux/agent-contact: launch, resume, monitor, capture, repo agent routing, latest Codex chat, provider mismatch, guarded contact, unsafe raw PTY."
---

# Agent Tmux Control

Source: AgentTerminalContact guarded-contact skill, version 0.1.0.

## Discovery And Routing Scope

Use this skill when an agent needs to launch, resume, monitor, message, capture,
or coordinate another terminal-based Codex, Claude, or CLI agent through a safe
tmux control channel. Trigger phrases include `agent-tmux`, `agent-contact`,
tmux agent sessions, contacting or communicating with another terminal
Codex/Claude repo agent, finding or resuming the latest Codex chat in a repo,
cross-agent terminal coordination, capturing another agent's output, provider
mismatch refusals, guarded contact recovery, and replacing unsafe raw PTY
injection. Do not use this skill for ordinary one-shot shell commands.

Use `agent-tmux` for launch, resume, capture, transcript, attach, and stop.
On this workstation, the `agent-tmux` command should resolve to the
AgentTerminalContact source-owned user-level wrapper at `~/.local/bin/agent-tmux`,
which delegates normal commands unchanged to the non-owned
`/usr/local/bin/agent-tmux` helper.

The source-owned wrapper owns launch-time logging for `start`, `codex`,
`codex-resume`, `codex-resume-latest`, full-permission aliases, code-map
sidecars, and explicit `pipe-log`. Logs live under
`${AGENT_TMUX_LOG_DIR:-${XDG_STATE_HOME:-~/.local/state}/agent-tmux}` and are
capped by default at `AGENT_TMUX_LOG_MAX_BYTES=50M` with
`AGENT_TMUX_LOG_KEEP_PARTS=3` rotated parts. Use `agent-tmux logs status` before
long-running supervision to see total footprint. Use
`agent-tmux logs prune --older-than 14d --max-size 50M` to reclaim closed or
oversized agent-tmux logs; it must not touch `~/.codex/sessions/` or
`~/.codex/archived_sessions/`.

Use `agent-contact send` for sending messages to another live terminal agent.
Raw `agent-tmux send` is a low-level transport primitive and must not be used for
cross-agent Codex/Claude messages unless the user explicitly asks for a bypass
for that exact target.

Normal user-launched `codex` chats are not tmux-managed by default. Treat tmux as
a worker/control surface, not as the user's foreground Codex UI. If a foreground
Codex chat is outside tmux, this skill cannot safely inject into it; resume the
intended existing thread into a tmux worker only when worker contact is needed.

`agent-contact` verifies provider identity against narrow roots: Codex/Node
package roots, Claude/Node package roots, or the exact native Claude version
binary. Normal sends automatically trust a live provider pane only when that
provider root is anchored by the provider command found on the current `PATH`
or by the matching npm global package root. Manual
`AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS` and
`AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS` remain supported as an override for
unusual installs, but do not ask the user to export them for normal side shells.
Do not guess broad roots. Launcher roots are exact executable directories, not
broad parent directories. `trust-roots` prints the discovered roots for
debugging.

## Supervisor Delegation Gate

When acting as a supervisor over a live tmux worker, every implementation change must
pass the following gate before the supervisor edits source directly.

### Objective Gate — Direct Edit Allowed Only When ALL Hold

- At most 2 files changed.
- At most ~40 lines changed.
- No new files created.
- No build-system, shader, or pipeline file changes.
- Verification is a cheap existing test — not a full build cycle or OSTM run.

If any condition fails, route the change to the live worker. Do not apply supervisor
judgment to override the gate — the gate is objective precisely because judgment always
prefers the cheaper (direct) path.

### Delegation Default

When a healthy worker is already spawned, delegation is the default behavior.
A direct edit must emit a one-line auditable justification in the supervisor reply:

```
Direct edit: 1 file / 12 lines / clamp-only
```

No justification line = violation. A supervisor reply containing a source edit
with no justification line is out-of-policy.

### Minimal Supervisor Nudges

When a supervisor contacts a live worker to correct behavior, use the smallest
natural-language nudge that names the observed problem and asks the worker to
apply repo/user rules. Do not send long implementation plans, root-cause guesses,
file lists, validation recipes, or step-by-step fixes unless the worker is
blocked and explicitly asks for that detail. The goal is to test and preserve
the worker's rule-following behavior; over-detailed supervisor prompts can mask
bad rules, confuse ownership, and turn supervision into micro-management.

### Anti-Drift Tripwire

After 3 consecutive direct edits within a supervised slice, the next change **must**
go to the worker, or the supervisor must explicitly declare the worker dead or stuck
and relaunch. Three consecutive direct edits without a worker turn is the circuit
breaker — the tripwire resets whenever a change is routed to the worker.

### Closeout Audit

Slice closeout must report direct-edit count vs. worker-task count for the slice.
All-direct with a live worker is a flagged violation that must be resolved before
the slice is accepted.

### Delegation Via Task File

Use `agent-contact delegate` to brief a worker from a task file instead of a long
inline paste. This is the recommended path when the task brief is longer than a
short nudge:

```bash
agent-contact delegate \
  --repo /path/to/repo \
  --provider codex \
  --task-file /path/to/task.md \
  [--session <tmux-session>] \
  [--dry-run]
```

The task file contains the full delegation brief. `delegate` reads it, prepends a
`DELEGATE: <filename>` header, and sends it through the same guarded contact path
as `send`. Use `--dry-run` to preview without sending.

Note: reliable delivery of long task files depends on PLANE-233 (paste/submit
friction). For short nudges, `agent-contact send --message "..."` is sufficient.

## Hard Safety Rules

- Never inject keystrokes into a raw PTY such as `/dev/pts/*` unless the user explicitly authorizes that exact terminal.
- Existing non-tmux agents cannot be safely contacted through this skill. Report that they are outside the guarded channel.
- Before sending to another Codex/Claude chat, run `agent-contact send --dry-run` or use `agent-contact send` directly.
- If `agent-contact` refuses, stop. Do not fall back to raw `agent-tmux send`.
- If `agent-contact` returns `mutated_unsubmitted`, delivery failed. When the
  failed send leaves its current guarded `CONTACT_ID` payload or Codex
  collapsed pasted-content placeholder in the composer, it clears that owned
  residue, retries once through the same guarded gates, and reports
  `recovery: cleared_own_guarded_payload` plus `send_attempts: 2` on success.
  If guarded recovery cannot prove a safe retry or the retry also fails, rerun
  guarded contact instead of using raw tmux input.
- If post-send readback finds the same guarded payload still pending in the
  composer, `agent-contact` clears that owned residue and reports
  `mutated_unsubmitted`, not `sent_unproven`.
  When pre-submit proof already succeeded and no Codex plan-mode confirmation
  prompt is visible, it first tries one additional guarded Enter against that
  tool-owned pending payload; if delivery is then proven, the result is `sent`
  with `post_send_resubmit: true`.
  In that result, `pane_state`/`pane_reason` describe the contaminated
  pending-composer state that caused the failure; `recovered_pane_state` and
  `recovered_pane_reason` describe the state after the non-submitting clear
  attempt.
- If that failed result includes
  `unsupported_prompt: codex_plan_mode_confirmation`, Codex held the long
  guarded payload behind its plan-mode confirmation prompt. The owned residue
  was cleared, but delivery failed; use the returned recovery guidance and do
  not use raw tmux input.
- If `agent-contact` returns `sent_unproven`, inspect
  `delivery_proof_reason`, `post_send_guarded_contact_visible`, and
  `pre_submit_contact_proven`, and `post_send_state`; do not treat it as
  delivered unless the current operator explicitly accepts that ambiguity.
- A successful guarded send can report `delivery_proven: true` even when
  `post_send_guarded_contact_visible` is false, but only when
  `pre_submit_contact_proven: true` and the post-send state is `agent_working`.
  That means the same send proved the guarded payload in the composer
  immediately before submit, then observed the worker actively processing after
  submit.
- In a validated, detached tmux-managed worker session, visible composer text is
  a control surface. Use guarded `agent-contact send`; do not manually clear,
  submit, or send raw tmux input. `--dry-run` reports `would_clear_and_send`
  plus `agent-tmux clear-input <session>` when composer text is visible, and a
  real send clears the composer before sending a fresh guarded payload.
- The clear-before-send path covers Codex starter placeholder text, stale
  `CONTACT_ID`/`MESSAGE_JSON` residue, Codex pasted-content placeholders,
  wrapped/truncated residue, and arbitrary leftover worker composer text.
- Long Codex guarded sends can show `[Pasted Content 1024 chars]` before
  submit. When the guarded line is at least 1024 characters, that threshold
  placeholder is accepted as the just-pasted guarded payload; smaller
  wrong-count placeholders still fail closed.
  Long Codex guarded payloads use tmux bracketed paste so Codex can submit the
  pasted-content payload normally instead of retaining an unsubmitted collapsed
  placeholder after Enter.
- After an unproven long Codex send, `[Pasted Content 1024 chars]` followed by
  visible leftover payload text is treated as owned residue from that
  just-attempted send and is cleared before returning `mutated_unsubmitted`;
  do not treat that suffix form as pre-submit proof.
- This does not weaken refusal boundaries: attached sessions, trust prompts,
  approval prompts, dead/unknown panes, ambiguous identity, wrong-provider
  matches, and non-tmux targets still refuse. Busy/working panes refuse by
  default; a supervisor may use
  `agent-contact send --session <exact-worker> --interrupt-working ...` only for
  a detached tmux-managed worker session that needs intervention. The guarded
  interrupt sends `Escape`, waits for a sendable prompt, then uses the normal
  guarded send path; if the worker stays busy or lands in a non-sendable state,
  it refuses instead of sending blind input.
- Messages with terminal control bytes or bracketed-paste markers are refused; summarize or sanitize captured terminal output before sending it.
- The guarded contact payload is one `CONTACT_ID ... MESSAGE_JSON ...` line and does not request tmux bracketed-paste wrapping; Codex starter-placeholder prompts are handled by literal key input inside `agent-contact`.
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
For ticket supervision or other cross-repo owner routing, do not rely on a
default Codex launch. Pass the proven provider explicitly to the supervisor or
launcher. If the route has no proven provider and the user did not specify one,
fail closed before launch/contact.

First inspect the latest recorded Codex thread for that repo:

```bash
agent-tmux codex-latest /path/to/repo
```

If a tmux-managed worker is needed for contact, resume that latest thread rather
than opening a new one:

```bash
agent-tmux codex-resume-latest example-session /path/to/repo
```

If an existing tmux-managed Codex session already targets the repo, prefer
inspecting it before launching anything:

```bash
agent-tmux codex-existing /path/to/repo
```

If multiple matching tmux sessions exist, stop and resolve identity instead of
guessing. Only use `agent-tmux codex <session> <repo>` for a genuinely new
worker session when the user asked for a new worker or no prior repo chat
exists.

The source-owned wrapper normalizes `agent-tmux codex-existing <repo>` for
machine callers: a true no-existing-session result is `rc=1`, empty stdout, and
one stderr line beginning `agent-tmux: no Codex tmux session found for workdir:`.
Before that lookup, the wrapper runs a conservative stale-owner cleanup pass:
detached `owner-*` Codex sessions older than
`${AGENT_TMUX_IDLE_OWNER_GC_AGE:-30m}` are killed only when their pane still
shows the Codex starter template prompt. Set
`AGENT_TMUX_AUTO_GC_IDLE_OWNERS=0` to disable this automatic pass, or inspect it
manually with:

```bash
agent-tmux gc-idle-owners --dry-run --older-than 30m
agent-tmux gc-idle-owners --kill --older-than 30m
```

When an exact preferred session is supplied with
`agent-tmux codex-existing <repo> <session>`, the wrapper source-inspects that
exact tmux session name; exact absence, wrong-repo, or not-Codex-like evidence
must not collapse into a delegated multiple-session refusal.
Treat other non-zero shapes as ambiguous or broken helper output.

For a Claude-owned repo, launch or select a Claude tmux lane explicitly and
prove that exact session with `agent-contact` before sending ticket work:

```bash
agent-tmux start owner-example-claude /path/to/claude-owned-repo claude --permission-mode bypassPermissions --name owner-example-claude

agent-contact trust-roots \
  --repo /path/to/claude-owned-repo \
  --provider claude \
  --session owner-example-claude \
  --json

AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS="$HOME/.local/share/claude/versions/X.Y.Z" \
  agent-contact send \
    --repo /path/to/claude-owned-repo \
    --provider claude \
    --session owner-example-claude \
    --message "Please triage the assigned ticket." \
    --dry-run
```

If `agent-contact trust-roots` or `agent-contact send --dry-run` refuses, stop
and fix the guarded provider/contact path instead of switching to a Codex worker
or raw tmux input.

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

Resume the latest recorded Codex session for a repo with the same visible
profile. After the requested tmux session preflight passes, this helper resolves
the latest session id through the source-owned `codex-latest` path and starts
`codex ... resume <session-id> [prompt]`; it does not pass a prompt to ambiguous
`resume --last` positional parsing:

```bash
agent-tmux codex-resume-latest-full <session> <repo>
```

The wrapper expands these aliases to Codex CLI flags `-s danger-full-access -a
never` in the delegated command line so later captures and process inspection
show the worker was started with `danger-full-access` and `never` approval. Do not use
`--dangerously-bypass-approvals-and-sandbox` for this workflow, and do not pass
`-s`/`--sandbox` or `-a`/`--ask-for-approval` yourself; the full aliases already
provide those flags and reject duplicate caller-supplied permission options
before launch.
Latest-session parsing for these aliases is fail-closed. `codex-latest` first
reads the current Codex thread database at `${CODEX_HOME:-~/.codex}/state_5.sqlite`
and falls back to legacy `${CODEX_HOME:-~/.codex}/session_index.jsonl` only when
the database has no matching repo thread. A session qualifies only when the
matching rollout/session file has exact resolved `cwd` or function-call
`workdir` evidence for the repo. A matching `title` or legacy `thread_name` is
never enough when the recorded session `cwd` belongs to a different repo;
same-name stale chats must be skipped in favor of a cwd-matching session or fail
closed before a worker launch. Missing metadata, duplicate newest candidates,
and ambiguous session-file matches fail closed before a worker launch.

Codex launch/resume routes through this wrapper require the requested tmux
session name to be unused. If that session already exists, the wrapper refuses
before launching so the prompt cannot be lost inside a stale pane. Older
same-repo Codex sessions do not steal these explicit launches; the wrapper tells
the delegated helper to create the requested session. The wrapper also
recognizes the legacy supervise-style shape `agent-tmux codex-resume-latest
<session> <repo> -s danger-full-access -a never [prompt]` and routes it through
the same deterministic latest-session-id path.

Before wrapper-launched Codex workers (`codex`, `codex-full`, `codex-resume`,
`codex-resume-full`, `codex-resume-latest`, and
`codex-resume-latest-full`), the wrapper verifies that the reachable tmux server
through `tmux -S <expected-socket>` is the expected persistent socket
`${AGENT_TMUX_EXPECTED_SOCKET:-/tmp/tmux-$(id -u)/default}` and already has
sessions. If no server is reachable, the server is empty, `$TMUX` points at a
different socket, or listed sessions report a different socket, it refuses before
`tmux new-session` because the worker may be launched into a sandbox-local server
that disappears when the call ends.

The same persistent-socket preflight applies to wrapper-owned code-map sidecar
launches before their `tmux new-session` call.

The same launch preflight verifies an exact trusted
`[projects."<absolute repo path>"]` entry in `${CODEX_HOME:-~/.codex}/config.toml`.
If that trust entry is missing, it refuses before `tmux new-session` and prints
the exact TOML block to add or asks the operator to run Codex once in that
project and approve the trust prompt. A launch that would stop at Codex's
project trust screen must not report `started`.

After `tmux new-session`, the wrapper checks that the provider pane is still
live before reporting `started`. If Codex exits during launch, the wrapper
fails loudly and includes captured provider stderr when available.

## Code-Map Sidecar Workers

Use the source-owned wrapper for a code-map patch-artifact sidecar when a
supervisor needs a short-lived Codex worker to inspect source and produce
reviewable map-update artifacts without touching production files:

```bash
agent-tmux codex-code-map-sidecar <repo> <anchor> [focus prompt...]
```

For a Rewind/Codex fork anchor, pass the session id from the generated
`codex fork <session-id>` command instead of pasting that command into an
existing pane:

```bash
agent-tmux codex-code-map-sidecar-fork <repo> <anchor> <codex-session-id> [focus prompt...]
```

The sidecar session name is deterministic from the resolved repo root and
anchor. If that session already exists, the wrapper refuses; change the anchor
to launch a new sidecar. Do not use or overwrite old same-repo tmux sessions.
The sidecar route does not select a live owner lane, does not send to an
existing pane, and does not bypass `agent-contact` for follow-up messages.

The wrapper launches Codex from an isolated artifact directory with a visible
workspace-write permission profile, disabled network access for model-run shell
commands, and wrapper-owned `CODEX_HOME` deny-read for model-run shell
commands. Before launch, it writes an exact trusted-project entry for that
generated artifact directory into the wrapper-owned sidecar `CODEX_HOME`, so the
sidecar does not stop at Codex's directory trust prompt and no user-level
Codex config is mutated. It injects a map-only prompt. The prompt gives the repo
root as a read-only input path and the artifact directory as the only writable map-output
path.
The sidecar may write
artifacts such as `MAP_REPORT.md`, `PROPOSED_CHANGES.patch`, or proposed
map/project-memory file contents under the artifact directory. Applyable
patch/file artifacts may target only
`.project-memory/code-map-state.json`, `.project-memory/project-memory-state.json`,
bounded `.project-memory/` policy namespaces
(`code-map/`, `project-memory/`, `routing/`, `indexes/`, `subsystems/`) with
`.md`, `.json`, or `.jsonl` files, `docs/CODEBASE_ARCHITECTURE_INDEX.md`,
`docs/CODEBASE_SUBSYSTEM_MANIFEST.json`, direct Markdown files under
`docs/SUBSYSTEMS/` (`docs/SUBSYSTEMS/*.md`), `CODE_MAP.md`, `PROJECT_MEMORY.md`,
`docs/CODE_MAP.md`, or `docs/PROJECT_MEMORY.md`. Runtime/credential/key/token
path components such as `codex-home`, `.codex`, `session_index.jsonl`,
`credential`, `secret`, `token`, `password`, `private-key`, `access-key`,
`ssh-key`, or `api-key` are rejected even inside the allowed namespaces;
ordinary Codex/auth/session map topics are allowed when they do not look like
runtime files or credential material. `MAP_REPORT.md` alone is the report-only
lane; otherwise an artifact must contain a proposed map update. The
sidecar must not write terminal control bytes, bracketed-paste markers, OSC
sequences, or other non-text terminal payloads into map artifacts. The sidecar
must not edit production source, tests, config, install scripts, user-level
files, or generated artifacts in place; do not run `apply_patch`, commit,
install, roll out, dispatch tickets, contact other agents, or mutate tmux
sessions. The supervisor applies accepted map edits later through the normal
source workflow, with validation and commit evidence. The final
deterministic artifact directory must not already exist or be a symlink; the
wrapper creates it atomically and refuses paths that resolve inside the
repository root.

The Codex process runs under `bwrap`: there is no host `/` bind, host home is
hidden except for trusted Codex/Node executable paths, `/usr/local/bin` is
hidden, selected host inspection tools are bound by exact file plus their
library dependencies instead of broad `/usr/bin` or `/usr/lib` binds, `/dev` is
a private bwrap device filesystem, `/dev/shm` is overlaid read-only, the
artifact directory is the writable map-output bind, and `/tmp` and `/run` are
private so tmux sockets are not exposed. Codex
`HOME`/`CODEX_HOME` live under a separate wrapper-owned runtime directory next
to the artifact directory. In fork mode, the wrapper copies the requested Codex
session file plus the matching `session_index.jsonl` entry when present into the
wrapper-owned `CODEX_HOME` before launch. Codex auth/session files are
wrapper-managed runtime inputs; the sidecar's permission profile deny-reads
wrapper-owned `CODEX_HOME` from model-run shell commands and disables shell
network access. Auth/session material must not be copied into sidecar artifacts.
The wrapper refuses artifact and runtime roots that resolve inside the
repository root.

Before applying sidecar output, validate the artifact directory:

```bash
agent-tmux codex-code-map-validate-artifacts <artifact-dir>
```

The validator requires the wrapper-written sidecar registry stored as a sibling
of the artifact directory, outside the sidecar-writable tree, and checks it
against the artifact-local `SIDECAR_REQUEST.txt` audit copy. The registry binds
the session, repo, anchor, allowed output directory, sandbox permission,
filesystem-isolation description, and validator command. Those fields must
match the wrapper schema exactly; unknown or partial audit manifests are
rejected. The wrapper cleanup owner marker is also stored beside that registry,
outside the sidecar-writable artifact and runtime directories. It rejects
`PROPOSED_CHANGES.patch` and `PROPOSED_FILES/` entries that target non-map paths,
and rejects symlink or non-regular proposed artifact entries, including patch
modes that would create symlinks or other non-regular files. It also rejects
unsupported patch path header formats, symlink or non-regular entries anywhere
in the sidecar artifact tree, binary or terminal-control content in
supervisor-consumed artifacts, and direct Codex auth material or obvious
auth/session key structures or raw transcript-style JSONL records in
supervisor-consumed artifacts. Runtime-looking paths such as
`.agent-tmux-runtime/` inside the artifact directory are rejected; wrapper-owned
runtime state lives outside the artifact tree. The artifact directory passed to
the validator must itself be a real directory, not a symlink, and must not
resolve inside the registry repo. Treat rejected artifacts as out of sidecar
scope.

The wrapper prints the sidecar session, artifact directory, wrapper-owned
runtime directory, sidecar registry path, and log path before launch. Capture
them for audit:

```bash
agent-tmux log <sidecar-session>
agent-tmux transcript <sidecar-session> all
ls <artifact-dir>
```

If a follow-up message is needed after launch, target only the known sidecar
session and dry-run guarded contact first. For wrapper-launched sidecars,
`agent-contact` accepts the original repository root when an exact session is
provided and validates both the sidecar registry outside the writable artifact
tree and the artifact-local `SIDECAR_REQUEST.txt` binding before selecting the
pane:

```bash
agent-contact send --repo <repo> --provider codex --session <sidecar-session> --message "..." --dry-run
```

If `agent-contact` returns `mutated_unsubmitted`, treat delivery as failed. When
the failed send leaves its current guarded `CONTACT_ID` payload or Codex
collapsed pasted-content placeholder in the composer, it clears that owned
residue, retries once through the same guarded gates, and reports
`recovery: cleared_own_guarded_payload` plus `send_attempts: 2` on success. If
guarded recovery cannot prove a safe retry or the retry also fails, rerun
guarded contact instead of switching to raw tmux input. For a validated, detached tmux-managed worker
session, visible composer text is a control
surface: `--dry-run` reports `would_clear_and_send` plus
`agent-tmux clear-input <sidecar-session>`, and a real send clears the composer
before sending a fresh guarded payload. This includes starter placeholder text,
stale `CONTACT_ID`/`MESSAGE_JSON` residue, Codex pasted-content placeholders,
wrapped/truncated residue, and arbitrary leftover worker composer text.

Long Codex guarded sends can show `[Pasted Content 1024 chars]` before submit.
When the guarded line is at least 1024 characters, that threshold placeholder is
accepted as the just-pasted guarded payload; smaller wrong-count placeholders
still fail closed.
Long Codex guarded payloads use tmux bracketed paste so Codex can submit the
pasted-content payload normally instead of retaining an unsubmitted collapsed
placeholder after Enter.
If post-send readback finds the same guarded payload still pending in the
composer, `agent-contact` clears that owned residue and reports
`mutated_unsubmitted`, not `sent_unproven`.
When pre-submit proof already succeeded and no Codex plan-mode confirmation
prompt is visible, it first tries one additional guarded Enter against that
tool-owned pending payload; if delivery is then proven, the result is `sent`
with `post_send_resubmit: true`.
In that result, `pane_state`/`pane_reason` describe the contaminated
pending-composer state that caused the failure; `recovered_pane_state` and
`recovered_pane_reason` describe the state after the non-submitting clear
attempt.
If that failed result includes
`unsupported_prompt: codex_plan_mode_confirmation`, Codex held the long guarded
payload behind its plan-mode confirmation prompt. The owned residue was cleared,
but delivery failed; use the returned recovery guidance and do not use raw tmux
input.
For long Codex payloads, this cleanup also covers `[Pasted Content 1024 chars]`
followed by visible leftover payload text from the same just-attempted send; the
suffix form is cleanup evidence, not pre-submit proof.

Attached sessions, trust prompts, approval prompts, dead/unknown panes,
ambiguous identity, and wrong-provider matches still refuse. Busy/working panes
refuse unless the supervisor uses
`agent-contact send --session <exact-worker> --interrupt-working ...`; that path
sends `Escape`, waits for a sendable prompt, then sends through guarded contact.
Do not fall back to raw `agent-tmux send` unless the current operator explicitly
authorizes that exact bypass.

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
  --repo /path/to/repo \
  --provider codex \
  --message "Please brief me on the active issue." \
  --dry-run
```

If discovery reports no matching provider pane, ask `agent-contact` to inspect
the live pane and print narrow roots:

```bash
agent-contact trust-roots \
  --repo /path/to/repo \
  --provider codex \
  --json
```

For unusual installs only, rerun with explicit override roots:

```bash
AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS="$HOME/.nvm/versions/node/vX.Y.Z/lib/node_modules/@openai/codex" \
AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS="$HOME/.nvm/versions/node/vX.Y.Z/bin" \
  agent-contact send \
    --repo /path/to/repo \
    --provider codex \
    --message "Please brief me on the active issue." \
    --dry-run
```

If the dry-run reports `status: would_send`, run the same command without
`--dry-run`:

```bash
agent-contact send \
  --repo /path/to/repo \
  --provider codex \
  --message "Please brief me on the active issue."
```

Use `--session <tmux-session>` only when the user named the intended session or
you have independently verified the exact session identity.

Expected refusal states:

- `multiple tmux-managed ... sessions found`: stop and resolve identity
- `pending_user_text`: detached tmux-managed workers are cleared by
  `agent-contact`; if it is reported as a refusal, stop and inspect the reason
- `approval_prompt` or `trust_prompt`: stop; the target needs local handling
- `agent_working`: wait/capture later, or for supervisor intervention use
  `--session <exact-worker> --interrupt-working`; if that refuses, stop and
  inspect the refusal
- `dead_or_unknown`: stop; there is no safe idle prompt

## Launch And Observe

Start a Codex agent in tmux:

```bash
agent-tmux codex example-session /path/to/repo
```

Start a full-permission Codex worker in tmux:

```bash
agent-tmux codex-full example-session /path/to/repo
```

Resume the latest recorded Codex session for a repo:

```bash
agent-tmux codex-resume-latest example-session /path/to/repo
```

Resume the latest recorded Codex session with the explicit full-permission worker
profile:

```bash
agent-tmux codex-resume-latest-full example-session /path/to/repo
```

Find an existing tmux-managed Codex session for a repo:

```bash
agent-tmux codex-existing /path/to/repo
```

List stale detached owner Codex starter sessions without killing them:

```bash
agent-tmux gc-idle-owners --dry-run --older-than 30m
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
