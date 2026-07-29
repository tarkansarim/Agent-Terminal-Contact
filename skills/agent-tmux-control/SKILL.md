---
name: agent-tmux-control
description: "Tmux-managed Codex/Claude/CLI agents via agent-tmux/agent-contact: launch, resume, monitor, capture, repo agent routing, latest Codex chat, provider mismatch, guarded contact, unsafe raw PTY."
---

<!-- thin-relay:v1 -->
# Agent Tmux Control Router

Load this skill when its frontmatter description matches the task.

## Always

- Read `modules/core.md` before taking skill-specific action.
- Keep detailed procedure, examples, and edge cases in modules, not this relay.
- Load only the module needed for the current task.

## Route

| Task | Module |
| --- | --- |
| Any task matched by this skill description | `modules/core.md` |

## Hard Limits

- Do not act from this relay alone when the routed module is available.
- Do not create another discoverable `SKILL.md` inside this package.
