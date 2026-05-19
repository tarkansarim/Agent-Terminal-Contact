"""Command-line interface for guarded terminal-agent contact."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import secrets
import shlex
import sys
import time
from typing import TextIO

from .artifact_ownership import ArtifactLookupError, artifact_info_payload
from .classifier import (
    PaneState,
    classify_pane,
    current_prompt_body,
    is_codex_starter_placeholder_idle,
    strip_terminal_control,
)
from .runner import Runner, SubprocessRunner
from .session import DiscoveryError, revalidate_target, select_target, suggest_trusted_roots
from .tmux_transport import AgentTmuxTransport, TransportError, UnsubmittedMessageError


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DISCOVERY = 3
EXIT_REFUSED = 4
EXIT_UNPROVEN = 5
EXIT_TRANSPORT = 6
CONTACT_ID_RE = re.compile(r"^AC-[A-Za-z0-9_.:-]+$")
CODEX_COLLAPSED_PASTE_RE = re.compile(r"^\[Pasted Content (?P<count>[0-9]+) chars\]$")
BRACKETED_PASTE_SEQUENCES = ("\x1b[200~", "\x1b[201~")
MESSAGE_ALLOWED_CONTROLS = {"\n", "\t"}
POST_PASTE_READBACK_ATTEMPTS = 40
POST_PASTE_READBACK_STABLE_MISMATCH_ATTEMPTS = 5
POST_PASTE_READBACK_DELAY_SECONDS = 0.05
CODEX_COLLAPSED_PASTE_THRESHOLD_CHARS = 1024
CODEX_LITERAL_INPUT_CHUNK_SIZE = 200
CODEX_LITERAL_INPUT_DELAY_SECONDS = 0.03


@dataclass(frozen=True)
class PendingGuardedContact:
    contact_id: str
    guarded_message: str


@dataclass(frozen=True)
class PendingGuardedResidue:
    contact_id: str
    guarded_message: str


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
    if args.command == "trust-roots":
        return _trust_roots(args, runner, stdout)
    if args.command == "artifact-info":
        return _artifact_info(args, stdout, stderr)

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

    trust_roots = subparsers.add_parser(
        "trust-roots",
        help="inspect live tmux panes and print narrow provider/launcher roots for agent-contact",
    )
    trust_roots.add_argument("--repo", required=True, help="absolute or relative target project path")
    trust_roots.add_argument("--provider", required=True, choices=("codex", "claude"))
    trust_roots.add_argument("--session", help="explicit tmux session name to validate and inspect")
    trust_roots.add_argument("--json", action="store_true", help="emit JSON output")

    artifact_info = subparsers.add_parser(
        "artifact-info",
        help="report source ownership for installed AgentTerminalContact artifacts",
    )
    artifact_info.add_argument("artifact", nargs="?", help="installed path, command name, or manifest artifact id")
    artifact_info.add_argument("--all", action="store_true", help="report every artifact in the source manifest")
    artifact_info.add_argument("--json", action="store_true", help="emit JSON output")
    artifact_info.add_argument("--manifest", help="artifact ownership manifest path")
    return parser


def _artifact_info(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    try:
        payload = artifact_info_payload(
            args.artifact,
            all_artifacts=args.all,
            manifest_path=args.manifest,
        )
    except ArtifactLookupError as exc:
        payload = {
            "status": "error",
            "stage": "artifact_lookup",
            "reason": str(exc),
        }
        if args.json:
            stdout.write(json.dumps(payload, sort_keys=True) + "\n")
        else:
            stderr.write(f"agent-contact: artifact lookup error: {exc}\n")
        return EXIT_USAGE

    if args.json:
        stdout.write(json.dumps(payload, sort_keys=True) + "\n")
        return EXIT_OK if payload["matches"] else EXIT_DISCOVERY

    if not payload["matches"]:
        stdout.write("agent-contact artifact-info: unknown\n")
        stdout.write(f"query: {args.artifact}\n")
        stdout.write(f"manifest: {payload['manifest_path']}\n")
        return EXIT_DISCOVERY

    stdout.write(f"agent-contact artifact-info: {payload['status']}\n")
    for match in payload["matches"]:
        stdout.write(f"artifact: {match['id']}\n")
        stdout.write(f"kind: {match['kind']}\n")
        stdout.write(f"ownership: {match['ownership']}\n")
        stdout.write(f"installed_path: {match['installed_path']}\n")
        stdout.write(f"source_repo: {match['source_repo']}\n")
        stdout.write(f"source_path: {match['source_path']}\n")
        stdout.write(f"installed_matches_source: {match['installed_matches_source']}\n")
        stdout.write(f"match_reason: {match['match_reason']}\n")
        if match.get("delegates_to"):
            stdout.write(f"delegates_to: {match['delegates_to']}\n")
        if match.get("install_command"):
            stdout.write(f"install_command: {match['install_command']}\n")
        if match.get("check_command"):
            stdout.write(f"check_command: {match['check_command']}\n")
        if match.get("notes"):
            stdout.write(f"notes: {match['notes']}\n")
    return EXIT_OK


def _trust_roots(args: argparse.Namespace, runner: Runner, stdout: TextIO) -> int:
    try:
        suggestions = suggest_trusted_roots(
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

    payload = {
        "status": "ok",
        "repo": suggestions[0].repo,
        "provider": args.provider,
        "suggestions": [
            {
                "session": suggestion.session_name,
                "pane_id": suggestion.pane_id,
                "provider_pid": suggestion.provider_pid,
                "provider_root": suggestion.provider_root,
                "launcher_root": suggestion.launcher_root,
                "process_args": suggestion.process_args,
            }
            for suggestion in suggestions
        ],
    }
    if args.json:
        stdout.write(json.dumps(payload, sort_keys=True) + "\n")
        return EXIT_OK

    stdout.write("agent-contact: ok\n")
    if len(suggestions) != 1:
        stdout.write("reason: multiple matching provider panes; rerun with --session before exporting roots\n")
        for suggestion in suggestions:
            stdout.write(f"- {suggestion.session_name}:{suggestion.pane_id} provider_root={suggestion.provider_root}\n")
        return EXIT_OK

    suggestion = suggestions[0]
    stdout.write(f"session: {suggestion.session_name}\n")
    stdout.write(f"pane_id: {suggestion.pane_id}\n")
    stdout.write(f"export AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS={shlex.quote(suggestion.provider_root)}\n")
    if suggestion.launcher_root is not None:
        stdout.write(f"export AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS={shlex.quote(suggestion.launcher_root)}\n")
    return EXIT_OK


def _send(args: argparse.Namespace, runner: Runner, stdout: TextIO, stderr: TextIO) -> int:
    payload_error = _message_payload_error(args.message)
    if payload_error is not None:
        _emit(
            args,
            stdout,
            {
                "status": "refused",
                "stage": "message",
                "reason": payload_error,
            },
        )
        return EXIT_REFUSED

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
        before_capture = transport.capture_state(selection.pane.pane_id, args.capture_lines)
        before = before_capture.text
        log_path = transport.log_path(selection.pane.session_name)
    except (DiscoveryError, TransportError) as exc:
        _emit(
            args,
            stdout,
            {
                "status": "error",
                "stage": "capture",
                "reason": str(exc),
                "session": selection.pane.session_name,
                "pane_id": selection.pane.pane_id,
            },
        )
        return EXIT_TRANSPORT

    classification = classify_pane(
        before,
        provider=selection.provider,
        cursor_line_index=before_capture.cursor_line_index,
        cursor_column_index=before_capture.cursor_x,
    )
    base = {
        "repo": selection.repo,
        "provider": selection.provider,
        "session": selection.pane.session_name,
        "pane_id": selection.pane.pane_id,
        "session_command": selection.pane.command,
        "pane_pid": selection.pane.pid,
        "provider_pid": selection.pane.provider_pid,
        "provider_evidence": selection.pane.provider_evidence,
        "log_path": log_path,
        "pane_state": classification.state.value,
        "pane_reason": classification.reason,
    }

    pending_guarded_contact = None
    pending_guarded_residue = None
    if classification.state == PaneState.PENDING_USER_TEXT:
        pending_guarded_contact = _matching_pending_guarded_contact(
            before,
            provider=selection.provider,
            cursor_line_index=before_capture.cursor_line_index,
            cursor_column_index=before_capture.cursor_x,
            requested_message=args.message,
        )
        if pending_guarded_contact is None:
            pending_guarded_residue = _matching_pending_guarded_residue(
                before,
                provider=selection.provider,
                cursor_line_index=before_capture.cursor_line_index,
                cursor_column_index=before_capture.cursor_x,
                requested_message=args.message,
            )

    if (
        classification.state != PaneState.IDLE_EMPTY_PROMPT
        and pending_guarded_contact is None
        and pending_guarded_residue is None
    ):
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

    if pending_guarded_residue is not None:
        if selection.pane.attached > 0:
            _emit(
                args,
                stdout,
                {
                    **base,
                    "status": "refused",
                    "stage": "attached_session",
                    "contact_id": pending_guarded_residue.contact_id,
                    "recovery": "clear_pending_guarded_contact",
                    "clear_command": _clear_input_command(selection.pane.session_name),
                    "reason": "target tmux session is attached; refusing contact to avoid human input races",
                },
            )
            return EXIT_REFUSED
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "refused",
                "stage": "pending_guarded_contact",
                "contact_id": pending_guarded_residue.contact_id,
                "recovery": "clear_pending_guarded_contact",
                "clear_command": _clear_input_command(selection.pane.session_name),
                "reason": (
                    "pending composer contains duplicated guarded-contact residue for the requested message; "
                    "clear the proven residue and rerun guarded contact"
                ),
            },
        )
        return EXIT_REFUSED

    if pending_guarded_contact is not None:
        if selection.pane.attached > 0:
            _emit(
                args,
                stdout,
                {
                    **base,
                    "status": "refused",
                    "stage": "attached_session",
                    "contact_id": pending_guarded_contact.contact_id,
                    "recovery": "pending_guarded_contact",
                    "reason": "target tmux session is attached; refusing contact to avoid human input races",
                },
            )
            return EXIT_REFUSED

        if args.dry_run:
            _emit(
                args,
                stdout,
                {
                    **base,
                    "status": "would_submit_pending",
                    "stage": "pending_guarded_contact",
                    "contact_id": pending_guarded_contact.contact_id,
                    "recovery": "pending_guarded_contact",
                    "reason": "pending composer contains matching guarded contact; real send would submit it without pasting",
                },
            )
            return EXIT_OK

        return _submit_pending_guarded_contact(
            args,
            stdout,
            selection,
            runner,
            transport,
            args.capture_lines,
            pending_guarded_contact,
            base,
        )

    if selection.pane.attached > 0:
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "refused",
                "stage": "attached_session",
                "reason": "target tmux session is attached; refusing contact to avoid human input races",
            },
        )
        return EXIT_REFUSED

    contact_id = args.contact_id or _new_contact_id()
    if not CONTACT_ID_RE.match(contact_id):
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "refused",
                "stage": "contact_id",
                "reason": "contact id must be a single AC-prefixed token",
                "contact_id": contact_id,
            },
        )
        return EXIT_REFUSED
    contact_marker = f"CONTACT_ID: {contact_id}"
    if contact_marker in before:
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "refused",
                "stage": "contact_id",
                "reason": "contact id is already visible before send",
                "contact_id": contact_id,
            },
        )
        return EXIT_REFUSED
    guarded_message = _guarded_message(contact_id, args.message)

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

    send_starter_placeholder_via_literal = False
    try:
        revalidated = revalidate_target(selection, runner)
        latest_before_capture = transport.capture_state(revalidated.pane_id, args.capture_lines)
        latest_before = latest_before_capture.text
        latest_classification = classify_pane(
            latest_before,
            provider=selection.provider,
            cursor_line_index=latest_before_capture.cursor_line_index,
            cursor_column_index=latest_before_capture.cursor_x,
        )
        if latest_classification.state != PaneState.IDLE_EMPTY_PROMPT:
            _emit(
                args,
                stdout,
                {
                    **base,
                    "status": "refused",
                    "stage": "pre_send_recapture",
                    "contact_id": contact_id,
                    "reason": latest_classification.reason,
                    "pane_state": latest_classification.state.value,
                    "pane_reason": latest_classification.reason,
                },
            )
            return EXIT_REFUSED
        if contact_marker in latest_before:
            _emit(
                args,
                stdout,
                {
                    **base,
                    "status": "refused",
                    "stage": "contact_id",
                    "contact_id": contact_id,
                    "reason": "contact id is already visible in latest pre-send capture",
                },
            )
            return EXIT_REFUSED
        send_target = revalidate_target(selection, runner)
        final_before_capture = transport.capture_state(send_target.pane_id, args.capture_lines)
        final_before = final_before_capture.text
        final_classification = classify_pane(
            final_before,
            provider=selection.provider,
            cursor_line_index=final_before_capture.cursor_line_index,
            cursor_column_index=final_before_capture.cursor_x,
        )
        if final_classification.state != PaneState.IDLE_EMPTY_PROMPT:
            _emit(
                args,
                stdout,
                {
                    **base,
                    "status": "refused",
                    "stage": "pre_send_final_state",
                    "contact_id": contact_id,
                    "reason": final_classification.reason,
                    "pane_state": final_classification.state.value,
                    "pane_reason": final_classification.reason,
                },
            )
            return EXIT_REFUSED
        if contact_marker in final_before:
            _emit(
                args,
                stdout,
                {
                    **base,
                    "status": "refused",
                    "stage": "contact_id",
                    "contact_id": contact_id,
                    "reason": "contact id is already visible in final pre-send capture",
                },
            )
            return EXIT_REFUSED
        send_starter_placeholder_via_literal = (
            selection.provider == "codex" and is_codex_starter_placeholder_idle(final_classification)
        )
    except DiscoveryError as exc:
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "refused",
                "stage": "pre_send_revalidate",
                "contact_id": contact_id,
                "reason": str(exc),
            },
        )
        return EXIT_REFUSED
    except TransportError as exc:
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "error",
                "stage": "pre_send_capture",
                "contact_id": contact_id,
                "reason": str(exc),
            },
        )
        return EXIT_TRANSPORT

    try:
        literal_key_chunk_size = None
        literal_key_chunk_delay_seconds = 0.0
        if selection.provider == "codex" and (
            send_starter_placeholder_via_literal or len(guarded_message) >= CODEX_COLLAPSED_PASTE_THRESHOLD_CHARS
        ):
            literal_key_chunk_size = CODEX_LITERAL_INPUT_CHUNK_SIZE
            literal_key_chunk_delay_seconds = CODEX_LITERAL_INPUT_DELAY_SECONDS
        transport.send(
            send_target.pane_id,
            guarded_message,
            pre_paste_check=lambda: _revalidate_idle_prompt(
                selection,
                runner,
                transport,
                args.capture_lines,
                contact_marker,
            ),
            pre_submit_check=lambda: _revalidate_pasted_contact(
                selection,
                runner,
                transport,
                args.capture_lines,
                guarded_message,
            ),
            literal_key_chunk_size=literal_key_chunk_size,
            literal_key_chunk_delay_seconds=literal_key_chunk_delay_seconds,
        )
    except UnsubmittedMessageError as exc:
        try:
            contaminated_capture = transport.capture_state(selection.pane.pane_id, args.capture_lines)
            contaminated_classification = classify_pane(
                contaminated_capture.text,
                provider=selection.provider,
                cursor_line_index=contaminated_capture.cursor_line_index,
                cursor_column_index=contaminated_capture.cursor_x,
            )
            contaminated_state = contaminated_classification.state.value
            contaminated_reason = contaminated_classification.reason
        except TransportError as capture_exc:
            contaminated_state = PaneState.DEAD_OR_UNKNOWN.value
            contaminated_reason = f"post-failure capture failed: {capture_exc}"
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "mutated_unsubmitted",
                "stage": "submit",
                "contact_id": contact_id,
                "reason": str(exc),
                "pane_state": contaminated_state,
                "pane_reason": contaminated_reason,
                "delivery_proven": False,
            },
        )
        return EXIT_TRANSPORT
    except DiscoveryError as exc:
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "refused",
                "stage": "pre_send_revalidate",
                "contact_id": contact_id,
                "reason": str(exc),
            },
        )
        return EXIT_REFUSED
    except TransportError as exc:
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

    try:
        after_target = revalidate_target(selection, runner)
        after_capture = transport.capture_state(after_target.pane_id, args.capture_lines)
        after = after_capture.text
    except DiscoveryError as exc:
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "sent_unproven",
                "stage": "post_send_revalidate",
                "contact_id": contact_id,
                "reason": str(exc),
                "delivery_proven": False,
            },
        )
        return EXIT_UNPROVEN
    except TransportError as exc:
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "sent_unproven",
                "stage": "post_send_capture",
                "contact_id": contact_id,
                "reason": str(exc),
                "delivery_proven": False,
            },
        )
        return EXIT_UNPROVEN

    after_classification = classify_pane(
        after,
        provider=selection.provider,
        cursor_line_index=after_capture.cursor_line_index,
        cursor_column_index=after_capture.cursor_x,
    )
    delivery_proven = (
        _capture_contains_guarded_message(after, guarded_message)
        and after_classification.state == PaneState.IDLE_EMPTY_PROMPT
    )
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


def _submit_pending_guarded_contact(
    args: argparse.Namespace,
    stdout: TextIO,
    selection,
    runner: Runner,
    transport: AgentTmuxTransport,
    lines: int,
    pending_guarded_contact: PendingGuardedContact,
    base: dict[str, object],
) -> int:
    try:
        target = revalidate_target(selection, runner)
        latest_capture = transport.capture_state(target.pane_id, lines)
        latest_classification = classify_pane(
            latest_capture.text,
            provider=selection.provider,
            cursor_line_index=latest_capture.cursor_line_index,
            cursor_column_index=latest_capture.cursor_x,
        )
        latest_pending = _matching_pending_guarded_contact(
            latest_capture.text,
            provider=selection.provider,
            cursor_line_index=latest_capture.cursor_line_index,
            cursor_column_index=latest_capture.cursor_x,
            requested_message=args.message,
        )
        if latest_classification.state != PaneState.PENDING_USER_TEXT or latest_pending != pending_guarded_contact:
            _emit(
                args,
                stdout,
                {
                    **base,
                    "status": "refused",
                    "stage": "pending_recovery_revalidate",
                    "contact_id": pending_guarded_contact.contact_id,
                    "recovery": "pending_guarded_contact",
                    "reason": "pending guarded contact no longer matches the requested message",
                    "pane_state": latest_classification.state.value,
                    "pane_reason": latest_classification.reason,
                },
            )
            return EXIT_REFUSED
        transport.submit_pending(target.pane_id)
    except UnsubmittedMessageError as exc:
        try:
            contaminated_capture = transport.capture_state(selection.pane.pane_id, args.capture_lines)
            contaminated_classification = classify_pane(
                contaminated_capture.text,
                provider=selection.provider,
                cursor_line_index=contaminated_capture.cursor_line_index,
                cursor_column_index=contaminated_capture.cursor_x,
            )
            contaminated_state = contaminated_classification.state.value
            contaminated_reason = contaminated_classification.reason
        except TransportError as capture_exc:
            contaminated_state = PaneState.DEAD_OR_UNKNOWN.value
            contaminated_reason = f"post-failure capture failed: {capture_exc}"
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "mutated_unsubmitted",
                "stage": "submit",
                "contact_id": pending_guarded_contact.contact_id,
                "recovery": "pending_guarded_contact",
                "reason": str(exc),
                "pane_state": contaminated_state,
                "pane_reason": contaminated_reason,
                "delivery_proven": False,
            },
        )
        return EXIT_TRANSPORT
    except DiscoveryError as exc:
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "refused",
                "stage": "pending_recovery_revalidate",
                "contact_id": pending_guarded_contact.contact_id,
                "recovery": "pending_guarded_contact",
                "reason": str(exc),
            },
        )
        return EXIT_REFUSED
    except TransportError as exc:
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "error",
                "stage": "pending_recovery_capture",
                "contact_id": pending_guarded_contact.contact_id,
                "recovery": "pending_guarded_contact",
                "reason": str(exc),
            },
        )
        return EXIT_TRANSPORT

    try:
        after_target = revalidate_target(selection, runner)
        after_capture = transport.capture_state(after_target.pane_id, lines)
        after = after_capture.text
    except DiscoveryError as exc:
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "sent_unproven",
                "stage": "post_send_revalidate",
                "contact_id": pending_guarded_contact.contact_id,
                "recovery": "pending_guarded_contact",
                "reason": str(exc),
                "delivery_proven": False,
            },
        )
        return EXIT_UNPROVEN
    except TransportError as exc:
        _emit(
            args,
            stdout,
            {
                **base,
                "status": "sent_unproven",
                "stage": "post_send_capture",
                "contact_id": pending_guarded_contact.contact_id,
                "recovery": "pending_guarded_contact",
                "reason": str(exc),
                "delivery_proven": False,
            },
        )
        return EXIT_UNPROVEN

    after_classification = classify_pane(
        after,
        provider=selection.provider,
        cursor_line_index=after_capture.cursor_line_index,
        cursor_column_index=after_capture.cursor_x,
    )
    delivery_proven = (
        _capture_contains_guarded_message(after, pending_guarded_contact.guarded_message)
        and after_classification.state == PaneState.IDLE_EMPTY_PROMPT
    )
    status = "sent" if delivery_proven else "sent_unproven"
    _emit(
        args,
        stdout,
        {
            **base,
            "status": status,
            "contact_id": pending_guarded_contact.contact_id,
            "recovery": "pending_guarded_contact",
            "post_send_state": after_classification.state.value,
            "post_send_reason": after_classification.reason,
            "delivery_proven": delivery_proven,
        },
    )
    return EXIT_OK if delivery_proven else EXIT_UNPROVEN


def _revalidate_idle_prompt(selection, runner: Runner, transport: AgentTmuxTransport, lines: int, contact_marker: str) -> None:
    target = revalidate_target(selection, runner)
    capture = transport.capture_state(target.pane_id, lines)
    classification = classify_pane(
        capture.text,
        provider=selection.provider,
        cursor_line_index=capture.cursor_line_index,
        cursor_column_index=capture.cursor_x,
    )
    if classification.state != PaneState.IDLE_EMPTY_PROMPT:
        raise DiscoveryError(classification.reason)
    if contact_marker in capture.text:
        raise DiscoveryError("contact id is already visible in critical pre-paste capture")


def _revalidate_pasted_contact(selection, runner: Runner, transport: AgentTmuxTransport, lines: int, guarded_message: str) -> None:
    last_reason = "pasted contact was not visible before submit"
    stable_mismatch_key: tuple[str, str] | None = None
    stable_mismatch_count = 0
    for attempt in range(POST_PASTE_READBACK_ATTEMPTS):
        target = revalidate_target(selection, runner)
        capture = transport.capture_state(target.pane_id, lines)
        prompt_body = current_prompt_body(
            capture.text,
            provider=selection.provider,
            cursor_line_index=capture.cursor_line_index,
            cursor_column_index=capture.cursor_x,
            allow_cursor_backed_prompt_without_footer=True,
        )
        classification = classify_pane(
            capture.text,
            provider=selection.provider,
            cursor_line_index=capture.cursor_line_index,
            cursor_column_index=capture.cursor_x,
        )
        if (
            classification.state == PaneState.PENDING_USER_TEXT
            and prompt_body is not None
            and _normalized_prompt_body_matches_pasted_contact(
                prompt_body,
                guarded_message,
                provider=selection.provider,
            )
        ):
            return
        if classification.state != PaneState.PENDING_USER_TEXT:
            last_reason = f"pasted contact is not visible as pending composer text: {classification.reason}"
            mismatch_key = (classification.state.value, classification.reason)
        else:
            last_reason = "full guarded contact line or exact Codex pasted-content placeholder is not the current composer prompt body"
            mismatch_key = (classification.state.value, _normalized_prompt_body(prompt_body or ""))
        if mismatch_key == stable_mismatch_key:
            stable_mismatch_count += 1
        else:
            stable_mismatch_key = mismatch_key
            stable_mismatch_count = 1
        # Codex can repaint long literal input over several captures; fail early only
        # once the visible non-matching state has stopped changing.
        if stable_mismatch_count >= POST_PASTE_READBACK_STABLE_MISMATCH_ATTEMPTS:
            break
        if attempt + 1 < POST_PASTE_READBACK_ATTEMPTS:
            time.sleep(POST_PASTE_READBACK_DELAY_SECONDS)
    raise DiscoveryError(last_reason)


def _message_payload_error(message: str) -> str | None:
    for sequence in BRACKETED_PASTE_SEQUENCES:
        if sequence in message:
            return "message contains a bracketed paste control sequence"
    for character in message:
        codepoint = ord(character)
        if character in MESSAGE_ALLOWED_CONTROLS:
            continue
        if codepoint < 0x20 or codepoint == 0x7F or 0x80 <= codepoint <= 0x9F:
            return f"message contains terminal control character U+{codepoint:04X}"
    return None


def _guarded_message(contact_id: str, message: str) -> str:
    return f"CONTACT_ID: {contact_id} MESSAGE_JSON: {json.dumps(message)}"


def _matching_pending_guarded_contact(
    text: str,
    *,
    provider: str,
    cursor_line_index: int,
    cursor_column_index: int,
    requested_message: str,
) -> PendingGuardedContact | None:
    prompt_body = current_prompt_body(
        text,
        provider=provider,
        cursor_line_index=cursor_line_index,
        cursor_column_index=cursor_column_index,
        allow_cursor_backed_prompt_without_footer=True,
    )
    if prompt_body is None:
        return None
    contact_id = _contact_id_from_prompt_body(prompt_body)
    if contact_id is None:
        return None
    guarded_message = _guarded_message(contact_id, requested_message)
    if not _normalized_prompt_body_matches_pasted_contact(prompt_body, guarded_message, provider=provider):
        return None
    return PendingGuardedContact(contact_id=contact_id, guarded_message=guarded_message)


def _matching_pending_guarded_residue(
    text: str,
    *,
    provider: str,
    cursor_line_index: int,
    cursor_column_index: int,
    requested_message: str,
) -> PendingGuardedResidue | None:
    prompt_body = current_prompt_body(
        text,
        provider=provider,
        cursor_line_index=cursor_line_index,
        cursor_column_index=cursor_column_index,
        allow_cursor_backed_prompt_without_footer=True,
    )
    if prompt_body is None:
        return None
    contact_id = _contact_id_from_prompt_body(prompt_body)
    if contact_id is None:
        return None
    guarded_message = _guarded_message(contact_id, requested_message)
    if _normalized_prompt_body_matches_pasted_contact(prompt_body, guarded_message, provider=provider):
        return None
    if not _prompt_body_is_duplicated_guarded_residue(prompt_body, guarded_message):
        return None
    return PendingGuardedResidue(contact_id=contact_id, guarded_message=guarded_message)


def _contact_id_from_prompt_body(prompt_body: str) -> str | None:
    normalized = _normalized_prompt_body(prompt_body)
    match = re.match(r"^CONTACT_ID: (?P<contact_id>AC-[A-Za-z0-9_.:-]+)\b", normalized)
    if match is None:
        return None
    contact_id = match.group("contact_id")
    if not CONTACT_ID_RE.match(contact_id):
        return None
    return contact_id


def _normalized_prompt_body(prompt_body: str) -> str:
    return prompt_body.replace("\n", "").replace("\u258c", "").strip()


def _normalized_prompt_body_matches_pasted_contact(prompt_body: str, guarded_message: str, *, provider: str) -> bool:
    normalized = _normalized_prompt_body(prompt_body)
    if normalized == guarded_message:
        return True
    if _codex_visual_wrapped_prompt_body_matches_guarded_message(prompt_body, guarded_message):
        return True
    if provider != "codex":
        return False
    match = CODEX_COLLAPSED_PASTE_RE.match(normalized)
    if match is None:
        return False
    return int(match.group("count")) == len(guarded_message)


def _prompt_body_is_duplicated_guarded_residue(prompt_body: str, guarded_message: str) -> bool:
    # DELICATE_FIX: Carefully debugged. Modify only with failing repro + targeted tests.
    normalized = _normalized_prompt_body(prompt_body)
    if _normalized_body_is_repeated_guarded_residue(normalized, guarded_message):
        return True
    return _visual_wrapped_body_is_repeated_guarded_residue(prompt_body, guarded_message)


def _normalized_body_is_repeated_guarded_residue(normalized: str, guarded_message: str) -> bool:
    remaining = normalized
    full_matches = 0
    while remaining.startswith(guarded_message):
        full_matches += 1
        remaining = remaining[len(guarded_message) :]
    if full_matches == 0:
        return False
    if not remaining:
        return full_matches > 1
    return guarded_message.startswith(remaining)


def _visual_wrapped_body_is_repeated_guarded_residue(prompt_body: str, guarded_message: str) -> bool:
    pieces = [piece.replace("\u258c", "").strip() for piece in prompt_body.splitlines()]
    pieces = [piece for piece in pieces if piece]
    if not pieces:
        return False

    position = 0
    full_matches = 0
    for piece in pieces:
        if guarded_message.startswith(piece, position):
            position += len(piece)
        elif (
            position < len(guarded_message)
            and guarded_message[position] == " "
            and guarded_message.startswith(piece, position + 1)
        ):
            position += len(piece) + 1
        else:
            return False
        if position == len(guarded_message):
            full_matches += 1
            position = 0
    if full_matches == 0:
        return False
    return full_matches > 1 or position > 0


def _codex_visual_wrapped_prompt_body_matches_guarded_message(prompt_body: str, guarded_message: str) -> bool:
    # DELICATE_FIX: Carefully debugged. Modify only with failing repro + targeted tests.
    pieces = [piece.replace("\u258c", "").strip() for piece in prompt_body.splitlines()]
    pieces = [piece for piece in pieces if piece]
    if not pieces:
        return False

    position = 0
    for index, piece in enumerate(pieces):
        if guarded_message.startswith(piece, position):
            position += len(piece)
            continue
        if (
            index > 0
            and position < len(guarded_message)
            and guarded_message[position] == " "
            and guarded_message.startswith(piece, position + 1)
        ):
            position += len(piece) + 1
            continue
        return False
    return position == len(guarded_message)


def _capture_contains_guarded_message(text: str, guarded_message: str) -> bool:
    visible = strip_terminal_control(text)
    return (
        guarded_message in text
        or guarded_message in visible
        or _remove_visual_wrap_newlines(visible).find(guarded_message) != -1
        or _visible_text_contains_wrapped_guarded_message(visible, guarded_message)
    )


def _remove_visual_wrap_newlines(text: str) -> str:
    return text.replace("\n", "")


def _visible_text_contains_wrapped_guarded_message(text: str, guarded_message: str) -> bool:
    lines = text.splitlines()
    for start_index, line in enumerate(lines):
        marker_index = line.find("CONTACT_ID:")
        if marker_index == -1:
            continue
        pieces = [line[marker_index:]]
        if _codex_visual_wrapped_prompt_body_matches_guarded_message("\n".join(pieces), guarded_message):
            return True
        for line in lines[start_index + 1 : min(len(lines), start_index + 12)]:
            if not line.strip():
                break
            pieces.append(line)
            if _codex_visual_wrapped_prompt_body_matches_guarded_message("\n".join(pieces), guarded_message):
                return True
    return False


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
        "pane_id",
        "pane_pid",
        "provider_pid",
        "provider_evidence",
        "pane_state",
        "pane_reason",
        "contact_id",
        "recovery",
        "clear_command",
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


def _clear_input_command(session_name: str) -> str:
    return f"agent-tmux clear-input {session_name}"
