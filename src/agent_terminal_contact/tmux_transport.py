"""Pane-locked tmux transport plus agent-tmux transcript lookup."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import secrets
import time

from .runner import Runner
from .session import validate_pane_id, validate_session_name


CAPTURE_STATE_FORMAT = "#{cursor_x}\t#{cursor_y}\t#{pane_width}\t#{pane_height}"


class TransportError(RuntimeError):
    pass


class UnsubmittedMessageError(TransportError):
    pass


class PreSubmitCheckError(UnsubmittedMessageError):
    pass


@dataclass(frozen=True)
class PaneCapture:
    text: str
    cursor_x: int
    cursor_y: int
    pane_width: int
    pane_height: int

    @property
    def cursor_line_index(self) -> int:
        line_count = len(self.text.splitlines())
        visible_origin = max(0, line_count - self.pane_height)
        return visible_origin + self.cursor_y


@dataclass(frozen=True)
class AgentTmuxTransport:
    runner: Runner
    executable: str = "agent-tmux"

    def capture(self, pane_id: str, lines: int = 160) -> str:
        validate_pane_id(pane_id)
        result = self.runner.run(["tmux", "capture-pane", "-ep", "-t", pane_id, "-S", f"-{lines}"])
        if result.returncode != 0:
            raise TransportError(_detail("capture failed", result.stderr, result.stdout))
        return result.stdout

    def capture_state(self, pane_id: str, lines: int = 160) -> PaneCapture:
        text = self.capture(pane_id, lines)
        state = self.runner.run(["tmux", "display-message", "-p", "-t", pane_id, CAPTURE_STATE_FORMAT])
        if state.returncode != 0:
            raise TransportError(_detail("capture cursor-state failed", state.stderr, state.stdout))
        parts = state.stdout.strip().split("\t")
        if len(parts) != 4:
            raise TransportError("capture cursor-state failed: malformed tmux cursor metadata")
        try:
            cursor_x, cursor_y, pane_width, pane_height = (int(part) for part in parts)
        except ValueError:
            raise TransportError("capture cursor-state failed: non-numeric tmux cursor metadata") from None
        return PaneCapture(
            text=text,
            cursor_x=cursor_x,
            cursor_y=cursor_y,
            pane_width=pane_width,
            pane_height=pane_height,
        )

    def log_path(self, session: str) -> str:
        validate_session_name(session)
        result = self.runner.run([self.executable, "log", session])
        if result.returncode != 0:
            raise TransportError(_detail("log path lookup failed", result.stderr, result.stdout))
        return result.stdout.strip()

    def send(
        self,
        pane_id: str,
        message: str,
        *,
        pre_paste_check: Callable[[], None] | None = None,
        pre_submit_check: Callable[[], None] | None = None,
        literal_key_chunk_size: int | None = None,
        literal_key_chunk_delay_seconds: float = 0.0,
    ) -> None:
        validate_pane_id(pane_id)
        if not message:
            raise TransportError("refusing to send an empty message")
        if literal_key_chunk_size is not None and literal_key_chunk_size <= 0:
            raise TransportError("literal key chunk size must be positive")
        if literal_key_chunk_delay_seconds < 0:
            raise TransportError("literal key chunk delay must not be negative")

        if literal_key_chunk_size is not None:
            if pre_paste_check is not None:
                pre_paste_check()
            self._send_literal_chunks(
                pane_id,
                message,
                chunk_size=literal_key_chunk_size,
                chunk_delay_seconds=literal_key_chunk_delay_seconds,
            )
            if pre_submit_check is not None:
                try:
                    pre_submit_check()
                except Exception as exc:
                    raise PreSubmitCheckError(
                        "pre-submit revalidation failed after literal input; "
                        f"target composer may contain an unsubmitted message: {exc}"
                    ) from exc
            self._submit(pane_id)
            return

        buffer_name = f"agent-contact-{pane_id.lstrip('%')}-{secrets.token_hex(4)}"
        load = self.runner.run(["tmux", "load-buffer", "-b", buffer_name, "-"], input_text=message)
        if load.returncode != 0:
            raise TransportError(_detail("load-buffer failed", load.stderr, load.stdout))
        try:
            if pre_paste_check is not None:
                pre_paste_check()
            paste = self.runner.run(["tmux", "paste-buffer", "-d", "-r", "-b", buffer_name, "-t", pane_id])
            if paste.returncode != 0:
                raise TransportError(_detail("paste-buffer failed", paste.stderr, paste.stdout))
            if pre_submit_check is not None:
                try:
                    pre_submit_check()
                except Exception as exc:
                    raise PreSubmitCheckError(
                        "pre-submit revalidation failed after paste; "
                        f"target composer may contain an unsubmitted message: {exc}"
                    ) from exc
            self._submit(pane_id)
        finally:
            self._delete_buffer(buffer_name)

    def submit_pending(self, pane_id: str) -> None:
        validate_pane_id(pane_id)
        self._submit(pane_id)

    def _delete_buffer(self, buffer_name: str):
        return self.runner.run(["tmux", "delete-buffer", "-b", buffer_name])

    def _send_literal_chunks(
        self,
        pane_id: str,
        message: str,
        *,
        chunk_size: int,
        chunk_delay_seconds: float,
    ) -> None:
        # DELICATE_FIX: Carefully debugged. Modify only with failing repro + targeted tests.
        for offset in range(0, len(message), chunk_size):
            chunk = message[offset : offset + chunk_size]
            result = self.runner.run(["tmux", "send-keys", "-t", pane_id, "-l", "--", chunk])
            if result.returncode != 0:
                raise UnsubmittedMessageError(
                    _detail(
                        "literal input failed after partial send; target composer may contain an unsubmitted message",
                        result.stderr,
                        result.stdout,
                    )
                )
            if chunk_delay_seconds and offset + chunk_size < len(message):
                time.sleep(chunk_delay_seconds)

    def _submit(self, pane_id: str) -> None:
        enter = self.runner.run(["tmux", "send-keys", "-t", pane_id, "C-m"])
        if enter.returncode != 0:
            raise UnsubmittedMessageError(
                _detail(
                    "submit key failed after input; target composer may contain an unsubmitted message",
                    enter.stderr,
                    enter.stdout,
                )
            )


def _detail(prefix: str, stderr: str, stdout: str) -> str:
    detail = (stderr or stdout).strip()
    return f"{prefix}: {detail}" if detail else prefix
