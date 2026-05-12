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
- the pane still has the same cwd, process command, pid, provider evidence, and idle prompt state immediately before send
- the target pane is at an idle empty prompt proven by provider text plus tmux cursor metadata
- no pending user text is visible
- the message payload contains no bracketed-paste markers or terminal control characters except newline and tab
- the pasted payload is a single line containing a generated `CONTACT_ID` and `MESSAGE_JSON`, without tmux bracketed-paste wrapping
- the post-send capture gives delivery evidence, or the result is reported as unproven after mutation
- installed AgentTerminalContact artifacts can be resolved through a source
  manifest that reports installed path, source path, install/check commands,
  ownership, and source-match status in JSON
- the source-owned `~/.local/bin/agent-tmux` wrapper delegates normal commands
  unchanged to `/usr/local/bin/agent-tmux` and adds explicit full-permission
  Codex aliases using `-s danger-full-access -a never`

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
- the selected pane changes cwd, process command, pid, or provider evidence before send
- a real send targets a tmux session currently attached to a client
- the message contains a bracketed-paste marker or C0/C1 control character other than newline or tab
- the target pane shows pending user text
- the target pane shows a trust or approval prompt
- the target pane is working, dead, or unknown
- a full-permission `agent-tmux` alias is asked to pass
  `--dangerously-bypass-approvals-and-sandbox`

## Non-Goals

V0 does not patch Codex, Claude, or tmux internals. It does not contact
non-tmux live terminals. It does not patch `/usr/local/bin/agent-tmux`; the
source-owned user wrapper delegates to that explicitly non-owned helper.
