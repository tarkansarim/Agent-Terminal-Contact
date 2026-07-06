# Active Slice Watchlist

This file is agent-maintained. It lists what the supervising or direct agent must keep
watching during each implementation slice: constraints, risks, gates, donor facts, user
rules, verification expectations, and rejection conditions that must survive compaction and
worker handoffs.

## Active

1. **code-map sidecar may produce readable but validator-rejected PROPOSED_CHANGES.patch artifacts containing terminal control bytes after restricted-shell artifact writes; do not apply such artifacts as trusted sidecar output.**
   - Status: `active`
   - Slice: `code-map-sidecar-artifact-validation`
   - Scope: `project`
   - Source: CudaGroomTool2 code-map sidecar closeout 2026-07-06
   - Revisit when: before changing or relying on agent-tmux codex-code-map-sidecar artifact generation or validation
   - Gate: Reproduce or regression-test agent-tmux codex-code-map-validate-artifacts on a sidecar PROPOSED_CHANGES.patch created from minimal shell/builtin redirection; accepted fix must either prevent terminal-control bytes in artifacts or surface a cleaner worker-facing write route before reporting map sidecar output as applyable.
   - Evidence: none recorded
   - Recorded: `2026-07-06T11:16:31Z`


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

4. **codex-full must reject/de-duplicate caller sandbox and approval flags, prove provider stays live before printing started, document built-in full-permission behavior, and validate the exact duplicate-flag repro.**
   - Status: `historical`
   - Slice: `PLANE-169 codex-full launch hardening`
   - Scope: `project`
   - Source: Plane ticket PLANE-169
   - Revisit when: before source edits, verification, and closeout
   - Gate: source changes plus verification command showing duplicate flags fail clearly and failed launches surface stderr instead of false started
   - Evidence: Gate checked during closeout; see focused codex-full contract tests, direct duplicate-flag repro, and broad sandbox-safe suite results recorded on PLANE-169.
   - Recorded: `2026-06-02T04:12:57Z`

5. **codex-full launch hardening gate satisfied: duplicate full-permission flags are rejected before launch, fast provider exits fail without started and surface captured output, and docs state codex-full is already full-permission.**
   - Status: `historical`
   - Slice: `PLANE-169 codex-full launch hardening`
   - Scope: `project`
   - Source: PLANE-169 implementation closeout
   - Revisit when: historical closeout record
   - Gate: bash -n passed; focused codex-full contract tests passed; exact duplicate-flag repro rc=2 with clear wrapper error; broad suite passed with only unrelated real-tmux sandbox-blocked codex-existing tests deselected
   - Evidence: PLANE-169 check statuses recorded: bash syntax, focused codex-full contracts, exact duplicate-flag repro, broad sandbox-safe suite.
   - Recorded: `2026-06-02T04:19:23Z`
