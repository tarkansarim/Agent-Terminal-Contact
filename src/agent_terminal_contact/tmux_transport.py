"""Transport wrapper around agent-tmux."""

from __future__ import annotations

from dataclasses import dataclass

from .runner import Runner
from .session import validate_session_name


class TransportError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentTmuxTransport:
    runner: Runner
    executable: str = "agent-tmux"

    def capture(self, session: str, lines: int = 160) -> str:
        validate_session_name(session)
        result = self.runner.run([self.executable, "capture", session, str(lines)])
        if result.returncode != 0:
            raise TransportError(_detail("capture failed", result.stderr, result.stdout))
        return result.stdout

    def log_path(self, session: str) -> str:
        validate_session_name(session)
        result = self.runner.run([self.executable, "log", session])
        if result.returncode != 0:
            raise TransportError(_detail("log path lookup failed", result.stderr, result.stdout))
        return result.stdout.strip()

    def send(self, session: str, message: str) -> None:
        validate_session_name(session)
        if not message:
            raise TransportError("refusing to send an empty message")
        result = self.runner.run([self.executable, "send", session, message])
        if result.returncode != 0:
            raise TransportError(_detail("send failed", result.stderr, result.stdout))


def _detail(prefix: str, stderr: str, stdout: str) -> str:
    detail = (stderr or stdout).strip()
    return f"{prefix}: {detail}" if detail else prefix
