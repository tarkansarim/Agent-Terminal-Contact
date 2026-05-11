"""tmux session discovery for guarded agent contact."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Sequence

from .runner import Runner


SESSION_FORMAT = "#{session_name}\t#{pane_current_path}\t#{pane_current_command}\t#{session_created}\t#{session_attached}"
SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class DiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class TmuxSession:
    name: str
    path: str
    command: str
    created: int
    attached: int
    provider_evidence: str


@dataclass(frozen=True)
class TargetSelection:
    repo: str
    provider: str
    session: TmuxSession
    candidates: tuple[TmuxSession, ...]


def select_target(
    *,
    repo: str,
    provider: str,
    runner: Runner,
    explicit_session: str | None = None,
) -> TargetSelection:
    repo_path = _resolve_existing_repo(repo)
    provider = _normalize_provider(provider)

    if explicit_session:
        session = _read_explicit_session(explicit_session, runner)
        if _resolve_path(session.path) != repo_path:
            raise DiscoveryError(
                f"explicit session {explicit_session!r} is rooted at {session.path!r}, not {repo_path!r}"
            )
        matched = _with_provider_evidence(session, provider, explicit=True)
        if matched is None:
            raise DiscoveryError(
                f"explicit session {explicit_session!r} does not look like provider {provider!r}"
            )
        return TargetSelection(repo_path, provider, matched, (matched,))

    candidates = tuple(
        session
        for session in _list_sessions(runner)
        if _resolve_path(session.path) == repo_path
        for session in [_with_provider_evidence(session, provider, explicit=False)]
        if session is not None
    )

    if not candidates:
        raise DiscoveryError(f"no tmux-managed {provider} session found for {repo_path}")
    if len(candidates) > 1:
        names = ", ".join(session.name for session in candidates)
        raise DiscoveryError(f"multiple tmux-managed {provider} sessions found for {repo_path}: {names}")

    return TargetSelection(repo_path, provider, candidates[0], candidates)


def validate_session_name(session: str) -> None:
    if not SESSION_NAME_RE.match(session):
        raise DiscoveryError("session name must match [A-Za-z0-9_.-]+")


def _read_explicit_session(session: str, runner: Runner) -> TmuxSession:
    validate_session_name(session)
    result = runner.run(["tmux", "display-message", "-p", "-t", session, SESSION_FORMAT])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise DiscoveryError(f"failed to inspect session {session!r}: {detail}")
    sessions = _parse_session_lines(result.stdout.splitlines())
    if len(sessions) != 1:
        raise DiscoveryError(f"failed to parse session metadata for {session!r}")
    return sessions[0]


def _list_sessions(runner: Runner) -> tuple[TmuxSession, ...]:
    result = runner.run(["tmux", "list-sessions", "-F", SESSION_FORMAT])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise DiscoveryError(f"tmux session discovery failed: {detail}")
    return tuple(_parse_session_lines(result.stdout.splitlines()))


def _parse_session_lines(lines: Sequence[str]) -> list[TmuxSession]:
    sessions: list[TmuxSession] = []
    for line in lines:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        name, path, command, created, attached = parts
        sessions.append(
            TmuxSession(
                name=name,
                path=path,
                command=command,
                created=_safe_int(created),
                attached=_safe_int(attached),
                provider_evidence="unmatched",
            )
        )
    return sessions


def _with_provider_evidence(session: TmuxSession, provider: str, *, explicit: bool) -> TmuxSession | None:
    name = session.name.lower()
    command = session.command.lower()
    opposite = "claude" if provider == "codex" else "codex"

    if opposite in name:
        return None
    if provider in name:
        evidence = f"session name contains {provider}"
    elif command == provider:
        evidence = f"pane command is {provider}"
    elif explicit and command == "node":
        evidence = f"explicit session uses node command and is not labeled {opposite}"
    else:
        return None

    return TmuxSession(
        name=session.name,
        path=session.path,
        command=session.command,
        created=session.created,
        attached=session.attached,
        provider_evidence=evidence,
    )


def _normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized not in {"codex", "claude"}:
        raise DiscoveryError("provider must be 'codex' or 'claude'")
    return normalized


def _resolve_existing_repo(repo: str) -> str:
    path = Path(repo).expanduser()
    if not path.exists() or not path.is_dir():
        raise DiscoveryError(f"repo path does not exist or is not a directory: {repo}")
    return str(path.resolve())


def _resolve_path(path: str) -> str:
    if not path:
        return ""
    return str(Path(path).expanduser().resolve())


def _safe_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0
