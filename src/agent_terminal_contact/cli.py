"""Command-line interface for guarded terminal-agent contact."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import secrets
import sys
from typing import TextIO

from .classifier import PaneState, classify_pane
from .runner import Runner, SubprocessRunner
from .session import DiscoveryError, select_target
from .tmux_transport import AgentTmuxTransport, TransportError


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DISCOVERY = 3
EXIT_REFUSED = 4
EXIT_UNPROVEN = 5
EXIT_TRANSPORT = 6


def main(
    argv: list[str] | None = None,
    *,
    runner: Runner | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    runner = runner or SubprocessRunner()
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "send":
        return _send(args, runner, stdout, stderr)

    parser.print_help(stderr)
    return EXIT_USAGE


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-contact")
    subparsers = parser.add_subparsers(dest="command", required=True)

    send = subparsers.add_parser("send", help="guarded send to a live terminal agent")
    send.add_argument("--repo", required=True, help="absolute or relative target project path")
    send.add_argument("--provider", required=True, choices=("codex", "claude"))
    send.add_argument("--message", required=True, help="message body to send")
    send.add_argument("--session", help="explicit tmux session name to validate and use")
    send.add_argument("--dry-run", action="store_true", help="classify and report without sending")
    send.add_argument("--json", action="store_true", help="emit JSON output")
    send.add_argument("--agent-tmux", default="agent-tmux", help="agent-tmux executable path")
    send.add_argument("--capture-lines", type=int, default=160)
    send.add_argument("--contact-id", help=argparse.SUPPRESS)
    return parser


def _send(args: argparse.Namespace, runner: Runner, stdout: TextIO, stderr: TextIO) -> int:
    try:
        selection = select_target(
            repo=args.repo,
            provider=args.provider,
            runner=runner,
            explicit_session=args.session,
        )
    except DiscoveryError as exc:
        _emit(
            args,
            stdout,
            {
                "status": "refused",
                "stage": "discovery",
                "reason": str(exc),
            },
        )
        return EXIT_DISCOVERY

    transport = AgentTmuxTransport(runner=runner, executable=args.agent_tmux)

    try:
        before = transport.capture(selection.session.name, args.capture_lines)
        log_path = transport.log_path(selection.session.name)
    except (DiscoveryError, TransportError) as exc:
        _emit(
            args,
            stdout,
            {
                "status": "error",
                "stage": "capture",
                "reason": str(exc),
                "session": selection.session.name,
            },
        )
        return EXIT_TRANSPORT

    classification = classify_pane(before)
    base = {
        "repo": selection.repo,
        "provider": selection.provider,
        "session": selection.session.name,
        "session_command": selection.session.command,
        "provider_evidence": selection.session.provider_evidence,
        "log_path": log_path,
        "pane_state": classification.state.value,
        "pane_reason": classification.reason,
    }

    if classification.state != PaneState.IDLE_EMPTY_PROMPT:
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "refused",
                "stage": "pre_send_state",
                "reason": classification.reason,
            },
        )
        return EXIT_REFUSED

    contact_id = args.contact_id or _new_contact_id()
    guarded_message = f"CONTACT_ID: {contact_id}\n{args.message}"

    if args.dry_run:
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "would_send",
                "contact_id": contact_id,
            },
        )
        return EXIT_OK

    try:
        transport.send(selection.session.name, guarded_message)
        after = transport.capture(selection.session.name, args.capture_lines)
    except (DiscoveryError, TransportError) as exc:
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "error",
                "stage": "send",
                "contact_id": contact_id,
                "reason": str(exc),
            },
        )
        return EXIT_TRANSPORT

    after_classification = classify_pane(after)
    delivery_proven = contact_id in after and after_classification.state != PaneState.PENDING_USER_TEXT
    status = "sent" if delivery_proven else "sent_unproven"
    _emit(
        args,
        stdout,
        {
            **base,
            "status": status,
            "contact_id": contact_id,
            "post_send_state": after_classification.state.value,
            "post_send_reason": after_classification.reason,
            "delivery_proven": delivery_proven,
        },
    )
    return EXIT_OK if delivery_proven else EXIT_UNPROVEN


def _emit(args: argparse.Namespace, stdout: TextIO, payload: dict[str, object]) -> None:
    if getattr(args, "json", False):
        stdout.write(json.dumps(payload, sort_keys=True) + "\n")
        return

    status = payload.get("status", "unknown")
    stdout.write(f"agent-contact: {status}\n")
    for key in (
        "stage",
        "reason",
        "repo",
        "provider",
        "session",
        "session_command",
        "provider_evidence",
        "pane_state",
        "pane_reason",
        "contact_id",
        "post_send_state",
        "post_send_reason",
        "delivery_proven",
        "log_path",
    ):
        if key in payload:
            stdout.write(f"{key}: {payload[key]}\n")


def _new_contact_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"AC-{stamp}-{secrets.token_hex(4)}"
