"""Pane-state classification for terminal agent contact."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


ANSI_RE = re.compile(
    r"\x1b\][^\a]*(?:\a|\x1b\\)|"
    r"\x1b\[[0-9;?]*[ -/]*[@-~]|"
    r"\x1b[()#][0-9A-Za-z]"
)


class PaneState(str, Enum):
    IDLE_EMPTY_PROMPT = "idle_empty_prompt"
    PENDING_USER_TEXT = "pending_user_text"
    AGENT_WORKING = "agent_working"
    APPROVAL_PROMPT = "approval_prompt"
    TRUST_PROMPT = "trust_prompt"
    DEAD_OR_UNKNOWN = "dead_or_unknown"


@dataclass(frozen=True)
class Classification:
    state: PaneState
    reason: str


@dataclass(frozen=True)
class PromptMatch:
    body: str
    line_index: int
    line: str


def strip_terminal_control(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\r", "\n")


def classify_pane(
    text: str,
    *,
    provider: str | None = None,
    cursor_line_index: int | None = None,
    cursor_column_index: int | None = None,
) -> Classification:
    visible = strip_terminal_control(text or "")
    lowered = visible.lower()

    if not visible.strip():
        return Classification(PaneState.DEAD_OR_UNKNOWN, "capture was empty")

    if _looks_like_trust_prompt(lowered):
        return Classification(PaneState.TRUST_PROMPT, "directory trust prompt is visible")

    if _looks_like_approval_prompt(lowered):
        return Classification(PaneState.APPROVAL_PROMPT, "approval prompt is visible")

    if _looks_like_working_state(visible):
        return Classification(PaneState.AGENT_WORKING, "agent appears to be working")

    prompt = _safe_prompt(visible, provider=provider, cursor_line_index=cursor_line_index)
    if prompt is not None:
        if not _prompt_body_is_empty(prompt.body):
            if _is_codex_starter_placeholder(
                prompt,
                provider=provider,
                cursor_column_index=cursor_column_index,
            ) and _has_provider_prompt_context(
                visible,
                prompt,
                provider=provider,
                cursor_line_index=cursor_line_index,
            ):
                return Classification(PaneState.IDLE_EMPTY_PROMPT, "codex starter placeholder has no pending user text")
            return Classification(PaneState.PENDING_USER_TEXT, "prompt contains pending user text")
        if not _has_provider_prompt_context(visible, prompt, provider=provider, cursor_line_index=cursor_line_index):
            return Classification(PaneState.DEAD_OR_UNKNOWN, "bare prompt marker lacks provider TUI context")
        return Classification(PaneState.IDLE_EMPTY_PROMPT, "idle prompt has no pending text")

    return Classification(PaneState.DEAD_OR_UNKNOWN, "no safe idle prompt was detected")


def current_prompt_body(
    text: str,
    *,
    provider: str | None,
    cursor_line_index: int | None,
    cursor_column_index: int | None = None,
) -> str | None:
    visible = strip_terminal_control(text or "")
    prompt = _safe_prompt(visible, provider=provider, cursor_line_index=cursor_line_index)
    if prompt is None:
        return None
    if not _has_provider_prompt_context(visible, prompt, provider=provider, cursor_line_index=cursor_line_index):
        return None
    return _strip_prompt_cursor(prompt.body)


def _is_codex_starter_placeholder(
    prompt: PromptMatch,
    *,
    provider: str | None,
    cursor_column_index: int | None,
) -> bool:
    if provider != "codex" or cursor_column_index is None:
        return False
    if _strip_prompt_cursor(prompt.body).strip() != "Find and fix a bug in @filename":
        return False
    return cursor_column_index <= _prompt_body_start_column(prompt.line, provider=provider)


def _looks_like_trust_prompt(lowered: str) -> bool:
    return (
        "do you trust the contents of this directory" in lowered
        or ("trusting the directory" in lowered and "press enter to continue" in lowered)
    )


def _looks_like_approval_prompt(lowered: str) -> bool:
    approval_markers = (
        "do you want to allow",
        "allow command",
        "approve command",
        "approval required",
        "requires approval",
        "press enter to approve",
    )
    return any(marker in lowered for marker in approval_markers)


def _looks_like_working_state(text: str) -> bool:
    lines = [line.strip().lower() for line in text.splitlines() if line.strip()]
    for line in lines[-12:]:
        if _is_provider_footer(line, provider="codex") or _is_provider_footer(line, provider="claude"):
            continue
        line = _strip_status_prefix(line)
        if re.match(r"^(working|thinking|running|executing|applying patch|waiting for)\b", line):
            return True
        if " tokens" in line and ("used" in line or "remaining" in line):
            return True
    return False


def _safe_prompt(text: str, *, provider: str | None, cursor_line_index: int | None) -> PromptMatch | None:
    if cursor_line_index is not None:
        return _prompt_near_cursor(text, provider=provider, cursor_line_index=cursor_line_index)
    return _last_prompt(text, provider=provider)


def _prompt_near_cursor(text: str, *, provider: str | None, cursor_line_index: int) -> PromptMatch | None:
    lines = text.splitlines()
    if cursor_line_index < 0 or cursor_line_index >= len(lines):
        return None

    for index in range(cursor_line_index, -1, -1):
        stripped = lines[index].strip()
        if not stripped:
            continue
        if _is_provider_footer(stripped, provider=provider):
            return None
        body = _prompt_body(stripped, provider=provider)
        if body is not None:
            return _prompt_from_index(lines, index, body, provider=provider, allow_previous_prompts=True)
    return None


def _last_prompt(text: str, *, provider: str | None) -> PromptMatch | None:
    lines = text.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        stripped = lines[index].strip()
        if not stripped:
            continue
        body = _prompt_body(stripped, provider=provider)
        if body is not None:
            return _prompt_from_index(lines, index, body, provider=provider, allow_previous_prompts=False)
    return None


def _prompt_from_index(
    lines: list[str],
    index: int,
    body: str,
    *,
    provider: str | None,
    allow_previous_prompts: bool,
) -> PromptMatch:
    if not allow_previous_prompts:
        for previous in lines[:index]:
            previous_stripped = previous.strip()
            if previous_stripped and _prompt_body(previous_stripped, provider=provider) is not None:
                return PromptMatch(body="ambiguous prompt-marker block", line_index=index, line=lines[index].strip())
    trailing = [body]
    for line in lines[index + 1 :]:
        candidate = line.strip()
        if not candidate:
            continue
        if _is_provider_footer(candidate, provider=provider):
            break
        trailing.append(candidate)
    return PromptMatch(body="\n".join(trailing).strip(), line_index=index, line=lines[index].strip())


def _prompt_body(line: str, *, provider: str | None) -> str | None:
    if provider == "codex":
        prompt_markers = ("\u203a",)
    elif provider == "claude":
        prompt_markers = (">",)
    else:
        prompt_markers = ()
    for marker in prompt_markers:
        if line.startswith(marker):
            return line[len(marker) :].strip()
    return None


def _prompt_body_start_column(line: str, *, provider: str | None) -> int:
    if provider == "codex":
        marker = "\u203a"
    elif provider == "claude":
        marker = ">"
    else:
        return 0
    if not line.startswith(marker):
        return 0
    index = len(marker)
    while index < len(line) and line[index].isspace():
        index += 1
    return index


def _is_provider_footer(line: str, *, provider: str | None) -> bool:
    lowered = line.lower()
    if provider == "codex":
        return bool(re.search(r"\bgpt-[0-9][\w.-]*\b.*·", lowered))
    if provider == "claude":
        return "? for shortcuts" in lowered or "esc to interrupt" in lowered
    return False


def _strip_status_prefix(line: str) -> str:
    return re.sub(r"^[•●⏺⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏*\\-]\s*", "", line).strip()


def _has_provider_prompt_context(
    text: str,
    prompt: PromptMatch,
    *,
    provider: str | None,
    cursor_line_index: int | None,
) -> bool:
    lines = text.splitlines()
    non_empty_indexes = [index for index, line in enumerate(lines) if line.strip()]
    line_index = prompt.line_index

    footer_index = _footer_index_after_prompt(lines, line_index, provider=provider)
    if provider in {"codex", "claude"} and footer_index is None:
        return False
    if cursor_line_index is None:
        return False
    if _prompt_body_is_empty(prompt.body):
        if cursor_line_index != line_index:
            return False
    elif footer_index is not None and not (line_index <= cursor_line_index < footer_index):
        return False
    elif footer_index is None and cursor_line_index < line_index:
        return False
    if footer_index is not None:
        for index in non_empty_indexes:
            if index > footer_index:
                return False

    nearby_end = footer_index + 1 if footer_index is not None else min(len(lines), line_index + 4)
    nearby_lines = lines[line_index + 1 : nearby_end]
    nearby = "\n".join(nearby_lines)
    lowered = nearby.lower()

    if provider == "codex":
        return bool(re.search(r"\bgpt-[0-9][\w.-]*\b.*·", lowered))

    if provider == "claude":
        has_footer = "? for shortcuts" in lowered
        if not has_footer:
            return False
        if not _prompt_body_is_empty(prompt.body):
            return True
        return "\u258c" in prompt.line or "|" in prompt.line

    return False


def _footer_index_after_prompt(lines: list[str], prompt_index: int, *, provider: str | None) -> int | None:
    for index in range(prompt_index + 1, len(lines)):
        candidate = lines[index].strip()
        if not candidate:
            continue
        if _is_provider_footer(candidate, provider=provider):
            return index
    return None


def _prompt_body_is_empty(body: str) -> bool:
    return not _strip_prompt_cursor(body).strip()


def _strip_prompt_cursor(body: str) -> str:
    return body.replace("\u258c", "")
