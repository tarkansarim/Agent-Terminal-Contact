#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  scripts/install.sh [--dry-run]

Installs AgentTerminalContact without modifying Codex, Claude, tmux, or
/usr/local/bin/agent-tmux:
  - symlink ~/.local/bin/agent-contact to this repo's bin/agent-contact
  - copy skills/agent-tmux-control/SKILL.md into ${CODEX_HOME:-~/.codex}/skills/agent-tmux-control/SKILL.md

Existing installed SKILL.md is backed up before replacement.
EOF
}

dry_run=0
case "${1:-}" in
    --dry-run)
        dry_run=1
        ;;
    -h|--help)
        usage
        exit 0
        ;;
    "")
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_HOME="${CODEX_HOME:-${HOME}/.codex}"
BIN_DIR="${BIN_DIR:-${HOME}/.local/bin}"
SKILL_SOURCE="${ROOT}/skills/agent-tmux-control/SKILL.md"
SKILL_DIR="${CODEX_HOME}/skills/agent-tmux-control"
SKILL_TARGET="${SKILL_DIR}/SKILL.md"
AGENT_CONTACT_TARGET="${BIN_DIR}/agent-contact"

require_file() {
    local path="$1"
    [[ -f "${path}" ]] || {
        echo "install.sh: required file missing: ${path}" >&2
        exit 2
    }
}

run() {
    if ((dry_run)); then
        printf 'dry-run:'
        printf ' %q' "$@"
        printf '\n'
    else
        "$@"
    fi
}

require_file "${ROOT}/bin/agent-contact"
require_file "${SKILL_SOURCE}"

run mkdir -p "${BIN_DIR}"
run ln -sfn "${ROOT}/bin/agent-contact" "${AGENT_CONTACT_TARGET}"

run mkdir -p "${SKILL_DIR}"
if [[ -f "${SKILL_TARGET}" && ! -L "${SKILL_TARGET}" ]]; then
    backup="${SKILL_TARGET}.bak-$(date +%Y%m%dT%H%M%S)"
    run cp "${SKILL_TARGET}" "${backup}"
fi
run cp "${SKILL_SOURCE}" "${SKILL_TARGET}"

echo "agent-contact: ${AGENT_CONTACT_TARGET}"
echo "agent-tmux-control skill: ${SKILL_TARGET}"

