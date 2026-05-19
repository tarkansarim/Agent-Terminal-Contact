# Active Slice Watchlist

This file is agent-maintained. It lists what the supervising or direct agent must keep
watching during each implementation slice: constraints, risks, gates, donor facts, user
rules, verification expectations, and rejection conditions that must survive compaction and
worker handoffs.

## Active

- No active entries.

## Superseded Or Historical

1. **Work from AgentTerminalContact source only; do not edit installed ~/.codex skill artifacts directly.**
   - Status: `historical`
   - Slice: `tickets-101-102-source-closeout`
   - Scope: `reusable-skill`
   - Source: user ticket closeout instruction
   - Revisit when: before any skill/install artifact mutation
   - Gate: Changed source paths and rollout/install evidence must be commented on ticket before close
   - Evidence: Used AgentTerminalContact source commands only; installed artifacts were inspected with source-owned install check and artifact-info.
   - Recorded: `2026-05-19T01:13:31Z`

2. **Validate exact requested behaviors: installed skill backup artifacts are not left under ~/.codex/skills and guarded-contact residue from mutated_unsubmitted is deterministically recovered or refused safely.**
   - Status: `historical`
   - Slice: `tickets-101-102-source-closeout`
   - Scope: `project`
   - Source: ticket #101/#102 bodies
   - Revisit when: before closeout claim
   - Gate: Run validation commands and comment results on tickets; strict closeout-check passes before close
   - Evidence: Focused unittest suite ran 8 tests OK; full unittest discovery ran 296 tests OK; compileall OK; install check OK; backup-artifact find output empty.
   - Recorded: `2026-05-19T01:13:31Z`

3. **If source or installed artifacts change, report source HEAD/commit and install or rollout/sync evidence on the ticket before agent-ticket close.**
   - Status: `historical`
   - Slice: `tickets-101-102-source-closeout`
   - Scope: `project`
   - Source: user closeout gate
   - Revisit when: before agent-ticket close 101 or 102
   - Gate: agent-ticket closeout-check <id> --strict reports no blockers
   - Evidence: Current source HEAD and install/source-match evidence are ticket-commented before close; no source product changes or installed artifact rollout were needed in this pass.
   - Recorded: `2026-05-19T01:13:31Z`
