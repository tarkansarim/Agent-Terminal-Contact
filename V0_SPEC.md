# AgentTerminalContact V0 Spec

## Contract

`agent-contact send` wraps `agent-tmux send` with a fail-closed contact check.

V0 must prove:

- target repo and provider resolve to exactly one tmux-managed session
- the target pane is at an idle empty prompt
- no pending user text is visible
- the sent message contains a generated `CONTACT_ID`
- the post-send capture gives delivery evidence, or the result is reported as
  unproven

## Refusals

The command refuses before sending when:

- no matching tmux session exists
- more than one matching session exists
- an explicit session does not match the requested repo/provider
- the target pane shows pending user text
- the target pane shows a trust or approval prompt
- the target pane is working, dead, or unknown

## Non-Goals

V0 does not patch Codex, Claude, or tmux internals. It does not contact
non-tmux live terminals. It does not update installed skills until this source
tool is tested.

