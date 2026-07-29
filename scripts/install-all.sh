#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"${SCRIPT_DIR}/install.sh" "$@"
"${SCRIPT_DIR}/install_claude_skill.sh" "$@"
