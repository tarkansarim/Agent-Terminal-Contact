#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  scripts/install.sh [--dry-run] [--force]
  scripts/install.sh --check

Installs AgentTerminalContact without modifying Codex, Claude, tmux, or
/usr/local/bin/agent-tmux:
  - symlink ~/.local/bin/agent-contact to this repo's bin/agent-contact
  - copy skills/agent-tmux-control/SKILL.md into ${CODEX_HOME:-~/.codex}/skills/agent-tmux-control/SKILL.md

If an existing installed SKILL.md differs from the repo source, or is a symlink,
installation refuses unless --force is supplied. Forced replacement writes a
timestamped backup first and replaces the install path without following
symlinks.

--check verifies that the current user-level command and skill already match
this repo source without writing anything.
EOF
}

dry_run=0
force=0
check=0
while (($# > 0)); do
    case "$1" in
        --dry-run)
            dry_run=1
            ;;
        --force)
            force=1
            ;;
        --check)
            check=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
    shift
done

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

desired_agent_contact="${ROOT}/bin/agent-contact"
if ((check)); then
    if [[ ! -L "${AGENT_CONTACT_TARGET}" ]]; then
        echo "install.sh: agent-contact is not installed as a symlink: ${AGENT_CONTACT_TARGET}" >&2
        exit 3
    fi
    if [[ "$(readlink "${AGENT_CONTACT_TARGET}")" != "${desired_agent_contact}" ]]; then
        echo "install.sh: agent-contact points somewhere else: ${AGENT_CONTACT_TARGET}" >&2
        exit 3
    fi
    resolved_agent_contact="$(command -v agent-contact || true)"
    if [[ -z "${resolved_agent_contact}" ]]; then
        echo "install.sh: agent-contact is not discoverable on PATH" >&2
        echo "install.sh: add ${BIN_DIR} to PATH before relying on the installed skill" >&2
        exit 3
    fi
    if [[ "${resolved_agent_contact}" != "${AGENT_CONTACT_TARGET}" ]]; then
        echo "install.sh: PATH resolves agent-contact to a different command: ${resolved_agent_contact}" >&2
        exit 3
    fi
    if [[ -L "${SKILL_DIR}" ]]; then
        echo "install.sh: installed skill directory is a symlink: ${SKILL_DIR}" >&2
        exit 3
    fi
    if [[ -L "${SKILL_TARGET}" || ! -f "${SKILL_TARGET}" ]]; then
        echo "install.sh: installed skill is missing, non-file, or symlinked: ${SKILL_TARGET}" >&2
        exit 3
    fi
    if ! cmp -s "${SKILL_SOURCE}" "${SKILL_TARGET}"; then
        echo "install.sh: installed skill differs from repo source: ${SKILL_TARGET}" >&2
        echo "install.sh: compare with: diff -u ${SKILL_TARGET} ${SKILL_SOURCE}" >&2
        exit 3
    fi
    echo "agent-contact install check: ok"
    echo "agent-contact: ${AGENT_CONTACT_TARGET}"
    echo "agent-tmux-control skill: ${SKILL_TARGET}"
    exit 0
fi

if [[ -e "${AGENT_CONTACT_TARGET}" || -L "${AGENT_CONTACT_TARGET}" ]]; then
    current_agent_contact=""
    if [[ -L "${AGENT_CONTACT_TARGET}" ]]; then
        current_agent_contact="$(readlink "${AGENT_CONTACT_TARGET}")"
    fi
    if [[ "${current_agent_contact}" != "${desired_agent_contact}" ]]; then
        if ((force == 0)); then
            echo "install.sh: refusing to overwrite divergent agent-contact target without --force: ${AGENT_CONTACT_TARGET}" >&2
            exit 3
        fi
    fi
fi

skill_target_occupied=0
skill_target_divergent=0
skill_target_symlink=0
skill_dir_symlink=0
if [[ -L "${SKILL_DIR}" ]]; then
    skill_dir_symlink=1
    if ((force == 0)); then
        echo "install.sh: refusing to write through symlinked skill directory without --force: ${SKILL_DIR}" >&2
        exit 3
    fi
fi
if [[ -e "${SKILL_TARGET}" || -L "${SKILL_TARGET}" ]]; then
    skill_target_occupied=1
    if [[ -L "${SKILL_TARGET}" ]]; then
        skill_target_symlink=1
        skill_target_divergent=1
    elif [[ ! -f "${SKILL_TARGET}" ]] || ! cmp -s "${SKILL_SOURCE}" "${SKILL_TARGET}"; then
        skill_target_divergent=1
    fi
fi

if ((skill_target_divergent)); then
    if ((force == 0)); then
        if ((skill_target_symlink)); then
            echo "install.sh: refusing to overwrite symlinked installed skill without --force: ${SKILL_TARGET}" >&2
        else
            echo "install.sh: refusing to overwrite divergent installed skill without --force: ${SKILL_TARGET}" >&2
            echo "install.sh: compare with: diff -u ${SKILL_TARGET} ${SKILL_SOURCE}" >&2
        fi
        exit 3
    fi
fi

run mkdir -p "${BIN_DIR}"
if [[ -e "${AGENT_CONTACT_TARGET}" || -L "${AGENT_CONTACT_TARGET}" ]]; then
    current_agent_contact=""
    if [[ -L "${AGENT_CONTACT_TARGET}" ]]; then
        current_agent_contact="$(readlink "${AGENT_CONTACT_TARGET}")"
    fi
    agent_contact_divergent=0
    if [[ "${current_agent_contact}" != "${desired_agent_contact}" ]]; then
        agent_contact_divergent=1
    fi
fi
if [[ "${agent_contact_divergent:-0}" == "1" && "${force}" == "1" ]]; then
    backup="${AGENT_CONTACT_TARGET}.bak-$(date +%Y%m%dT%H%M%S)"
    run cp -P "${AGENT_CONTACT_TARGET}" "${backup}"
    echo "backup: ${backup}"
fi
run ln -sfn "${ROOT}/bin/agent-contact" "${AGENT_CONTACT_TARGET}"

if ((skill_dir_symlink && force)); then
    backup="${SKILL_DIR}.bak-$(date +%Y%m%dT%H%M%S)"
    run cp -P "${SKILL_DIR}" "${backup}"
    echo "backup: ${backup}"
    run rm -f "${SKILL_DIR}"
    skill_target_occupied=0
    skill_target_divergent=0
    skill_target_symlink=0
fi
run mkdir -p "${SKILL_DIR}"
if ((skill_target_occupied && skill_target_divergent && force)); then
    backup="${SKILL_TARGET}.bak-$(date +%Y%m%dT%H%M%S)"
    run cp -P "${SKILL_TARGET}" "${backup}"
    echo "backup: ${backup}"
    run rm -f "${SKILL_TARGET}"
fi
run cp "${SKILL_SOURCE}" "${SKILL_TARGET}"

echo "agent-contact: ${AGENT_CONTACT_TARGET}"
echo "agent-tmux-control skill: ${SKILL_TARGET}"
