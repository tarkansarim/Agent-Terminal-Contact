"""Command runner abstraction used by the CLI and tests."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Protocol, Sequence


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class Runner(Protocol):
    def run(self, args: Sequence[str]) -> CommandResult:
        ...


class SubprocessRunner:
    def run(self, args: Sequence[str]) -> CommandResult:
        completed = subprocess.run(
            list(args),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return CommandResult(tuple(args), completed.returncode, completed.stdout, completed.stderr)
