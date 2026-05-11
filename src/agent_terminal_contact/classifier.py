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


def strip_terminal_control(text: str) -> str:
    return ANSI_RE.sub("", text).replace("\r", "\n")


def classify_pane(text: str) -> Classification:
    visible = strip_terminal_control(text or "")
    lowered = visible.lower()

    if not visible.strip():
        return Classification(PaneState.DEAD_OR_UNKNOWN, "capture was empty")

    if _looks_like_trust_prompt(lowered):
        return Classification(PaneState.TRUST_PROMPT, "directory trust prompt is visible")

    if _looks_like_approval_prompt(lowered):
        return Classification(PaneState.APPROVAL_PROMPT, "approval prompt is visible")

    prompt = _last_prompt_body(visible)
    if prompt is not None:
        if _prompt_body_is_empty(prompt):
            return Classification(PaneState.IDLE_EMPTY_PROMPT, "idle prompt has no pending text")
        return Classification(PaneState.PENDING_USER_TEXT, "prompt contains pending user text")

    if _looks_like_working_state(lowered):
        return Classification(PaneState.AGENT_WORKING, "agent appears to be working")

    return Classification(PaneState.DEAD_OR_UNKNOWN, "no safe idle prompt was detected")


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


def _looks_like_working_state(lowered: str) -> bool:
    working_markers = (
        "working",
        "thinking",
        "running",
        "applying patch",
        "executing",
        "waiting for",
        "tokens",
        "interrupt",
    )
    return any(marker in lowered for marker in working_markers)


def _last_prompt_body(text: str) -> str | None:
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        body = _prompt_body(stripped)
        if body is not None:
            return body
    return None


def _prompt_body(line: str) -> str | None:
    prompt_markers = ("\u203a", ">")
    for marker in prompt_markers:
        if line.startswith(marker):
            return line[len(marker) :].strip()
    return None


def _prompt_body_is_empty(body: str) -> bool:
    cursor_chars = ("\u258c", "|")
    cleaned = body
    for char in cursor_chars:
        cleaned = cleaned.replace(char, "")
    return not cleaned.strip()
