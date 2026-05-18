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
SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
CODEX_STARTER_PROMPTS = {
    "Explain this codebase",
    "Summarize recent commits",
    "Implement {feature}",
    "Find and fix a bug in @filename",
    "Write tests for @filename",
    "Improve documentation in @filename",
    "Run /review on my current changes",
    "Use /skills to list available skills",
    "Check recently modified functions for compatibility",
    "How many files have been modified?",
    "Will this algorithm scale well?",
}
CODEX_UNRESOLVED_TEMPLATE_RE = re.compile(r"(?:\{[^{}\n]+\}|@[A-Za-z][A-Za-z0-9_-]*)")
CODEX_STARTER_PLACEHOLDER_REASON = "codex starter placeholder has no pending user text"
CODEX_PROMPT_MARKERS = ("\u203a",)
CLAUDE_PROMPT_MARKERS = (">", "\u276f")


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

    prompt = _safe_prompt(visible, provider=provider, cursor_line_index=cursor_line_index)
    if _looks_like_working_state(visible, provider=provider, prompt=prompt):
        return Classification(PaneState.AGENT_WORKING, "agent appears to be working")

    if prompt is not None:
        if not _prompt_body_is_empty(prompt.body):
            if _is_codex_starter_placeholder(
                prompt,
                raw_text=text or "",
                provider=provider,
                cursor_column_index=cursor_column_index,
            ) and _has_provider_prompt_context(
                visible,
                prompt,
                provider=provider,
                cursor_line_index=cursor_line_index,
                cursor_column_index=cursor_column_index,
            ):
                return Classification(PaneState.IDLE_EMPTY_PROMPT, CODEX_STARTER_PLACEHOLDER_REASON)
            return Classification(PaneState.PENDING_USER_TEXT, "prompt contains pending user text")
        if not _has_provider_prompt_context(
            visible,
            prompt,
            provider=provider,
            cursor_line_index=cursor_line_index,
            cursor_column_index=cursor_column_index,
        ):
            return Classification(PaneState.DEAD_OR_UNKNOWN, "bare prompt marker lacks provider TUI context")
        return Classification(PaneState.IDLE_EMPTY_PROMPT, "idle prompt has no pending text")

    return Classification(PaneState.DEAD_OR_UNKNOWN, "no safe idle prompt was detected")


def current_prompt_body(
    text: str,
    *,
    provider: str | None,
    cursor_line_index: int | None,
    cursor_column_index: int | None = None,
    allow_cursor_backed_prompt_without_footer: bool = False,
) -> str | None:
    visible = strip_terminal_control(text or "")
    prompt = _safe_prompt(visible, provider=provider, cursor_line_index=cursor_line_index)
    if prompt is None:
        return None
    has_context = _has_provider_prompt_context(
        visible,
        prompt,
        provider=provider,
        cursor_line_index=cursor_line_index,
        cursor_column_index=cursor_column_index,
    )
    if not has_context and not (
        allow_cursor_backed_prompt_without_footer
        and _has_cursor_backed_unfooted_prompt_context(
            visible,
            prompt,
            provider=provider,
            cursor_line_index=cursor_line_index,
        )
    ):
        return None
    return _strip_prompt_cursor(prompt.body)


def is_codex_starter_placeholder_idle(classification: Classification) -> bool:
    return (
        classification.state == PaneState.IDLE_EMPTY_PROMPT
        and classification.reason == CODEX_STARTER_PLACEHOLDER_REASON
    )


def _is_codex_starter_placeholder(
    prompt: PromptMatch,
    *,
    raw_text: str,
    provider: str | None,
    cursor_column_index: int | None,
) -> bool:
    # DELICATE_FIX: Carefully debugged. Modify only with failing repro + targeted tests.
    if provider != "codex" or cursor_column_index is None:
        return False
    body = _strip_prompt_cursor(prompt.body).strip()
    if body not in CODEX_STARTER_PROMPTS:
        return False
    if cursor_column_index > _prompt_body_start_column(prompt.line, provider=provider):
        return False
    raw_line = _line_at(raw_text, prompt.line_index)
    if _line_has_sgr(raw_line):
        return _codex_prompt_body_is_dim(raw_line)
    return bool(CODEX_UNRESOLVED_TEMPLATE_RE.search(body))


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


def _looks_like_working_state(
    text: str,
    *,
    provider: str | None,
    prompt: PromptMatch | None,
) -> bool:
    lines = text.splitlines()
    non_empty_indexes = [index for index, line in enumerate(lines) if line.strip()]
    for index in non_empty_indexes[-12:]:
        line = lines[index].strip().lower()
        if not _line_is_working_status(line):
            continue
        if prompt is not None and not _working_status_is_active_for_prompt(
            lines,
            index,
            prompt,
            provider=provider,
        ):
            continue
        return True
    return False


def _line_is_working_status(line: str) -> bool:
    line = _strip_status_prefix(line.strip().lower())
    if re.match(r"^(working|thinking|running|executing|applying patch|waiting for)\b", line):
        return True
    return " tokens" in line and ("used" in line or "remaining" in line)


def _working_status_is_active_for_prompt(
    lines: list[str],
    status_index: int,
    prompt: PromptMatch,
    *,
    provider: str | None,
) -> bool:
    if status_index >= prompt.line_index:
        return True
    for index in range(status_index + 1, prompt.line_index):
        candidate = lines[index].strip()
        if not candidate:
            continue
        if _prompt_body(candidate, provider=provider) is not None:
            return False
        if _is_provider_footer(candidate, provider=provider):
            return False
        if _line_is_working_status(candidate):
            continue
        return False
    return True


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
            return _prompt_from_index(
                lines,
                index,
                body,
                provider=provider,
                allow_previous_prompts=True,
                cursor_line_index=cursor_line_index,
            )
    return None


def _last_prompt(text: str, *, provider: str | None) -> PromptMatch | None:
    lines = text.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        stripped = lines[index].strip()
        if not stripped:
            continue
        body = _prompt_body(stripped, provider=provider)
        if body is not None:
            return _prompt_from_index(
                lines,
                index,
                body,
                provider=provider,
                allow_previous_prompts=False,
                cursor_line_index=None,
            )
    return None


def _prompt_from_index(
    lines: list[str],
    index: int,
    body: str,
    *,
    provider: str | None,
    allow_previous_prompts: bool,
    cursor_line_index: int | None,
) -> PromptMatch:
    if not allow_previous_prompts:
        for previous in lines[:index]:
            previous_stripped = previous.strip()
            if previous_stripped and _prompt_body(previous_stripped, provider=provider) is not None:
                return PromptMatch(body="ambiguous prompt-marker block", line_index=index, line=lines[index].strip())
    trailing = [body]
    for line_index, line in enumerate(lines[index + 1 :], start=index + 1):
        candidate = line.strip()
        if not candidate:
            continue
        if _is_provider_footer(candidate, provider=provider):
            break
        if _is_provider_prompt_auxiliary_line(candidate, provider=provider):
            break
        trailing.append(candidate)
    return PromptMatch(body="\n".join(trailing).strip(), line_index=index, line=lines[index].strip())


def _prompt_body(line: str, *, provider: str | None) -> str | None:
    for marker in _prompt_markers(provider):
        if line.startswith(marker):
            return line[len(marker) :].strip()
    return None


def _prompt_body_start_column(line: str, *, provider: str | None) -> int:
    for marker in _prompt_markers(provider):
        if line.startswith(marker):
            index = len(marker)
            while index < len(line) and line[index].isspace():
                index += 1
            return index
    return 0


def _prompt_markers(provider: str | None) -> tuple[str, ...]:
    if provider == "codex":
        return CODEX_PROMPT_MARKERS
    if provider == "claude":
        return CLAUDE_PROMPT_MARKERS
    return ()


def _line_at(text: str, line_index: int) -> str:
    lines = text.splitlines()
    if line_index < 0 or line_index >= len(lines):
        return ""
    return lines[line_index]


def _line_has_sgr(line: str) -> bool:
    return SGR_RE.search(line) is not None


def _codex_prompt_body_is_dim(raw_line: str) -> bool:
    visible_line = strip_terminal_control(raw_line).strip()
    body_start_column = _prompt_body_start_column(visible_line, provider="codex")
    return _dim_style_at_visible_column(raw_line.strip(), body_start_column)


def _dim_style_at_visible_column(raw_line: str, target_column: int) -> bool:
    dim = False
    visible_column = 0
    index = 0
    while index < len(raw_line):
        sgr = SGR_RE.match(raw_line, index)
        if sgr is not None:
            dim = _sgr_dim_state(sgr.group(1), dim)
            index = sgr.end()
            continue
        control = ANSI_RE.match(raw_line, index)
        if control is not None:
            index = control.end()
            continue
        if visible_column >= target_column:
            return dim
        visible_column += 1
        index += 1
    return visible_column >= target_column and dim


def _sgr_dim_state(parameter_text: str, current: bool) -> bool:
    if not parameter_text:
        return False
    try:
        parameters = [int(part) if part else 0 for part in parameter_text.split(";")]
    except ValueError:
        return current
    dim = current
    index = 0
    while index < len(parameters):
        code = parameters[index]
        if code in {38, 48, 58}:
            index = _skip_extended_sgr_color(parameters, index)
            continue
        if code == 0:
            dim = False
        elif code == 2:
            dim = True
        elif code == 22:
            dim = False
        index += 1
    return dim


def _skip_extended_sgr_color(parameters: list[int], index: int) -> int:
    if index + 1 >= len(parameters):
        return index + 1
    mode = parameters[index + 1]
    if mode == 2:
        return min(len(parameters), index + 5)
    if mode == 5:
        return min(len(parameters), index + 3)
    return index + 1


def _is_provider_footer(line: str, *, provider: str | None) -> bool:
    lowered = line.lower()
    if provider == "codex":
        return bool(re.search(r"\bgpt-[0-9][\w.-]*\b.*·", lowered))
    if provider == "claude":
        return (
            "? for shortcuts" in lowered
            or "esc to interrupt" in lowered
            or ("bypass permissions" in lowered and "shift+tab to cycle" in lowered)
        )
    return False


def _is_provider_prompt_auxiliary_line(line: str, *, provider: str | None) -> bool:
    if provider == "claude":
        stripped = line.strip()
        return bool(stripped) and set(stripped) <= {"─"}
    if provider != "codex":
        return False
    normalized = re.sub(r"\s+", " ", line.strip().lower())
    return (
        normalized.startswith("create a plan?")
        and "plan mode" in normalized
        and "esc" in normalized
        and "dismiss" in normalized
    )


def _strip_status_prefix(line: str) -> str:
    return re.sub(r"^[•●⏺⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏*\\-]\s*", "", line).strip()


def _has_provider_prompt_context(
    text: str,
    prompt: PromptMatch,
    *,
    provider: str | None,
    cursor_line_index: int | None,
    cursor_column_index: int | None,
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
            has_footer = "bypass permissions" in lowered and "shift+tab to cycle" in lowered
        if not has_footer:
            return False
        if not _prompt_body_is_empty(prompt.body):
            return True
        return (
            "\u258c" in prompt.line
            or "|" in prompt.line
            or _cursor_is_at_empty_prompt_body(
                prompt.line,
                provider=provider,
                cursor_column_index=cursor_column_index,
            )
        )

    return False


def _has_cursor_backed_unfooted_prompt_context(
    text: str,
    prompt: PromptMatch,
    *,
    provider: str | None,
    cursor_line_index: int | None,
) -> bool:
    if provider != "codex" or cursor_line_index is None:
        return False
    if _prompt_body_is_empty(prompt.body):
        return False
    lines = text.splitlines()
    if cursor_line_index < prompt.line_index or cursor_line_index >= len(lines):
        return False
    if _footer_index_after_prompt(lines, prompt.line_index, provider=provider) is not None:
        return False
    return True


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


def _cursor_is_at_empty_prompt_body(
    line: str,
    *,
    provider: str | None,
    cursor_column_index: int | None,
) -> bool:
    if cursor_column_index is None:
        return False
    body_start_column = _prompt_body_start_column(line, provider=provider)
    return body_start_column <= cursor_column_index <= body_start_column + 1


def _strip_prompt_cursor(body: str) -> str:
    return body.replace("\u258c", "")
