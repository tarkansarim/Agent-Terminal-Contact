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
  - symlink ~/.local/bin/agent-tmux to this repo's bin/agent-tmux wrapper
  - symlink ~/.local/bin/agent-vanilla to this repo's bin/agent-vanilla
  - snapshot the control skill into both Codex and Claude user skill roots

If an existing installed SKILL.md differs from the repo source, or is a symlink,
installation refuses unless --force is supplied. Forced replacement writes a
timestamped backup under this repo's ignored backups/install/ tree first and
replaces the install path without following symlinks.

--check verifies that the current user-level command and skill already match
this repo source without writing anything, and refuses backup/temp artifacts
left under the live Codex skill load root.
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
CLAUDE_HOME="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}"
BIN_DIR="${BIN_DIR:-${HOME}/.local/bin}"
SKILL_SOURCE="${ROOT}/skills/agent-tmux-control/SKILL.md"
SKILLS_ROOT="${CODEX_HOME}/skills"
SKILL_DIR="${SKILLS_ROOT}/agent-tmux-control"
SKILL_TARGET="${SKILL_DIR}/SKILL.md"
CLAUDE_SKILLS_ROOT="${CLAUDE_HOME}/skills"
CLAUDE_SKILL_DIR="${CLAUDE_SKILLS_ROOT}/agent-tmux-control"
CLAUDE_SKILL_TARGET="${CLAUDE_SKILL_DIR}/SKILL.md"
BACKUP_ROOT="${AGENT_TERMINAL_CONTACT_BACKUP_ROOT:-${ROOT}/backups/install}"
SKILL_BACKUP_DIR="${BACKUP_ROOT}/codex/agent-tmux-control"
CLAUDE_SKILL_BACKUP_DIR="${BACKUP_ROOT}/claude/agent-tmux-control"
LEGACY_SKILL_BACKUP_DIR="${CODEX_HOME}/agent-terminal-contact/backups/agent-tmux-control"
LEGACY_BACKUP_ROOT="${CODEX_HOME}/agent-terminal-contact/backups"
LEGACY_STATE_ROOT="${CODEX_HOME}/agent-terminal-contact"
AGENT_CONTACT_TARGET="${BIN_DIR}/agent-contact"
AGENT_TMUX_TARGET="${BIN_DIR}/agent-tmux"
AGENT_VANILLA_TARGET="${BIN_DIR}/agent-vanilla"

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

unique_skill_backup_path() {
    local base="$1"
    local candidate="${SKILL_BACKUP_DIR}/${base}"
    local stamp
    local counter

    if [[ ! -e "${candidate}" && ! -L "${candidate}" ]]; then
        printf "%s\n" "${candidate}"
        return
    fi

    stamp="$(date +%Y%m%dT%H%M%S)"
    counter=0
    while :; do
        candidate="${SKILL_BACKUP_DIR}/${base}.${stamp}.${counter}"
        if [[ ! -e "${candidate}" && ! -L "${candidate}" ]]; then
            printf "%s\n" "${candidate}"
            return
        fi
        counter=$((counter + 1))
    done
}

backup_skill_artifact() {
    local source_path="$1"
    local base="$2"
    local backup

    run mkdir -p "${SKILL_BACKUP_DIR}"
    backup="$(unique_skill_backup_path "${base}")"
    run cp -P "${source_path}" "${backup}"
    echo "backup: ${backup}"
}

skill_load_artifacts() {
    if [[ -d "${SKILLS_ROOT}" && ! -L "${SKILLS_ROOT}" ]]; then
        find "${SKILLS_ROOT}" -mindepth 1 -maxdepth 1 \
            \( -name 'agent-tmux-control.bak' -o -name 'agent-tmux-control.bak-*' \) \
            -print
    fi
    if [[ -d "${SKILL_DIR}" && ! -L "${SKILL_DIR}" ]]; then
        find "${SKILL_DIR}" -mindepth 1 -maxdepth 1 \
            \( -name '*.bak' -o -name '*.bak-*' -o -name '*.tmp' -o -name '*.tmp-*' \
            -o -name '*.orig' -o -name '*.rej' -o -name '*~' \) \
            -print
    fi
}

emit_skill_load_artifact_errors() {
    local artifacts=()
    local artifact

    mapfile -t artifacts < <(skill_load_artifacts)
    if ((${#artifacts[@]} == 0)); then
        return 0
    fi

    for artifact in "${artifacts[@]}"; do
        echo "install.sh: backup/temp artifact under Codex skill load root: ${artifact}" >&2
    done
    return 1
}

relocate_skill_load_artifacts() {
    local artifacts=()
    local artifact
    local backup

    mapfile -t artifacts < <(skill_load_artifacts)
    if ((${#artifacts[@]} == 0)); then
        return 0
    fi

    run mkdir -p "${SKILL_BACKUP_DIR}"
    for artifact in "${artifacts[@]}"; do
        backup="$(unique_skill_backup_path "$(basename "${artifact}")")"
        run mv "${artifact}" "${backup}"
        echo "relocated skill-load artifact: ${artifact} -> ${backup}"
    done
}

legacy_provider_root_backups() {
    if [[ -d "${LEGACY_SKILL_BACKUP_DIR}" && ! -L "${LEGACY_SKILL_BACKUP_DIR}" ]]; then
        find "${LEGACY_SKILL_BACKUP_DIR}" -mindepth 1 -maxdepth 1 -print
    elif [[ -e "${LEGACY_SKILL_BACKUP_DIR}" || -L "${LEGACY_SKILL_BACKUP_DIR}" ]]; then
        printf "%s\n" "${LEGACY_SKILL_BACKUP_DIR}"
    fi
}

emit_legacy_provider_root_backup_errors() {
    local artifacts=()
    local artifact

    mapfile -t artifacts < <(legacy_provider_root_backups)
    if ((${#artifacts[@]} == 0)); then
        return 0
    fi

    for artifact in "${artifacts[@]}"; do
        echo "install.sh: legacy backup artifact under Codex provider root: ${artifact}" >&2
    done
    return 1
}

relocate_legacy_provider_root_backups() {
    local artifacts=()
    local artifact
    local backup

    mapfile -t artifacts < <(legacy_provider_root_backups)
    if ((${#artifacts[@]} > 0)); then
        run mkdir -p "${SKILL_BACKUP_DIR}"
        for artifact in "${artifacts[@]}"; do
            backup="$(unique_skill_backup_path "$(basename "${artifact}")")"
            run mv "${artifact}" "${backup}"
            echo "relocated legacy provider-root backup: ${artifact} -> ${backup}"
        done
    fi
    run rmdir "${LEGACY_SKILL_BACKUP_DIR}" 2>/dev/null || true
    run rmdir "${LEGACY_BACKUP_ROOT}" 2>/dev/null || true
    run rmdir "${LEGACY_STATE_ROOT}" 2>/dev/null || true
}

require_file "${ROOT}/bin/agent-contact"
require_file "${ROOT}/bin/agent-tmux"
require_file "${ROOT}/bin/agent-vanilla"
require_file "${SKILL_SOURCE}"
require_file "${ROOT}/artifact_ownership.json"

desired_agent_contact="${ROOT}/bin/agent-contact"
desired_agent_tmux="${ROOT}/bin/agent-tmux"
desired_agent_vanilla="${ROOT}/bin/agent-vanilla"
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
    if [[ ! -L "${AGENT_TMUX_TARGET}" ]]; then
        echo "install.sh: agent-tmux wrapper is not installed as a symlink: ${AGENT_TMUX_TARGET}" >&2
        exit 3
    fi
    if [[ "$(readlink "${AGENT_TMUX_TARGET}")" != "${desired_agent_tmux}" ]]; then
        echo "install.sh: agent-tmux wrapper points somewhere else: ${AGENT_TMUX_TARGET}" >&2
        exit 3
    fi
    resolved_agent_tmux="$(command -v agent-tmux || true)"
    if [[ -z "${resolved_agent_tmux}" ]]; then
        echo "install.sh: agent-tmux is not discoverable on PATH" >&2
        echo "install.sh: add ${BIN_DIR} to PATH before relying on the installed wrapper" >&2
        exit 3
    fi
    if [[ "${resolved_agent_tmux}" != "${AGENT_TMUX_TARGET}" ]]; then
        echo "install.sh: PATH resolves agent-tmux to a different command: ${resolved_agent_tmux}" >&2
        exit 3
    fi
    if [[ ! -L "${AGENT_VANILLA_TARGET}" ]] || [[ "$(readlink "${AGENT_VANILLA_TARGET}" 2>/dev/null)" != "${desired_agent_vanilla}" ]]; then
        echo "install.sh: agent-vanilla is missing or points somewhere else: ${AGENT_VANILLA_TARGET}" >&2
        exit 3
    fi
    resolved_agent_vanilla="$(command -v agent-vanilla || true)"
    if [[ "${resolved_agent_vanilla}" != "${AGENT_VANILLA_TARGET}" ]]; then
        echo "install.sh: PATH does not resolve agent-vanilla to ${AGENT_VANILLA_TARGET}" >&2
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
    if [[ -L "${CLAUDE_SKILL_DIR}" || -L "${CLAUDE_SKILL_TARGET}" || ! -f "${CLAUDE_SKILL_TARGET}" ]]; then
        echo "install.sh: Claude skill is missing, non-file, or symlinked: ${CLAUDE_SKILL_TARGET}" >&2
        exit 3
    fi
    if ! cmp -s "${SKILL_SOURCE}" "${CLAUDE_SKILL_TARGET}"; then
        echo "install.sh: installed Claude skill differs from repo source: ${CLAUDE_SKILL_TARGET}" >&2
        exit 3
    fi
    if ! emit_skill_load_artifact_errors; then
        exit 3
    fi
    if ! emit_legacy_provider_root_backup_errors; then
        exit 3
    fi
    echo "agent-contact install check: ok"
    echo "agent-contact: ${AGENT_CONTACT_TARGET}"
    echo "agent-tmux wrapper: ${AGENT_TMUX_TARGET}"
    echo "agent-vanilla: ${AGENT_VANILLA_TARGET}"
    echo "Codex agent-tmux-control skill: ${SKILL_TARGET}"
    echo "Claude agent-tmux-control skill: ${CLAUDE_SKILL_TARGET}"
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
if [[ -e "${AGENT_TMUX_TARGET}" || -L "${AGENT_TMUX_TARGET}" ]]; then
    current_agent_tmux=""
    if [[ -L "${AGENT_TMUX_TARGET}" ]]; then
        current_agent_tmux="$(readlink "${AGENT_TMUX_TARGET}")"
    fi
    if [[ "${current_agent_tmux}" != "${desired_agent_tmux}" ]]; then
        if ((force == 0)); then
            echo "install.sh: refusing to overwrite divergent agent-tmux wrapper target without --force: ${AGENT_TMUX_TARGET}" >&2
            exit 3
        fi
    fi
fi
if [[ -e "${AGENT_VANILLA_TARGET}" || -L "${AGENT_VANILLA_TARGET}" ]]; then
    current_agent_vanilla=""
    if [[ -L "${AGENT_VANILLA_TARGET}" ]]; then
        current_agent_vanilla="$(readlink "${AGENT_VANILLA_TARGET}")"
    fi
    if [[ "${current_agent_vanilla}" != "${desired_agent_vanilla}" && "${force}" == "0" ]]; then
        echo "install.sh: refusing to overwrite divergent agent-vanilla target without --force: ${AGENT_VANILLA_TARGET}" >&2
        exit 3
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

claude_skill_divergent=0
if [[ -L "${CLAUDE_SKILL_DIR}" || -L "${CLAUDE_SKILL_TARGET}" ]]; then
    claude_skill_divergent=1
elif [[ -e "${CLAUDE_SKILL_TARGET}" ]] && { [[ ! -f "${CLAUDE_SKILL_TARGET}" ]] || ! cmp -s "${SKILL_SOURCE}" "${CLAUDE_SKILL_TARGET}"; }; then
    claude_skill_divergent=1
fi
if ((claude_skill_divergent && force == 0)); then
    echo "install.sh: refusing to overwrite divergent or symlinked Claude skill without --force: ${CLAUDE_SKILL_TARGET}" >&2
    exit 3
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

if [[ -e "${AGENT_TMUX_TARGET}" || -L "${AGENT_TMUX_TARGET}" ]]; then
    current_agent_tmux=""
    if [[ -L "${AGENT_TMUX_TARGET}" ]]; then
        current_agent_tmux="$(readlink "${AGENT_TMUX_TARGET}")"
    fi
    agent_tmux_divergent=0
    if [[ "${current_agent_tmux}" != "${desired_agent_tmux}" ]]; then
        agent_tmux_divergent=1
    fi
fi
if [[ "${agent_tmux_divergent:-0}" == "1" && "${force}" == "1" ]]; then
    backup="${AGENT_TMUX_TARGET}.bak-$(date +%Y%m%dT%H%M%S)"
    run cp -P "${AGENT_TMUX_TARGET}" "${backup}"
    echo "backup: ${backup}"
fi
run ln -sfn "${ROOT}/bin/agent-tmux" "${AGENT_TMUX_TARGET}"

if [[ -e "${AGENT_VANILLA_TARGET}" || -L "${AGENT_VANILLA_TARGET}" ]]; then
    current_agent_vanilla=""
    if [[ -L "${AGENT_VANILLA_TARGET}" ]]; then
        current_agent_vanilla="$(readlink "${AGENT_VANILLA_TARGET}")"
    fi
    if [[ "${current_agent_vanilla}" != "${desired_agent_vanilla}" && "${force}" == "1" ]]; then
        backup="${AGENT_VANILLA_TARGET}.bak-$(date +%Y%m%dT%H%M%S)"
        run cp -P "${AGENT_VANILLA_TARGET}" "${backup}"
        echo "backup: ${backup}"
    fi
fi
run ln -sfn "${ROOT}/bin/agent-vanilla" "${AGENT_VANILLA_TARGET}"

if ((skill_dir_symlink && force)); then
    backup_skill_artifact "${SKILL_DIR}" "agent-tmux-control.bak-$(date +%Y%m%dT%H%M%S)"
    run rm -f "${SKILL_DIR}"
    skill_target_occupied=0
    skill_target_divergent=0
    skill_target_symlink=0
fi
run mkdir -p "${SKILL_DIR}"
if ((skill_target_occupied && skill_target_divergent && force)); then
    backup_skill_artifact "${SKILL_TARGET}" "SKILL.md.bak-$(date +%Y%m%dT%H%M%S)"
    run rm -f "${SKILL_TARGET}"
fi
relocate_skill_load_artifacts
relocate_legacy_provider_root_backups
run cp "${SKILL_SOURCE}" "${SKILL_TARGET}.new"
run mv "${SKILL_TARGET}.new" "${SKILL_TARGET}"

if ((claude_skill_divergent && force)); then
    run mkdir -p "${CLAUDE_SKILL_BACKUP_DIR}"
    backup="${CLAUDE_SKILL_BACKUP_DIR}/SKILL.md.bak-$(date +%Y%m%dT%H%M%S)"
    if [[ -L "${CLAUDE_SKILL_DIR}" ]]; then
        backup="${CLAUDE_SKILL_BACKUP_DIR}/agent-tmux-control.bak-$(date +%Y%m%dT%H%M%S)"
        run cp -P "${CLAUDE_SKILL_DIR}" "${backup}"
        run rm -f "${CLAUDE_SKILL_DIR}"
    elif [[ -e "${CLAUDE_SKILL_TARGET}" || -L "${CLAUDE_SKILL_TARGET}" ]]; then
        run cp -P "${CLAUDE_SKILL_TARGET}" "${backup}"
        run rm -f "${CLAUDE_SKILL_TARGET}"
    fi
    echo "backup: ${backup}"
fi
run mkdir -p "${CLAUDE_SKILL_DIR}"
run cp "${SKILL_SOURCE}" "${CLAUDE_SKILL_TARGET}.new"
run mv "${CLAUDE_SKILL_TARGET}.new" "${CLAUDE_SKILL_TARGET}"

echo "agent-contact: ${AGENT_CONTACT_TARGET}"
echo "agent-tmux wrapper: ${AGENT_TMUX_TARGET}"
echo "agent-vanilla: ${AGENT_VANILLA_TARGET}"
echo "Codex agent-tmux-control skill: ${SKILL_TARGET}"
echo "Claude agent-tmux-control skill: ${CLAUDE_SKILL_TARGET}"
