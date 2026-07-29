#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  scripts/install_claude_skill.sh [--dry-run] [--force]
  scripts/install_claude_skill.sh --check

Snapshot-installs agent-tmux-control into
${CLAUDE_HOME:-~/.claude}/skills/agent-tmux-control.
EOF
}

dry_run=0
force=0
check=0
while (($# > 0)); do
    case "$1" in
        --dry-run) dry_run=1 ;;
        --force) force=1 ;;
        --check) check=1 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
    shift
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-${HOME}/.claude}"
SOURCE="${ROOT}/skills/agent-tmux-control"
SKILLS_ROOT="${CLAUDE_HOME}/skills"
TARGET="${SKILLS_ROOT}/agent-tmux-control"
STAGE="${CLAUDE_HOME}/.agent-tmux-control.new.$$"
OLD="${CLAUDE_HOME}/.agent-tmux-control.old.$$"
BACKUP_ROOT="${AGENT_TERMINAL_CONTACT_BACKUP_ROOT:-${ROOT}/backups/install}/claude/agent-tmux-control"

run() {
    if ((dry_run)); then
        printf 'dry-run:'
        printf ' %q' "$@"
        printf '\n'
    else
        "$@"
    fi
}

cleanup() {
    if [[ -n "${STAGE:-}" && -e "${STAGE}" ]]; then
        rm -rf "${STAGE}"
    fi
    if [[ -n "${OLD:-}" && -e "${OLD}" ]]; then
        rm -rf "${OLD}"
    fi
    return 0
}
trap cleanup EXIT

package_tree_has_symlink() {
    local package_dir="$1"
    [[ -d "${package_dir}" && ! -L "${package_dir}" ]] || return 0
    [[ -n "$(find "${package_dir}" -type l -print -quit)" ]]
}

package_trees_match() {
    local source_dir="$1"
    local target_dir="$2"

    [[ -d "${source_dir}" && ! -L "${source_dir}" ]] || return 1
    [[ -d "${target_dir}" && ! -L "${target_dir}" ]] || return 1
    package_tree_has_symlink "${source_dir}" && return 1
    package_tree_has_symlink "${target_dir}" && return 1
    diff -qr --no-dereference --exclude='.skill-source' "${source_dir}" "${target_dir}" >/dev/null
}

if [[ -L "${SOURCE}" || ! -d "${SOURCE}" ]]; then
    echo "install_claude_skill.sh: source package is missing, non-directory, or symlinked: ${SOURCE}" >&2
    exit 2
fi
if [[ -L "${SOURCE}/SKILL.md" || ! -f "${SOURCE}/SKILL.md" ]]; then
    echo "install_claude_skill.sh: source SKILL.md is missing, non-file, or symlinked: ${SOURCE}/SKILL.md" >&2
    exit 2
fi
bad_source_path="$(find "${SOURCE}" -type l -print -quit)"
if [[ -n "${bad_source_path}" ]]; then
    echo "install_claude_skill.sh: source package contains symlink: ${bad_source_path}" >&2
    exit 2
fi
bad_source_path="$(find "${SOURCE}" -type f \
    \( -name '*.bak' -o -name '*.old' -o -name '*.orig' -o -name '*~' \) \
    -print -quit)"
if [[ -n "${bad_source_path}" ]]; then
    echo "install_claude_skill.sh: source package contains backup artifact: ${bad_source_path}" >&2
    exit 2
fi
command -v rsync >/dev/null || {
    echo "install_claude_skill.sh: rsync is required" >&2
    exit 2
}

if [[ -e "${TARGET}" && ! -L "${TARGET}" ]] &&
    [[ "$(realpath "${TARGET}")" == "$(realpath "${SOURCE}")" ]]; then
    echo "install_claude_skill.sh: source package and install target resolve to the same directory: ${TARGET}" >&2
    exit 2
fi

if ((check)); then
    if [[ -L "${TARGET}" || ! -d "${TARGET}" ]]; then
        echo "install_claude_skill.sh: installed skill is missing or symlinked: ${TARGET}" >&2
        exit 3
    fi
    if ! package_trees_match "${SOURCE}" "${TARGET}"; then
        echo "install_claude_skill.sh: installed package differs from source: ${TARGET}" >&2
        exit 3
    fi
    if [[ "$(cat "${TARGET}/.skill-source" 2>/dev/null || true)" != "${ROOT}" ]]; then
        echo "install_claude_skill.sh: source sentinel missing or invalid: ${TARGET}/.skill-source" >&2
        exit 3
    fi
    echo "agent-tmux-control Claude install check: ok"
    echo "agent-tmux-control skill: ${TARGET}"
    exit 0
fi

run mkdir -p "${SKILLS_ROOT}"
run rm -rf "${STAGE}" "${OLD}"
run mkdir -p "${STAGE}"
run rsync -a --delete "${SOURCE}/" "${STAGE}/"
if ((dry_run)); then
    printf 'dry-run: write %q to %q\n' "${ROOT}" "${STAGE}/.skill-source"
else
    printf '%s\n' "${ROOT}" > "${STAGE}/.skill-source"
fi

target_occupied=0
target_matches=0
backup=""
if [[ -e "${TARGET}" || -L "${TARGET}" ]]; then
    target_occupied=1
    if package_trees_match "${SOURCE}" "${TARGET}" &&
        [[ "$(cat "${TARGET}/.skill-source" 2>/dev/null || true)" == "${ROOT}" ]]; then
        target_matches=1
    fi
    if ((target_matches == 0 && force == 0)); then
        echo "install_claude_skill.sh: refusing divergent target without --force: ${TARGET}" >&2
        exit 3
    fi
fi

if ((target_occupied && target_matches)); then
    run mv "${TARGET}" "${OLD}"
elif ((target_occupied)); then
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    run mkdir -p "${BACKUP_ROOT}"
    backup="${BACKUP_ROOT}/${stamp}"
    counter=1
    while [[ -e "${backup}" || -L "${backup}" ]]; do
        backup="${BACKUP_ROOT}/${stamp}-${counter}"
        counter=$((counter + 1))
    done
    run mv "${TARGET}" "${backup}"
fi

if ! run mv "${STAGE}" "${TARGET}"; then
    echo "install_claude_skill.sh: failed to activate staged package; restoring prior target" >&2
    if [[ -e "${OLD}" || -L "${OLD}" ]]; then
        mv "${OLD}" "${TARGET}"
    elif [[ -n "${backup}" && ( -e "${backup}" || -L "${backup}" ) ]]; then
        mv "${backup}" "${TARGET}"
    fi
    exit 4
fi
run rm -rf "${OLD}"

echo "agent-tmux-control Claude skill: ${TARGET}"
echo "source: ${ROOT}"
