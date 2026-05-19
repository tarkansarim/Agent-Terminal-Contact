import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_terminal_contact.cli import EXIT_DISCOVERY, EXIT_OK, EXIT_REFUSED, EXIT_TRANSPORT, EXIT_UNPROVEN, main
from agent_terminal_contact.runner import CommandResult
from agent_terminal_contact.session import PANE_FORMAT
from agent_terminal_contact.tmux_transport import CAPTURE_STATE_FORMAT


SIDECAR_REQUEST_PERMISSION = "-c sandbox_mode=workspace-write -c sandbox_workspace_write.network_access=false -a never"
SIDECAR_REQUEST_FILESYSTEM_ISOLATION = (
    "bwrap minimal root, selected host tool files only, private /tmp and /run, "
    "artifact directory writable for map output, separate wrapper-owned runtime directory"
)


CODEX_IDLE = "previous assistant output\n\n\u203a \n  gpt-5.5 xhigh · /tmp/project\n"
CODEX_STARTER = (
    "╭────────────────────────────────────────────────╮\n"
    "│ >_ OpenAI Codex (v0.130.0)                     │\n"
    "│                                                │\n"
    "│ model:     gpt-5.5 xhigh   /model to change    │\n"
    "│ directory: ~/Dropbox/work/MyTools/3dSculptTool │\n"
    "╰────────────────────────────────────────────────╯\n\n"
    "  Tip: Use /side to start a side conversation in a temporary fork without polluting the main thread.\n\n\n"
    "\u203a Improve documentation in @filename\n\n"
    "  gpt-5.5 xhigh · ~/Dropbox/work/MyTools/3dSculptTool\n"
)
CODEX_DIM_STARTER = CODEX_STARTER.replace(
    "Improve documentation in @filename",
    "\x1b[2mSummarize recent commits\x1b[0m",
)
CLAUDE_IDLE = "previous assistant output\n\n> \u258c\n? for shortcuts\n"
CLAUDE_V2_IDLE = (
    " ▐▛███▜▌   Claude Code v2.1.143\n"
    "───────────────────────────── owner-ComfyComannder-109-claude ──\n"
    "❯\u00a0\n"
    "────────────────────────────────────────────────────────────────\n"
    "  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
)


def guarded_line(message='hello', *, contact_id="AC-TEST"):
    return f"CONTACT_ID: {contact_id} MESSAGE_JSON: {json.dumps(message)}"


def codex_pending_contact(message='hello'):
    return f"previous assistant output\n\n\u203a {guarded_line(message)}\n  gpt-5.5 xhigh · /tmp/project\n"


def codex_wrapped_pending_contact(message='hello', width=24):
    line = guarded_line(message)
    pieces = [line[:width], *[line[index : index + width] for index in range(width, len(line), width)]]
    wrapped = "\n".join(pieces)
    return f"previous assistant output\n\n\u203a {wrapped}\n  gpt-5.5 xhigh · /tmp/project\n"


def codex_collapsed_pasted_contact(message='hello', *, count_delta=0):
    line = guarded_line(message)
    return (
        "previous assistant output\n\n"
        f"\u203a [Pasted Content {len(line) + count_delta} chars]\n"
        "  gpt-5.5 xhigh · /tmp/project\n"
    )


def codex_plan_mode_pending_contact(message='hello'):
    return (
        "previous assistant output\n\n"
        f"\u203a {guarded_line(message)}\n"
        "  Create a plan? shift + tab use Plan mode esc dismiss\n"
        "  gpt-5.5 xhigh · /tmp/project\n"
    )


def codex_plan_mode_wrapped_lines(lines):
    first, *rest = lines
    return (
        "previous assistant output\n\n"
        f"\u203a {first}\n"
        + "".join(f"{line}\n" for line in rest)
        + "  Create a plan? shift + tab use Plan mode esc dismiss\n"
        + "  gpt-5.5 xhigh · /tmp/project\n"
    )


def codex_plan_mode_wrapped_lines_without_footer(lines):
    first, *rest = lines
    return (
        "previous assistant output\n\n"
        f"\u203a {first}\n"
        + "".join(f"{line}\n" for line in rest)
        + "  Create a plan?  shift + tab use Plan mode   esc dismiss\n"
    )


def claude_wrapped_pending_contact(message='hello', width=24):
    line = guarded_line(message)
    pieces = [line[index : index + width] for index in range(0, len(line), width)]
    pieces[-1] = pieces[-1] + "\u258c"
    wrapped = "\n".join(pieces)
    return f"previous assistant output\n\n> {wrapped}\n? for shortcuts\n"


def claude_v2_pending_contact_with_hidden_space_wrap(message='hello', *, contact_id="AC-TEST"):
    line = guarded_line(message, contact_id=contact_id)
    split_index = line.index(" beta")
    return (
        " ▐▛███▜▌   Claude Code v2.1.143\n"
        "───────────────────────────── owner-ComfyComannder-109-claude ──\n"
        f"❯\u00a0{line[:split_index]}\n"
        f"  {line[split_index + 1:]}\n"
        "────────────────────────────────────────────────────────────────\n"
        "  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
    )


def claude_v2_wrapped_lines(lines, *, session="owner-SkillPackagingDiscipline-126-142-claude"):
    first, *rest = lines
    return (
        "╭─── Claude Code v2.1.143 ─────────────────────────────────────────────────────╮\n"
        "│                Welcome back Tarkan!                                          │\n"
        "╰──────────────────────────────────────────────────────────────────────────────╯\n\n"
        f"─────────────────────────────── {session} ──\n"
        f"❯\u00a0{first}\n"
        + "".join(f"  {line}\n" for line in rest)
        + "────────────────────────────────────────────────────────────────────────────────\n"
        + "  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
    )


def wrapped_guarded_echo(message='hello', width=24):
    line = guarded_line(message)
    return "\n".join(line[index : index + width] for index in range(0, len(line), width))


def write_provider_package(root, provider="codex"):
    if provider == "codex":
        package_root = Path(root) / "node_modules" / "@openai" / "codex"
        script = package_root / "bin" / "codex.js"
        package_json = '{"name":"@openai/codex","bin":{"codex":"bin/codex.js"}}\n'
    else:
        package_root = Path(root) / "node_modules" / "@anthropic-ai" / "claude-code"
        script = package_root / "bin" / "claude.exe"
        package_json = '{"name":"@anthropic-ai/claude-code","bin":{"claude":"bin/claude.exe","claude-code":"bin/claude.exe"}}\n'
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    (package_root / "package.json").write_text(package_json, encoding="utf-8")
    return script


def pane_line(session, pane_id, repo, command="node", pid=1234, attached=0):
    return f"{session}\t{pane_id}\t/dev/pts/7\t{Path(repo).resolve()}\t{command}\t{pid}\t1\t0\t10\t{attached}\n"


def write_sidecar_request(artifact_dir, *, session, repo):
    artifact_path = Path(artifact_dir)
    content = (
        f"session={session}\n"
        f"repo={Path(repo).resolve()}\n"
        "anchor=test-anchor\n"
        f"allowed_output_dir={artifact_path.resolve()}\n"
        f"permission={SIDECAR_REQUEST_PERMISSION}\n"
        f"filesystem_isolation={SIDECAR_REQUEST_FILESYSTEM_ISOLATION}\n"
        f"validator=agent-tmux codex-code-map-validate-artifacts {artifact_path.resolve()}\n"
    )
    artifact_path.joinpath("SIDECAR_REQUEST.txt").write_text(content, encoding="utf-8")
    registry_dir = artifact_path.parent / ".agent-tmux-sidecar-registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / f"{session}.txt").write_text(content, encoding="utf-8")


class FakeRunner:
    def __init__(
        self,
        repo,
        captures,
        *,
        fail_submit=False,
        fail_paste=False,
        cursor_line_index=None,
        cursor_line_indexes=None,
        cursor_x=0,
        cursor_x_indexes=None,
        display_messages=None,
        tty_processes=None,
        provider="codex",
        fail_dash_literal_without_option_terminator=False,
        fail_clear_input=False,
    ):
        if isinstance(captures, str):
            captures = [captures]
        resolved = Path(repo).resolve()
        script = write_provider_package(resolved, provider=provider)
        package_root = script.parents[1]
        os.environ["AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS"] = str(package_root)
        os.environ["AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS"] = "/usr/bin"
        session_name = f"{provider}-demo"
        self.default_display_message = CommandResult((), 0, pane_line(session_name, "%1", resolved), "")
        self.default_tty_process = CommandResult((), 0, f"1234 1 1234 Sl+ node {script}\n", "")
        self.display_messages = list(display_messages or [])
        self.tty_processes = list(tty_processes or [])
        self.responses = {
            ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                (), 0, pane_line(session_name, "%1", resolved), ""
            ),
            ("bash", "-lc", f"command -v -- {provider}"): CommandResult((), 0, f"{script}\n", ""),
            ("ps", "-p", "1234", "-o", "args="): CommandResult(
                (), 0, f"node {script}\n", ""
            ),
            ("cat", "/proc/1234/cmdline"): CommandResult((), 0, f"node\0{script}\0", ""),
            ("readlink", "-f", "/proc/1234/exe"): CommandResult((), 0, "/usr/bin/node\n", ""),
            ("cat", "/proc/1234/environ"): CommandResult((), 0, "PATH=/usr/bin\0", ""),
            ("agent-tmux", "log", session_name): CommandResult(
                (), 0, f"/tmp/agent-tmux/{session_name}.log\n", ""
            ),
        }
        self.captures = list(captures)
        self.calls = []
        self.fail_submit = fail_submit
        self.fail_paste = fail_paste
        self.fail_clear_input = fail_clear_input
        self.fail_dash_literal_without_option_terminator = fail_dash_literal_without_option_terminator
        self.cursor_line_index = cursor_line_index
        self.cursor_line_indexes = list(cursor_line_indexes or [])
        self.cursor_x = cursor_x
        self.cursor_x_indexes = list(cursor_x_indexes or [])

    def run(self, args, input_text=None):
        key = tuple(args)
        self.calls.append((key, input_text))
        if key[:2] == ("tmux", "capture-pane"):
            capture = self.captures.pop(0) if self.captures else ""
            self.last_capture = capture
            return CommandResult(key, 0, capture, "")
        if key == ("tmux", "display-message", "-p", "-t", "%1", CAPTURE_STATE_FORMAT):
            return CommandResult(key, 0, self._capture_state_stdout(), "")
        if key == ("tmux", "display-message", "-p", "-t", "%1", PANE_FORMAT):
            if self.display_messages:
                return self.display_messages.pop(0)
            return self.default_display_message
        if key == ("ps", "-t", "/dev/pts/7", "-o", "pid=,ppid=,pgid=,stat=,args="):
            if self.tty_processes:
                return self.tty_processes.pop(0)
            return self.default_tty_process
        if key[:3] == ("tmux", "load-buffer", "-b"):
            return CommandResult(key, 0, "", "")
        if key[:2] == ("tmux", "paste-buffer"):
            if self.fail_paste:
                return CommandResult(key, 1, "", "no such pane")
            return CommandResult(key, 0, "", "")
        if key[:3] == ("tmux", "delete-buffer", "-b"):
            return CommandResult(key, 0, "", "")
        if key[:2] == ("agent-tmux", "clear-input"):
            if self.fail_clear_input:
                return CommandResult(key, 1, "", "clear failed")
            return CommandResult(key, 0, "", "")
        if key[:5] == ("tmux", "send-keys", "-t", "%1", "-l"):
            literal_args = key[5:]
            if (
                self.fail_dash_literal_without_option_terminator
                and literal_args
                and literal_args[0] != "--"
                and literal_args[0].startswith("-")
            ):
                return CommandResult(
                    key,
                    1,
                    "",
                    "tmux: unknown option -- r\n"
                    "usage: send-keys [-FHlMRX] [-N repeat-count] [-t target-pane] key ...",
                )
            return CommandResult(key, 0, "", "")
        if key[:3] == ("tmux", "send-keys", "-t"):
            if self.fail_submit:
                return CommandResult(key, 1, "", "send failed")
            return CommandResult(key, 0, "", "")
        response = self.responses.get(key)
        if response is None:
            return CommandResult(key, 127, "", f"unexpected command: {key}")
        return response

    def _capture_state_stdout(self):
        lines = getattr(self, "last_capture", "").splitlines()
        if self.cursor_x_indexes:
            cursor_x = self.cursor_x_indexes.pop(0)
        else:
            cursor_x = self.cursor_x
        if self.cursor_line_indexes:
            cursor_y = self.cursor_line_indexes.pop(0)
        elif self.cursor_line_index is None:
            cursor_y = 0
            for index in range(len(lines) - 1, -1, -1):
                if lines[index].strip().startswith("\u203a") or lines[index].strip().startswith(">"):
                    cursor_y = index
                    break
        else:
            cursor_y = self.cursor_line_index
        pane_height = max(len(lines), 1)
        return f"{cursor_x}\t{cursor_y}\t120\t{pane_height}\n"


class AgentContactCliTests(unittest.TestCase):
    def test_dry_run_would_send_from_idle_prompt(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, CODEX_IDLE)
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--dry-run",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "would_send")
            self.assertEqual(payload["session"], "codex-demo")
            self.assertEqual(payload["pane_id"], "%1")
            self.assertFalse(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))

    def test_dry_run_would_send_from_claude_v2_idle_prompt(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, CLAUDE_V2_IDLE, provider="claude", cursor_line_index=2, cursor_x=2)
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "claude",
                    "--message",
                    "hello",
                    "--dry-run",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "would_send")
            self.assertEqual(payload["pane_state"], "idle_empty_prompt")

    def test_sidecar_contact_refuses_artifact_dir_as_repo_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_repo = Path(tmp) / "repo"
            session = "codex-map-repo-ticket58-123456789abc"
            artifact_dir = Path(tmp) / session
            original_repo.mkdir()
            artifact_dir.mkdir()
            write_sidecar_request(artifact_dir, session=session, repo=original_repo)
            runner = FakeRunner(artifact_dir, CODEX_IDLE)
            runner.responses[("tmux", "list-panes", "-s", "-t", session, "-F", PANE_FORMAT)] = CommandResult(
                (), 0, pane_line(session, "%1", artifact_dir), ""
            )
            runner.responses[("agent-tmux", "log", session)] = CommandResult(
                (), 0, f"/tmp/agent-tmux/{session}.log\n", ""
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    str(artifact_dir),
                    "--provider",
                    "codex",
                    "--session",
                    session,
                    "--message",
                    "follow up",
                    "--dry-run",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_DISCOVERY)
            self.assertEqual(payload["status"], "refused")
            self.assertIn("no tmux-managed codex pane found", payload["reason"])

    def test_sidecar_contact_uses_repo_root_with_manifest_and_exact_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            session = "codex-map-repo-ticket58-123456789abc"
            artifact_dir = tmp_path / session
            repo.mkdir()
            artifact_dir.mkdir()
            write_sidecar_request(artifact_dir, session=session, repo=repo)
            runner = FakeRunner(repo, CODEX_IDLE)
            sidecar_pane = pane_line(session, "%1", artifact_dir)
            runner.responses[("tmux", "list-panes", "-s", "-t", session, "-F", PANE_FORMAT)] = CommandResult(
                (), 0, sidecar_pane, ""
            )
            runner.responses[("agent-tmux", "log", session)] = CommandResult(
                (), 0, f"/tmp/agent-tmux/{session}.log\n", ""
            )
            runner.default_display_message = CommandResult((), 0, sidecar_pane, "")
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    str(repo),
                    "--provider",
                    "codex",
                    "--session",
                    session,
                    "--message",
                    "follow up",
                    "--dry-run",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "would_send")
            self.assertEqual(payload["repo"], str(repo.resolve()))
            self.assertEqual(payload["session"], session)

    def test_sidecar_contact_refuses_repo_root_when_manifest_session_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            session = "codex-map-repo-ticket58-123456789abc"
            artifact_dir = tmp_path / session
            repo.mkdir()
            artifact_dir.mkdir()
            write_sidecar_request(artifact_dir, session="codex-map-other-123456789abc", repo=repo)
            runner = FakeRunner(repo, CODEX_IDLE)
            sidecar_pane = pane_line(session, "%1", artifact_dir)
            runner.responses[("tmux", "list-panes", "-s", "-t", session, "-F", PANE_FORMAT)] = CommandResult(
                (), 0, sidecar_pane, ""
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    str(repo),
                    "--provider",
                    "codex",
                    "--session",
                    session,
                    "--message",
                    "follow up",
                    "--dry-run",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_DISCOVERY)
            self.assertEqual(payload["status"], "refused")
            self.assertIn("no tmux-managed codex pane found", payload["reason"])

    def test_sidecar_followup_send_uses_repo_root_with_manifest_and_exact_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            session = "codex-map-repo-ticket58-123456789abc"
            artifact_dir = tmp_path / session
            repo.mkdir()
            artifact_dir.mkdir()
            write_sidecar_request(artifact_dir, session=session, repo=repo)
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_pending_contact("follow up"),
                    f"{guarded_line('follow up')}\n{CODEX_IDLE}",
                ],
            )
            sidecar_pane = pane_line(session, "%1", artifact_dir)
            runner.responses[("tmux", "list-panes", "-s", "-t", session, "-F", PANE_FORMAT)] = CommandResult(
                (), 0, sidecar_pane, ""
            )
            runner.responses[("agent-tmux", "log", session)] = CommandResult(
                (), 0, f"/tmp/agent-tmux/{session}.log\n", ""
            )
            runner.default_display_message = CommandResult((), 0, sidecar_pane, "")
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    str(repo),
                    "--provider",
                    "codex",
                    "--session",
                    session,
                    "--message",
                    "follow up",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertEqual(payload["repo"], str(repo.resolve()))
            self.assertEqual(payload["session"], session)
            self.assertTrue(payload["delivery_proven"])

    def test_dry_run_reports_clear_path_from_codex_starter_placeholder(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, CODEX_STARTER, cursor_x=2)
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--dry-run",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "would_clear_and_send")
            self.assertEqual(payload["pane_state"], "idle_empty_prompt")
            self.assertEqual(payload["clear_command"], "agent-tmux clear-input codex-demo")

    def test_dry_run_reports_clear_path_from_dim_codex_starter_prompt(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, CODEX_DIM_STARTER, cursor_x=2)
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--dry-run",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "would_clear_and_send")
            self.assertEqual(payload["pane_state"], "idle_empty_prompt")
            self.assertEqual(payload["clear_command"], "agent-tmux clear-input codex-demo")

    def test_real_send_clears_codex_starter_placeholder_before_literal_input(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_STARTER,
                    CODEX_STARTER,
                    CODEX_IDLE,
                    CODEX_STARTER,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_pending_contact(),
                    f"{guarded_line()}\n{CODEX_IDLE}",
                ],
                cursor_x=2,
                fail_paste=True,
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            literal_calls = [
                call for call in runner.calls if call[0][:5] == ("tmux", "send-keys", "-t", "%1", "-l")
            ]
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(payload["delivery_proven"])
            self.assertEqual(payload["pane_state"], "idle_empty_prompt")
            self.assertEqual(payload["pane_reason"], "codex starter placeholder has no pending user text")
            self.assertTrue(any(call[0] == ("agent-tmux", "clear-input", "codex-demo") for call in runner.calls))
            self.assertEqual(len(literal_calls), 1)
            self.assertTrue(all(call[0][5] == "--" for call in literal_calls))
            self.assertFalse(any(call[0][:2] == ("tmux", "paste-buffer") for call in runner.calls))

    def test_trust_roots_reports_narrow_provider_and_launcher_roots(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, CODEX_IDLE)
            stdout = io.StringIO()
            code = main(
                [
                    "trust-roots",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--json",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(len(payload["suggestions"]), 1)
            suggestion = payload["suggestions"][0]
            self.assertEqual(
                suggestion["provider_root"],
                str(Path(repo).resolve() / "node_modules" / "@openai" / "codex"),
            )
            self.assertEqual(suggestion["launcher_root"], "/usr/bin")
            self.assertFalse(any(call[0][:2] == ("tmux", "capture-pane") for call in runner.calls))

    def test_trust_roots_refuses_node_preload_instead_of_returning_false_root(self):
        with tempfile.TemporaryDirectory() as repo:
            resolved = Path(repo).resolve()
            not_agent = resolved / "not-agent.js"
            not_agent.write_text("console.log('not agent')\n", encoding="utf-8")
            preload = resolved / "preload.js"
            preload.write_text("console.log('preload')\n", encoding="utf-8")
            args = f"node --require {preload} {not_agent}"
            runner = FakeRunner(repo, CODEX_IDLE, tty_processes=[CommandResult((), 0, f"1234 1 1234 Sl+ {args}\n", "")])
            runner.responses[("cat", "/proc/1234/cmdline")] = CommandResult((), 0, "\0".join(args.split()) + "\0", "")
            stdout = io.StringIO()
            code = main(
                [
                    "trust-roots",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--json",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_DISCOVERY)
            self.assertEqual(payload["status"], "refused")
            self.assertNotIn("False", stdout.getvalue())

    def test_trust_roots_refuses_package_not_anchored_by_provider_command_on_path(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as real_install:
            resolved = Path(repo).resolve()
            fake_script = write_provider_package(resolved)
            real_script = write_provider_package(real_install)
            runner = FakeRunner(repo, CODEX_IDLE)
            args = f"node {fake_script}"
            runner.default_tty_process = CommandResult((), 0, f"1234 1 1234 Sl+ {args}\n", "")
            runner.responses[("cat", "/proc/1234/cmdline")] = CommandResult((), 0, f"node\0{fake_script}\0", "")
            runner.responses[("bash", "-lc", "command -v -- codex")] = CommandResult((), 0, f"{real_script}\n", "")
            stdout = io.StringIO()
            code = main(
                [
                    "trust-roots",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--json",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_DISCOVERY)
            self.assertEqual(payload["status"], "refused")

    def test_trust_roots_accepts_global_npm_package_anchor_when_provider_command_is_wrapper(self):
        with tempfile.TemporaryDirectory() as repo:
            resolved = Path(repo).resolve()
            script = write_provider_package(resolved)
            runner = FakeRunner(repo, CODEX_IDLE)
            runner.responses[("bash", "-lc", "command -v -- codex")] = CommandResult(
                (), 0, "/home/tarkan/.local/bin/codex\n", ""
            )
            runner.responses[("bash", "-lc", "command -v -- npm")] = CommandResult((), 0, "/usr/bin/npm\n", "")
            runner.responses[("/usr/bin/npm", "root", "-g")] = CommandResult(
                (), 0, f"{resolved / 'node_modules'}\n", ""
            )
            runner.responses[("cat", "/proc/1234/cmdline")] = CommandResult((), 0, f"node\0{script}\0", "")
            stdout = io.StringIO()
            code = main(
                [
                    "trust-roots",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--json",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(
                payload["suggestions"][0]["provider_root"],
                str(resolved / "node_modules" / "@openai" / "codex"),
            )

    def test_trust_roots_refuses_global_npm_anchor_outside_live_launcher_root(self):
        with tempfile.TemporaryDirectory() as repo:
            resolved = Path(repo).resolve()
            script = write_provider_package(resolved)
            runner = FakeRunner(repo, CODEX_IDLE)
            runner.responses[("bash", "-lc", "command -v -- codex")] = CommandResult(
                (), 0, "/home/tarkan/.local/bin/codex\n", ""
            )
            runner.responses[("bash", "-lc", "command -v -- npm")] = CommandResult((), 0, "/tmp/npm\n", "")
            runner.responses[("/tmp/npm", "root", "-g")] = CommandResult(
                (), 0, f"{resolved / 'node_modules'}\n", ""
            )
            runner.responses[("cat", "/proc/1234/cmdline")] = CommandResult((), 0, f"node\0{script}\0", "")
            stdout = io.StringIO()
            code = main(
                [
                    "trust-roots",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--json",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_DISCOVERY)
            self.assertEqual(payload["status"], "refused")

    def test_pending_composer_clears_before_send(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    "previous assistant output\n\n\u203a already typed by user\n  gpt-5.5 xhigh · /tmp/project\n",
                    "previous assistant output\n\n\u203a already typed by user\n  gpt-5.5 xhigh · /tmp/project\n",
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_pending_contact(),
                    f"{guarded_line()}\n{CODEX_IDLE}",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertEqual(payload["pane_state"], "pending_user_text")
            self.assertTrue(any(call[0] == ("agent-tmux", "clear-input", "codex-demo") for call in runner.calls))
            self.assertTrue(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))

    def test_dry_run_reports_clear_path_for_matching_pending_guarded_contact(self):
        message = "Continue next smallest 3dSculptTool slice."
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, codex_plan_mode_pending_contact(message))
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    message,
                    "--dry-run",
                    "--json",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "would_clear_and_send")
            self.assertEqual(payload["clear_command"], "agent-tmux clear-input codex-demo")
            self.assertEqual(payload["pane_state"], "pending_user_text")
            self.assertFalse(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))
            self.assertFalse(any(call[0][:2] == ("tmux", "paste-buffer") for call in runner.calls))
            self.assertFalse(any(call[0][:3] == ("tmux", "send-keys", "-t") for call in runner.calls))

    def test_real_send_clears_matching_pending_guarded_contact_and_sends_fresh(self):
        message = "Continue next smallest 3dSculptTool slice."
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    codex_plan_mode_pending_contact(message),
                    codex_plan_mode_pending_contact(message),
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_pending_contact(message),
                    f"{guarded_line(message)}\n{CODEX_IDLE}",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertEqual(payload["contact_id"], "AC-TEST")
            self.assertTrue(payload["delivery_proven"])
            self.assertTrue(any(call[0] == ("agent-tmux", "clear-input", "codex-demo") for call in runner.calls))
            self.assertTrue(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))
            self.assertTrue(any(call[0][:2] == ("tmux", "paste-buffer") for call in runner.calls))
            self.assertTrue(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_pending_guarded_contact_with_different_message_clears_before_send(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    codex_plan_mode_pending_contact("old message"),
                    codex_plan_mode_pending_contact("old message"),
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_pending_contact("new message"),
                    f"{guarded_line('new message')}\n{CODEX_IDLE}",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "new message",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertEqual(payload["pane_state"], "pending_user_text")
            self.assertTrue(any(call[0] == ("agent-tmux", "clear-input", "codex-demo") for call in runner.calls))
            self.assertTrue(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))
            self.assertTrue(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_dry_run_reports_clear_path_for_claude_v2_pending_guarded_contact_with_hidden_space_wrap(self):
        message = "alpha beta"
        pending = claude_v2_pending_contact_with_hidden_space_wrap(message)
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, pending, provider="claude", cursor_line_index=3, cursor_x=55)
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "claude",
                    "--message",
                    message,
                    "--dry-run",
                    "--json",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "would_clear_and_send")
            self.assertEqual(payload["clear_command"], "agent-tmux clear-input claude-demo")
            self.assertEqual(payload["pane_state"], "pending_user_text")
            self.assertFalse(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))
            self.assertFalse(any(call[0][:3] == ("tmux", "send-keys", "-t") for call in runner.calls))

    def test_dry_run_reports_clear_path_for_claude_ticket_payload_with_working_wrapped_continuation(self):
        message = (
            "Ticket #126 for project SkillPackagingDiscipline: http://127.0.0.1:8765/task/126\n"
            "Use `agent-ticket show 126` for full title/body. If taking it, move to 'Agent "
            "working', work from SOURCE, validate exact request, comment evidence, run "
            "`agent-ticket closeout-check 126 --strict`, then close."
        )
        contact_id = "AC-20260519T002857Z-0dae3206"
        live_wrapped_lines = [
            f'CONTACT_ID: {contact_id} MESSAGE_JSON: "Ticket #126 for',
            "project SkillPackagingDiscipline: http://127.0.0.1:8765/task/126\\nUse",
            "`agent-ticket show 126` for full title/body. If taking it, move to 'Agent",
            "working', work from SOURCE, validate exact request, comment evidence, run",
            "`agent-ticket closeout-check 126 --strict`, then close.\"",
        ]
        capture = claude_v2_wrapped_lines(live_wrapped_lines)
        cursor_index = next(index for index, line in enumerate(capture.splitlines()) if "working', work" in line)
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                capture,
                provider="claude",
                cursor_line_index=cursor_index,
                cursor_x=58,
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "claude",
                    "--message",
                    message,
                    "--dry-run",
                    "--json",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "would_clear_and_send")
            self.assertEqual(payload["pane_state"], "pending_user_text")
            self.assertEqual(payload["clear_command"], "agent-tmux clear-input claude-demo")
            self.assertFalse(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))
            self.assertFalse(any(call[0][:3] == ("tmux", "send-keys", "-t") for call in runner.calls))

    def test_dry_run_reports_clear_path_for_current_live_pending_guarded_contact_without_footer(self):
        message = (
            "Continue from the current clean local HEAD. Do not push and do not add a remote. Determine the "
            "next smallest production slice from the approved plan after the shared Standard/Sculpt substrate. "
            "Before touching code, read the code map, planning artifacts, donor routes, harness docs, OSTM "
            "requirements, and Rewind readiness. Avoid brush-family breadth unless the plan and donor-backed slice "
            "readiness prove it is now the next smallest safe step; if the next slice is a proof/verification or "
            "high-poly substrate step instead, choose that. Use OSTM/harness evidence, code-map drift/schema "
            "validation, planning guard, build, CTest, and diff hygiene. Commit only a verified local slice with "
            "Commit-Origin: agent-slice, then stop and report changed files, validation commands, OSTM job/artifact "
            "paths, commit id, and launch command."
        )
        contact_id = "AC-20260517T005132Z-89849e8d"
        live_wrapped_lines = [
            f'CONTACT_ID: {contact_id} MESSAGE_JSON: "Continue from the',
            "current clean local HEAD. Do not push and do not add a remote. Determine the",
            "next smallest production slice from the approved plan after the shared",
            "Standard/Sculpt substrate. Before touching code, read the code map, planning",
            "artifacts, donor routes, harness docs, OSTM requirements, and Rewind",
            "readiness. Avoid brush-family breadth unless the plan and donor-backed slice",
            "readiness prove it is now the next smallest safe step; if the next slice is a",
            "proof/verification or high-poly substrate step instead, choose that. Use",
            "OSTM/harness evidence, code-map drift/schema validation, planning guard,",
            "build, CTest, and diff hygiene. Commit only a verified local slice with",
            "Commit-Origin: agent-slice, then stop and report changed files, validation",
            "commands, OSTM job/artifact paths, commit id, and launch command.\"",
        ]
        capture = codex_plan_mode_wrapped_lines_without_footer(live_wrapped_lines)
        plan_hint_index = next(
            index for index, line in enumerate(capture.splitlines()) if "Create a plan?" in line
        )
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, capture, cursor_line_index=plan_hint_index)
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    message,
                    "--dry-run",
                    "--json",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "would_clear_and_send")
            self.assertEqual(payload["pane_state"], "pending_user_text")
            self.assertEqual(payload["clear_command"], "agent-tmux clear-input codex-demo")
            self.assertFalse(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))
            self.assertFalse(any(call[0][:2] == ("tmux", "paste-buffer") for call in runner.calls))
            self.assertFalse(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_dry_run_reports_clear_path_for_duplicated_pending_guarded_residue(self):
        message = "Continue next smallest 3dSculptTool implementation slice."
        contact_id = "AC-20260519T035916Z-4425d81a"
        first = guarded_line(message, contact_id=contact_id)
        duplicated_capture = codex_plan_mode_wrapped_lines_without_footer([first, first])
        plan_hint_index = next(
            index for index, line in enumerate(duplicated_capture.splitlines()) if "Create a plan?" in line
        )
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, duplicated_capture, cursor_line_index=plan_hint_index)
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    message,
                    "--dry-run",
                    "--json",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "would_clear_and_send")
            self.assertEqual(payload["clear_command"], "agent-tmux clear-input codex-demo")
            self.assertEqual(payload["pane_state"], "pending_user_text")
            self.assertFalse(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))
            self.assertFalse(any(call[0][:2] == ("tmux", "paste-buffer") for call in runner.calls))
            self.assertFalse(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_real_send_clears_split_guarded_residue_before_fresh_send(self):
        message = (
            "Continue from the current clean local HEAD. Determine the next smallest production slice, "
            "validate exact behavior, and report commands."
        )
        stale_contact_id = "AC-20260519T035916Z-4425d81a"
        live_wrapped_lines = [
            f'CONTACT_ID: {stale_contact_id} MESSAGE_JSON: "Continue from the',
            "current clean local HEAD. Determine the next smallest production slice,",
            "validate exact behavior, and report commands.\"",
        ]
        split_capture = codex_plan_mode_wrapped_lines_without_footer(live_wrapped_lines)
        plan_hint_index = next(
            index for index, line in enumerate(split_capture.splitlines()) if "Create a plan?" in line
        )
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    split_capture,
                    split_capture,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_pending_contact(message),
                    f"{guarded_line(message)}\n{CODEX_IDLE}",
                ],
                cursor_line_indexes=[plan_hint_index, plan_hint_index, 2, 2, 2, 2, 3],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertEqual(payload["contact_id"], "AC-TEST")
            self.assertEqual(payload["pane_state"], "pending_user_text")
            self.assertTrue(any(call[0] == ("agent-tmux", "clear-input", "codex-demo") for call in runner.calls))
            self.assertTrue(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))
            self.assertTrue(any(call[0][:2] == ("tmux", "paste-buffer") for call in runner.calls))
            self.assertTrue(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_agent_tmux_invalid_session_name_reports_structured_capture_error(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, CODEX_IDLE)
            runner.responses[("tmux", "list-panes", "-a", "-F", PANE_FORMAT)] = CommandResult(
                (), 0, pane_line("codex demo", "%1", repo), ""
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_TRANSPORT)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(payload["stage"], "capture")
            self.assertIn("session name must match", payload["reason"])

    def test_prompt_text_without_cursor_on_prompt_refuses_before_send(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, CODEX_IDLE, cursor_line_index=0)
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_REFUSED)
            self.assertEqual(payload["status"], "refused")
            self.assertEqual(payload["pane_state"], "dead_or_unknown")
            self.assertFalse(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))

    def test_real_send_refuses_attached_session_without_clearing_composer(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                "previous assistant output\n\n\u203a attached session draft\n  gpt-5.5 xhigh · /tmp/project\n",
            )
            runner.responses[("tmux", "list-panes", "-a", "-F", PANE_FORMAT)] = CommandResult(
                (), 0, pane_line("codex-demo", "%1", repo, attached=1), ""
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_REFUSED)
            self.assertEqual(payload["stage"], "attached_session")
            self.assertEqual(payload["pane_state"], "pending_user_text")
            self.assertFalse(any(call[0] == ("agent-tmux", "clear-input", "codex-demo") for call in runner.calls))
            self.assertFalse(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))

    def test_dry_run_refuses_attached_session_to_avoid_misleading_acceptance(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, CODEX_IDLE)
            runner.responses[("tmux", "list-panes", "-a", "-F", PANE_FORMAT)] = CommandResult(
                (), 0, pane_line("codex-demo", "%1", repo, attached=1), ""
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--dry-run",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_REFUSED)
            self.assertEqual(payload["stage"], "attached_session")
            self.assertFalse(any(call[0] == ("agent-tmux", "clear-input", "codex-demo") for call in runner.calls))
            self.assertFalse(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))

    def test_working_state_refuses_without_clearing_or_sending(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                "Working for 12s\nRunning tests\n\n\u203a stale visible input\n  gpt-5.5 xhigh · /tmp/project\n",
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_REFUSED)
            self.assertEqual(payload["status"], "refused")
            self.assertEqual(payload["stage"], "pre_send_state")
            self.assertEqual(payload["pane_state"], "agent_working")
            self.assertFalse(any(call[0] == ("agent-tmux", "clear-input", "codex-demo") for call in runner.calls))
            self.assertFalse(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))

    def test_control_character_message_refuses_before_discovery(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, CODEX_IDLE)
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello\x1b[201~whoops",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_REFUSED)
            self.assertEqual(payload["stage"], "message")
            self.assertIn("bracketed paste", payload["reason"])
            self.assertFalse(any(call[0][:2] == ("tmux", "list-panes") for call in runner.calls))

    def test_c0_control_message_refuses_before_discovery(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, CODEX_IDLE)
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello\x00whoops",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_REFUSED)
            self.assertEqual(payload["stage"], "message")
            self.assertIn("U+0000", payload["reason"])
            self.assertFalse(any(call[0][:2] == ("tmux", "list-panes") for call in runner.calls))

    def test_ambiguous_panes_refuse_before_capture(self):
        with tempfile.TemporaryDirectory() as repo:
            resolved = Path(repo).resolve()
            runner = FakeRunner(repo, CODEX_IDLE)
            script = write_provider_package(resolved)
            runner.responses[("tmux", "list-panes", "-a", "-F", PANE_FORMAT)] = CommandResult(
                (),
                0,
                pane_line("codex-a", "%1", resolved, pid=111)
                + pane_line("codex-b", "%2", resolved, pid=222),
                "",
            )
            runner.responses[("ps", "-p", "111", "-o", "args=")] = CommandResult(
                (), 0, f"node {script}\n", ""
            )
            runner.responses[("ps", "-p", "222", "-o", "args=")] = CommandResult(
                (), 0, f"node {script}\n", ""
            )
            runner.responses[("ps", "-t", "/dev/pts/7", "-o", "pid=,ppid=,pgid=,stat=,args=")] = CommandResult(
                (), 0, f"111 1 111 Sl+ node {script}\n", ""
            )
            runner.responses[("cat", "/proc/111/cmdline")] = CommandResult((), 0, f"node\0{script}\0", "")
            runner.responses[("readlink", "-f", "/proc/111/exe")] = CommandResult((), 0, "/usr/bin/node\n", "")
            runner.responses[("cat", "/proc/111/environ")] = CommandResult((), 0, "PATH=/usr/bin\0", "")
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_DISCOVERY)
            self.assertEqual(payload["stage"], "discovery")
            self.assertFalse(any(call[0][:2] == ("tmux", "capture-pane") for call in runner.calls))

    def test_real_send_targets_locked_pane_id(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_pending_contact(),
                    f"{guarded_line()}\n{CODEX_IDLE}",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(
                any(
                    call[0][:4] == ("tmux", "paste-buffer", "-d", "-r")
                    and call[0][-2:] == ("-t", "%1")
                    for call in runner.calls
                )
            )
            self.assertTrue(
                any(
                    call[0][:4] == ("tmux", "paste-buffer", "-d", "-r")
                    and "-b" in call[0]
                    for call in runner.calls
                )
            )

    def test_real_send_pastes_single_line_message_json(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_pending_contact("hello\nworld"),
                    guarded_line("hello\nworld") + "\n" + CODEX_IDLE,
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello\nworld",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            self.assertEqual(code, EXIT_OK)
            load_inputs = [
                call[1]
                for call in runner.calls
                if call[0][:3] == ("tmux", "load-buffer", "-b")
            ]
            self.assertEqual(len(load_inputs), 1)
            self.assertNotIn("\n", load_inputs[0])
            self.assertIn('MESSAGE_JSON: "hello\\nworld"', load_inputs[0])

    def test_process_drift_after_recapture_refuses_before_send(self):
        with tempfile.TemporaryDirectory() as repo:
            resolved = Path(repo).resolve()
            runner = FakeRunner(
                repo,
                [CODEX_IDLE, CODEX_IDLE],
                display_messages=[
                    CommandResult((), 0, pane_line("codex-demo", "%1", resolved), ""),
                    CommandResult((), 0, pane_line("codex-demo", "%1", resolved, command="bash"), ""),
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_REFUSED)
            self.assertEqual(payload["status"], "refused")
            self.assertEqual(payload["stage"], "pre_send_revalidate")
            self.assertFalse(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))

    def test_process_drift_inside_transport_before_paste_refuses_without_paste(self):
        with tempfile.TemporaryDirectory() as repo:
            resolved = Path(repo).resolve()
            runner = FakeRunner(
                repo,
                [CODEX_IDLE, CODEX_IDLE, CODEX_IDLE],
                display_messages=[
                    CommandResult((), 0, pane_line("codex-demo", "%1", resolved), ""),
                    CommandResult((), 0, pane_line("codex-demo", "%1", resolved), ""),
                    CommandResult((), 0, pane_line("codex-demo", "%1", resolved, command="bash"), ""),
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_REFUSED)
            self.assertEqual(payload["status"], "refused")
            self.assertEqual(payload["stage"], "pre_send_revalidate")
            self.assertTrue(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))
            self.assertTrue(any(call[0][:3] == ("tmux", "delete-buffer", "-b") for call in runner.calls))
            self.assertFalse(any(call[0][:2] == ("tmux", "paste-buffer") for call in runner.calls))

    def test_process_drift_inside_transport_before_submit_reports_unsubmitted(self):
        with tempfile.TemporaryDirectory() as repo:
            resolved = Path(repo).resolve()
            runner = FakeRunner(
                repo,
                [CODEX_IDLE, CODEX_IDLE, CODEX_IDLE, CODEX_IDLE, f"CONTACT_ID: AC-TEST\nhello\n{CODEX_IDLE}"],
                display_messages=[
                    CommandResult((), 0, pane_line("codex-demo", "%1", resolved), ""),
                    CommandResult((), 0, pane_line("codex-demo", "%1", resolved), ""),
                    CommandResult((), 0, pane_line("codex-demo", "%1", resolved), ""),
                    CommandResult((), 0, pane_line("codex-demo", "%1", resolved, command="bash"), ""),
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_TRANSPORT)
            self.assertEqual(payload["status"], "mutated_unsubmitted")
            self.assertEqual(payload["stage"], "submit")
            self.assertIn("pre-submit revalidation failed", payload["reason"])
            self.assertTrue(any(call[0][:2] == ("tmux", "paste-buffer") for call in runner.calls))
            self.assertFalse(any(call[0][:3] == ("tmux", "send-keys", "-t") for call in runner.calls))

    def test_pre_submit_contact_id_must_be_in_current_composer_prompt(self):
        contaminated = (
            "previous assistant output\n\n"
            "\u203a unrelated draft\n"
            "  gpt-5.5 xhigh · /tmp/project\n"
            "CONTACT_ID: AC-TEST MESSAGE_JSON: \"hello\"\n"
        )
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [CODEX_IDLE, CODEX_IDLE, CODEX_IDLE, CODEX_IDLE] + [contaminated] * 6,
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_TRANSPORT)
            self.assertEqual(payload["status"], "mutated_unsubmitted")
            self.assertEqual(payload["stage"], "submit")
            self.assertIn("current composer prompt body", payload["reason"])
            self.assertTrue(any(call[0][:2] == ("tmux", "paste-buffer") for call in runner.calls))
            self.assertFalse(any(call[0] == ("agent-tmux", "clear-input", "codex-demo") for call in runner.calls))
            self.assertFalse(any(call[0][:3] == ("tmux", "send-keys", "-t") for call in runner.calls))

    def test_pre_submit_requires_full_guarded_message_json_in_current_composer(self):
        truncated = "previous assistant output\n\n\u203a CONTACT_ID: AC-TEST\n  gpt-5.5 xhigh · /tmp/project\n"
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [CODEX_IDLE, CODEX_IDLE, CODEX_IDLE, CODEX_IDLE] + [truncated] * 6,
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_TRANSPORT)
            self.assertEqual(payload["status"], "mutated_unsubmitted")
            self.assertEqual(payload["stage"], "submit")
            self.assertIn("full guarded contact line", payload["reason"])
            self.assertTrue(any(call[0][:2] == ("tmux", "paste-buffer") for call in runner.calls))
            self.assertFalse(any(call[0][:3] == ("tmux", "send-keys", "-t") for call in runner.calls))

    def test_pre_submit_waits_for_delayed_paste_render_before_enter(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_pending_contact(),
                    f"{guarded_line()}\n{CODEX_IDLE}",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(any(call[0][:3] == ("tmux", "send-keys", "-t") for call in runner.calls))

    def test_pre_submit_accepts_current_prompt_when_old_prompt_marker_is_visible(self):
        current_with_old_prompt = (
            "older assistant output\n\n"
            "\u203a old visible request\n"
            "  gpt-5.5 xhigh · /tmp/project\n"
            "new assistant output\n\n"
            f"\u203a {guarded_line()}\n"
            "  gpt-5.5 xhigh · /tmp/project\n"
        )
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    current_with_old_prompt,
                    f"{guarded_line()}\n{CODEX_IDLE}",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")

    def test_pre_submit_accepts_wrapped_guarded_line_before_enter(self):
        long_message = "wrapped-" * 14
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_wrapped_pending_contact(long_message, width=32),
                    wrapped_guarded_echo(long_message, width=32) + "\n" + CODEX_IDLE,
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    long_message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(payload["delivery_proven"])

    def test_pre_submit_accepts_codex_wrap_that_hides_boundary_space(self):
        message = "alpha beta"
        line = guarded_line(message)
        split_index = line.index(" beta")
        wrapped_with_hidden_space = (
            "previous assistant output\n\n"
            f"\u203a {line[:split_index]}\n"
            f"{line[split_index + 1:]}\n"
            "  gpt-5.5 xhigh · /tmp/project\n"
        )
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    wrapped_with_hidden_space,
                    f"{line}\n{CODEX_IDLE}",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")

    def test_pre_submit_accepts_codex_collapsed_pasted_content_before_enter(self):
        long_message = "collapsed-" * 90
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_collapsed_pasted_contact(long_message),
                    f"{guarded_line(long_message)}\n{CODEX_IDLE}",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    long_message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(any(call[0][:3] == ("tmux", "send-keys", "-t") for call in runner.calls))

    def test_codex_oversized_payload_uses_literal_chunks_before_enter(self):
        long_message = "chunked-" * 190
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_wrapped_pending_contact(long_message, width=96),
                    wrapped_guarded_echo(long_message, width=96) + "\n" + CODEX_IDLE,
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    long_message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            literal_calls = [
                call for call in runner.calls if call[0][:5] == ("tmux", "send-keys", "-t", "%1", "-l")
            ]
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertGreater(len(literal_calls), 1)
            self.assertTrue(all(call[0][5] == "--" for call in literal_calls))
            self.assertTrue(all(len(call[0][6]) <= 200 for call in literal_calls))
            self.assertFalse(any(call[0][:2] == ("tmux", "paste-buffer") for call in runner.calls))
            self.assertTrue(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_codex_literal_chunks_use_option_terminator_for_dash_prefixed_chunks(self):
        prefix = 'CONTACT_ID: AC-TEST MESSAGE_JSON: "'
        message = ("x" * (200 - len(prefix))) + "-r should stay literal " + ("z" * 900)
        self.assertEqual(guarded_line(message)[200:202], "-r")
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_wrapped_pending_contact(message, width=96),
                    wrapped_guarded_echo(message, width=96) + "\n" + CODEX_IDLE,
                ],
                fail_dash_literal_without_option_terminator=True,
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            literal_calls = [
                call for call in runner.calls if call[0][:5] == ("tmux", "send-keys", "-t", "%1", "-l")
            ]
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(all(call[0][5] == "--" for call in literal_calls))

    def test_codex_plan_mode_hint_does_not_block_long_literal_submit(self):
        long_message = "plan-mode-" * 190
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_plan_mode_pending_contact(long_message),
                    f"{guarded_line(long_message)}\n{CODEX_IDLE}",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    long_message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            literal_calls = [
                call for call in runner.calls if call[0][:5] == ("tmux", "send-keys", "-t", "%1", "-l")
            ]
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertGreater(len(literal_calls), 1)
            self.assertTrue(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_pre_submit_waits_for_live_codex_long_plan_mode_render_before_enter(self):
        long_message = (
            "Continue from clean HEAD 879e461 with the next smallest high-value 3dSculptTool slice. "
            "Before editing, re-open the current plan packet, code map/project memory, CppStudio route, "
            "Rewind, OSTM/control harness, GUI/donor notes, and the relevant sculpt/viewport donor references. "
            "Use donor-first behavior for sculpt/brush/viewport choices; if local donors are insufficient, "
            "do focused web/upstream research and record the sources. Pick one bounded slice only, preferably "
            "real sculpting or viewport behavior over cosmetic polish if the plan supports it. Use the updated "
            "OSTM contract: do not run OSTM --mode real-input or any intrusive desktop-input path unless you "
            "stop and request explicit supervisor/user approval for that exact intrusive run. Prefer "
            "non-intrusive control-harness/readback/offscreen paths. Capture before evidence, implement, then "
            "prove exact behavior with before-after evidence, screenshots/readbacks, and explicit comparison. "
            "Update code map/docs if routes drift. Run build, CTest, planning guard, code-map drift+validation, "
            "Rewind ready, relevant non-intrusive OSTM/control proof, screenshot inspection, diff hygiene, then "
            "commit with Commit-Origin: agent-slice. If a tool/harness path behaves unexpectedly, stop and "
            "classify it instead of silently working around it. Stop after final summary and include the launch command."
        )
        live_wrapped_lines = [
            'CONTACT_ID: AC-TEST MESSAGE_JSON: "Continue from clean',
            "HEAD 879e461 with the next smallest high-value 3dSculptTool slice. Before",
            "editing, re-open the current plan packet, code map/project memory, CppStudio",
            "route, Rewind, OSTM/control harness, GUI/donor notes, and the relevant",
            "sculpt/viewport donor references. Use donor-first behavior for sculpt/brush/",
            "viewport choices; if local donors are insufficient, do focused web/upstream",
            "research and record the sources. Pick one bounded slice only, preferably real",
            "sculpting or viewport behavior over cosmetic polish if the plan supports it.",
            "Use the updated OSTM contract: do not run OSTM --mode real-input or any",
            "intrusive desktop-input path unless you stop and request explicit supervisor/",
            "user approval for that exact intrusive run. Prefer non-intrusive control-",
            "harness/readback/offscreen paths. Capture before evidence, implement, then",
            "prove exact behavior with before-after evidence, screenshots/readbacks, and",
            "explicit comparison. Update code map/docs if routes drift. Run build, CTest,",
            "planning guard, code-map drift+validation, Rewind ready, relevant non-",
            "intrusive OSTM/control proof, screenshot inspection, diff hygiene, then",
            "commit with Commit-Origin: agent-slice. If a tool/harness path behaves",
            "unexpectedly, stop and classify it instead of silently working around it.",
            'Stop after final summary and include the launch command."',
        ]
        partial_renders = [
            codex_plan_mode_wrapped_lines(live_wrapped_lines[:count])
            for count in range(1, 7)
        ]
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    *partial_renders,
                    codex_plan_mode_wrapped_lines(live_wrapped_lines),
                    f"{guarded_line(long_message)}\n{CODEX_IDLE}",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    long_message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            literal_calls = [
                call for call in runner.calls if call[0][:5] == ("tmux", "send-keys", "-t", "%1", "-l")
            ]
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(payload["delivery_proven"])
            self.assertGreater(len(literal_calls), 1)
            self.assertTrue(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_post_send_waits_for_delayed_codex_working_echo_after_long_submit(self):
        long_message = (
            "Blocking visible viewport bug. Do not patch first. Reproduce with app-owned viewport/OSTM before "
            "evidence: Standard/Sculpt stroke is not tracking mouse drag direction/path, and product viewport "
            "looks like orange/red paint on the sphere. Prior green checks are insufficient: they proved "
            "checksum/revision changes, not spatial correctness or product visual semantics. Load CppStudio, "
            "viewport-session-testing, native-cpp-gui-hud, systematic-debugging, OSTM, code-map/watchlist. "
            "Gate Rewind/code-map first. Capture before/mid/after screenshots plus mouse positions, screen drag "
            "vector, ray/hit points, affected vertex/delta path, and color/material readback. Write why old "
            "verification missed it. Fix only Standard/Sculpt stroke/path and/or debug/product overlay. No extra "
            "brushes/CUDA/topology/import/export/broad UI. After: same/equivalent viewport proof must show "
            "deformation follows mouse path and no red/orange paint-looking product overlay unless debug-only "
            "and disabled. Rerun Standard stroke, viewport-session, product-surface smokes. Update docs/map/"
            "watchlist if changed. Do not commit. Final include artifact paths and launch command."
        )
        submitted_working = (
            f"{guarded_line(long_message)}\n\n"
            "• Working (1s • esc to interrupt)\n"
        )
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_plan_mode_pending_contact(long_message),
                    CODEX_STARTER,
                    submitted_working,
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    long_message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            literal_calls = [
                call for call in runner.calls if call[0][:5] == ("tmux", "send-keys", "-t", "%1", "-l")
            ]
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(payload["delivery_proven"])
            self.assertEqual(payload["post_send_state"], "agent_working")
            self.assertGreater(len(literal_calls), 1)
            self.assertTrue(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_post_send_proves_agent_working_after_pre_submit_guard_without_visible_echo(self):
        long_message = (
            "Ticket #151 reopened exact path. Long guarded supervisor payload for a Codex worker: use source only, "
            "validate the exact requested behavior, comment evidence before closing, keep Rewind coverage, and do "
            "not use raw tmux fallback. This text is intentionally long enough to use literal chunked input and to "
            "make the submitted prompt likely to scroll out of the post-send readback once the worker starts."
        ) * 4
        working_without_visible_contact = "• Working (1s • esc to interrupt)\n"
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_plan_mode_pending_contact(long_message),
                    working_without_visible_contact,
                    working_without_visible_contact,
                    working_without_visible_contact,
                    working_without_visible_contact,
                    working_without_visible_contact,
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    long_message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            literal_calls = [
                call for call in runner.calls if call[0][:5] == ("tmux", "send-keys", "-t", "%1", "-l")
            ]
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(payload["delivery_proven"])
            self.assertEqual(payload["post_send_state"], "agent_working")
            self.assertFalse(payload["post_send_guarded_contact_visible"])
            self.assertTrue(payload["pre_submit_contact_proven"])
            self.assertIn("pre-submit", payload["delivery_proof_reason"])
            self.assertGreater(len(literal_calls), 1)
            self.assertTrue(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_pre_submit_failure_clears_own_literal_guarded_residue(self):
        long_message = (
            "Ticket #150 long Codex send repro. "
            "This payload is intentionally long enough to use literal chunk input and then render only a split "
            "fragment before submit, matching the guarded-contact failure mode where Codex leaves the composer "
            "contaminated with an unsubmitted CONTACT_ID/MESSAGE_JSON payload. "
        ) * 8
        guarded = guarded_line(long_message)
        split_residue = codex_plan_mode_wrapped_lines(
            [
                guarded[:84],
                guarded[84:168],
                guarded[168:252],
            ]
        )
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    split_residue,
                    split_residue,
                    split_residue,
                    split_residue,
                    split_residue,
                    split_residue,
                    CODEX_IDLE,
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    long_message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_TRANSPORT)
            self.assertEqual(payload["status"], "mutated_unsubmitted")
            self.assertEqual(payload["stage"], "submit")
            self.assertEqual(payload["recovery"], "cleared_own_guarded_payload")
            self.assertEqual(payload["pane_state"], "idle_empty_prompt")
            self.assertFalse(payload["delivery_proven"])
            self.assertTrue(any(call[0] == ("agent-tmux", "clear-input", "codex-demo") for call in runner.calls))
            self.assertFalse(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_pre_submit_accepts_current_live_plan_mode_residue_without_footer_before_enter(self):
        message = (
            "Continue from the current clean local HEAD. Do not push and do not add a remote. Determine the "
            "next smallest production slice from the approved plan after the shared Standard/Sculpt substrate. "
            "Before touching code, read the code map, planning artifacts, donor routes, harness docs, OSTM "
            "requirements, and Rewind readiness. Avoid brush-family breadth unless the plan and donor-backed slice "
            "readiness prove it is now the next smallest safe step; if the next slice is a proof/verification or "
            "high-poly substrate step instead, choose that. Use OSTM/harness evidence, code-map drift/schema "
            "validation, planning guard, build, CTest, and diff hygiene. Commit only a verified local slice with "
            "Commit-Origin: agent-slice, then stop and report changed files, validation commands, OSTM job/artifact "
            "paths, commit id, and launch command."
        )
        contact_id = "AC-20260517T005132Z-89849e8d"
        live_wrapped_lines = [
            f'CONTACT_ID: {contact_id} MESSAGE_JSON: "Continue from the',
            "current clean local HEAD. Do not push and do not add a remote. Determine the",
            "next smallest production slice from the approved plan after the shared",
            "Standard/Sculpt substrate. Before touching code, read the code map, planning",
            "artifacts, donor routes, harness docs, OSTM requirements, and Rewind",
            "readiness. Avoid brush-family breadth unless the plan and donor-backed slice",
            "readiness prove it is now the next smallest safe step; if the next slice is a",
            "proof/verification or high-poly substrate step instead, choose that. Use",
            "OSTM/harness evidence, code-map drift/schema validation, planning guard,",
            "build, CTest, and diff hygiene. Commit only a verified local slice with",
            "Commit-Origin: agent-slice, then stop and report changed files, validation",
            "commands, OSTM job/artifact paths, commit id, and launch command.\"",
        ]
        capture = codex_plan_mode_wrapped_lines_without_footer(live_wrapped_lines)
        plan_hint_index = next(
            index for index, line in enumerate(capture.splitlines()) if "Create a plan?" in line
        )
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    capture,
                    f"{guarded_line(message, contact_id=contact_id)}\n{CODEX_IDLE}",
                ],
                cursor_line_indexes=[2, 2, 2, 2, plan_hint_index, 3],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    message,
                    "--json",
                    "--contact-id",
                    contact_id,
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(payload["delivery_proven"])
            self.assertTrue(any(call[0][:4] == ("tmux", "paste-buffer", "-d", "-r") for call in runner.calls))
            self.assertFalse(any(call[0][:5] == ("tmux", "send-keys", "-t", "%1", "-l") for call in runner.calls))
            self.assertTrue(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_codex_plan_mode_hint_does_not_block_short_paste_submit(self):
        message = "Continue next smallest 3dSculptTool slice."
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_plan_mode_pending_contact(message),
                    f"{guarded_line(message)}\n{CODEX_IDLE}",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(any(call[0][:4] == ("tmux", "paste-buffer", "-d", "-r") for call in runner.calls))
            self.assertFalse(any(call[0][:5] == ("tmux", "send-keys", "-t", "%1", "-l") for call in runner.calls))
            self.assertTrue(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_pre_submit_rejects_codex_collapsed_pasted_content_with_wrong_count(self):
        long_message = "collapsed-" * 90
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [CODEX_IDLE, CODEX_IDLE, CODEX_IDLE, CODEX_IDLE] + [codex_collapsed_pasted_contact(long_message, count_delta=1)] * 6,
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    long_message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_TRANSPORT)
            self.assertEqual(payload["status"], "mutated_unsubmitted")
            self.assertEqual(payload["stage"], "submit")
            self.assertIn("full guarded contact line", payload["reason"])
            self.assertFalse(any(call[0][:3] == ("tmux", "send-keys", "-t") for call in runner.calls))

    def test_pre_submit_accepts_claude_wrapped_guarded_line_with_cursor_on_continuation(self):
        long_message = "wrapped-" * 14
        pre_submit = claude_wrapped_pending_contact(long_message, width=32)
        post_send = wrapped_guarded_echo(long_message, width=32) + "\n" + CLAUDE_IDLE
        pre_submit_cursor = next(index for index, line in enumerate(pre_submit.splitlines()) if "\u258c" in line)
        post_send_cursor = next(index for index, line in enumerate(post_send.splitlines()) if "\u258c" in line)
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CLAUDE_IDLE,
                    CLAUDE_IDLE,
                    CLAUDE_IDLE,
                    CLAUDE_IDLE,
                    pre_submit,
                    post_send,
                ],
                provider="claude",
                cursor_line_indexes=[2, 2, 2, 2, pre_submit_cursor, post_send_cursor],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "claude",
                    "--message",
                    long_message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(payload["delivery_proven"])

    def test_real_send_to_claude_v2_idle_prompt_proves_delivery(self):
        post_send = guarded_line() + "\n" + CLAUDE_V2_IDLE
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CLAUDE_V2_IDLE,
                    CLAUDE_V2_IDLE,
                    CLAUDE_V2_IDLE,
                    CLAUDE_V2_IDLE,
                    claude_wrapped_pending_contact("hello", width=120),
                    post_send,
                ],
                provider="claude",
                cursor_line_indexes=[2, 2, 2, 2, 2, 3],
                cursor_x_indexes=[2, 2, 2, 2, len(guarded_line()), 2],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "claude",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(payload["delivery_proven"])
            self.assertTrue(any(call[0][:4] == ("tmux", "paste-buffer", "-d", "-r") for call in runner.calls))
            self.assertTrue(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_post_send_proves_claude_v2_wrapped_guarded_prompt_after_response(self):
        message = "alpha beta"
        wrapped_prompt = claude_v2_pending_contact_with_hidden_space_wrap(message)
        post_send = wrapped_prompt + "\n● OK.\n\n✻ Worked for 3s\n\n" + CLAUDE_V2_IDLE
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CLAUDE_V2_IDLE,
                    CLAUDE_V2_IDLE,
                    CLAUDE_V2_IDLE,
                    CLAUDE_V2_IDLE,
                    claude_v2_pending_contact_with_hidden_space_wrap(message),
                    post_send,
                ],
                provider="claude",
                cursor_line_indexes=[2, 2, 2, 2, 3, 13],
                cursor_x_indexes=[2, 2, 2, 2, 55, 2],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "claude",
                    "--message",
                    message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(payload["delivery_proven"])

    def test_pre_submit_accepts_claude_v2_wrap_that_hides_boundary_space(self):
        message = "alpha beta"
        pending = claude_v2_pending_contact_with_hidden_space_wrap(message)
        post_send = guarded_line(message) + "\n" + CLAUDE_V2_IDLE
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CLAUDE_V2_IDLE,
                    CLAUDE_V2_IDLE,
                    CLAUDE_V2_IDLE,
                    CLAUDE_V2_IDLE,
                    pending,
                    post_send,
                ],
                provider="claude",
                cursor_line_indexes=[2, 2, 2, 2, 3, 3],
                cursor_x_indexes=[2, 2, 2, 2, 55, 2],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "claude",
                    "--message",
                    message,
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(payload["delivery_proven"])
            self.assertTrue(any(call[0] == ("tmux", "send-keys", "-t", "%1", "C-m") for call in runner.calls))

    def test_pending_text_inside_transport_before_paste_clears_then_pastes(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    "previous assistant output\n\n\u203a critical user draft\n  gpt-5.5 xhigh · /tmp/project\n",
                    CODEX_IDLE,
                    codex_pending_contact(),
                    f"{guarded_line()}\n{CODEX_IDLE}",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(any(call[0] == ("agent-tmux", "clear-input", "codex-demo") for call in runner.calls))
            self.assertTrue(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))
            self.assertTrue(any(call[0][:2] == ("tmux", "paste-buffer") for call in runner.calls))

    def test_unsafe_post_send_state_is_unproven_even_with_contact_id(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_pending_contact(),
                    f"{guarded_line()}\nplain echo\n",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_UNPROVEN)
            self.assertEqual(payload["status"], "sent_unproven")
            self.assertEqual(payload["post_send_state"], "dead_or_unknown")

    def test_final_recapture_clears_pending_text_before_send(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    "previous assistant output\n\n\u203a final user draft appeared\n  gpt-5.5 xhigh · /tmp/project\n",
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_pending_contact(),
                    f"{guarded_line()}\n{CODEX_IDLE}",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(any(call[0] == ("agent-tmux", "clear-input", "codex-demo") for call in runner.calls))
            self.assertTrue(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))

    def test_recapture_clears_pending_text_after_initial_capture(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    "previous assistant output\n\n\u203a user draft appeared\n  gpt-5.5 xhigh · /tmp/project\n",
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_pending_contact(),
                    f"{guarded_line()}\n{CODEX_IDLE}",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "sent")
            self.assertTrue(any(call[0] == ("agent-tmux", "clear-input", "codex-demo") for call in runner.calls))
            self.assertTrue(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))

    def test_existing_contact_id_before_send_refuses(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, ["previous\nCONTACT_ID: AC-TEST\n\u203a \n  gpt-5.5 xhigh · /tmp/project\n"])
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_REFUSED)
            self.assertEqual(payload["stage"], "contact_id")
            self.assertFalse(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))

    def test_invalid_contact_id_refuses(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, [CODEX_IDLE])
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST with spaces",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_REFUSED)
            self.assertEqual(payload["stage"], "contact_id")

    def test_bare_prompt_glyph_refuses_before_send(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, ["ordinary output\n\u203a \n"])
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_REFUSED)
            self.assertEqual(payload["stage"], "pre_send_state")
            self.assertEqual(payload["pane_state"], "dead_or_unknown")
            self.assertFalse(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))

    def test_bare_prompt_glyph_after_send_is_unproven_even_with_contact_id(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_pending_contact(),
                    f"{guarded_line()}\nordinary output\n\u203a \n",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_UNPROVEN)
            self.assertEqual(payload["status"], "sent_unproven")
            self.assertEqual(payload["post_send_state"], "dead_or_unknown")

    def test_generic_working_after_send_is_unproven_even_with_contact_id(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    CODEX_IDLE,
                    codex_pending_contact(),
                    f"{guarded_line()}\nplain working echo\n",
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_UNPROVEN)
            self.assertEqual(payload["status"], "sent_unproven")
            self.assertFalse(payload["delivery_proven"])

    def test_submit_failure_reports_mutated_unsubmitted(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                repo,
                [CODEX_IDLE, CODEX_IDLE, CODEX_IDLE, CODEX_IDLE, codex_pending_contact()],
                fail_submit=True,
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_TRANSPORT)
            self.assertEqual(payload["status"], "mutated_unsubmitted")
            self.assertEqual(payload["stage"], "submit")
            self.assertFalse(payload["delivery_proven"])
            self.assertTrue(any(call[0][:4] == ("tmux", "paste-buffer", "-d", "-r") for call in runner.calls))

    def test_post_send_revalidation_failure_reports_unproven_not_refused(self):
        with tempfile.TemporaryDirectory() as repo:
            resolved = Path(repo).resolve()
            runner = FakeRunner(
                repo,
                [CODEX_IDLE, CODEX_IDLE, CODEX_IDLE, CODEX_IDLE, codex_pending_contact()],
                display_messages=[
                    CommandResult((), 0, pane_line("codex-demo", "%1", resolved), ""),
                    CommandResult((), 0, pane_line("codex-demo", "%1", resolved), ""),
                    CommandResult((), 0, pane_line("codex-demo", "%1", resolved), ""),
                    CommandResult((), 0, pane_line("codex-demo", "%1", resolved), ""),
                    CommandResult((), 0, pane_line("codex-demo", "%1", resolved, command="bash"), ""),
                ],
            )
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "hello",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_UNPROVEN)
            self.assertEqual(payload["status"], "sent_unproven")
            self.assertEqual(payload["stage"], "post_send_revalidate")
            self.assertFalse(payload["delivery_proven"])
            self.assertTrue(any(call[0][:3] == ("tmux", "load-buffer", "-b") for call in runner.calls))

    def test_paste_failure_deletes_loaded_tmux_buffer(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, [CODEX_IDLE, CODEX_IDLE, CODEX_IDLE, CODEX_IDLE], fail_paste=True)
            stdout = io.StringIO()
            code = main(
                [
                    "send",
                    "--repo",
                    repo,
                    "--provider",
                    "codex",
                    "--message",
                    "secret instruction",
                    "--json",
                    "--contact-id",
                    "AC-TEST",
                ],
                runner=runner,
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_TRANSPORT)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(payload["stage"], "send")
            load_calls = [call for call in runner.calls if call[0][:3] == ("tmux", "load-buffer", "-b")]
            delete_calls = [call for call in runner.calls if call[0][:3] == ("tmux", "delete-buffer", "-b")]
            self.assertEqual(len(load_calls), 1)
            self.assertEqual(len(delete_calls), 1)
            self.assertEqual(delete_calls[0][0][-1], load_calls[0][0][3])


if __name__ == "__main__":
    unittest.main()
