import io
import json
import tempfile
import unittest
from pathlib import Path

from agent_terminal_contact.cli import EXIT_DISCOVERY, EXIT_OK, EXIT_REFUSED, main
from agent_terminal_contact.runner import CommandResult
from agent_terminal_contact.session import SESSION_FORMAT


class FakeRunner:
    def __init__(self, repo, capture):
        resolved = Path(repo).resolve()
        self.responses = {
            ("tmux", "list-sessions", "-F", SESSION_FORMAT): CommandResult(
                (), 0, f"codex-demo\t{resolved}\tcodex\t10\t0\n", ""
            ),
            ("agent-tmux", "capture", "codex-demo", "160"): CommandResult(
                (), 0, capture, ""
            ),
            ("agent-tmux", "log", "codex-demo"): CommandResult(
                (), 0, "/tmp/agent-tmux/codex-demo.log\n", ""
            ),
        }
        self.calls = []

    def run(self, args):
        key = tuple(args)
        self.calls.append(key)
        response = self.responses.get(key)
        if response is None:
            return CommandResult(key, 127, "", f"unexpected command: {key}")
        return response


class AgentContactCliTests(unittest.TestCase):
    def test_dry_run_would_send_from_idle_prompt(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, "\u203a \n")
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
            self.assertNotIn(("agent-tmux", "send", "codex-demo", "hello"), runner.calls)

    def test_pending_composer_refuses_before_send(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(repo, "\u203a already typed by user\n")
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
            self.assertEqual(payload["pane_state"], "pending_user_text")
            self.assertFalse(any(call[:2] == ("agent-tmux", "send") for call in runner.calls))

    def test_ambiguous_sessions_refuse_before_capture(self):
        with tempfile.TemporaryDirectory() as repo:
            resolved = Path(repo).resolve()
            runner = FakeRunner(repo, "\u203a \n")
            runner.responses[("tmux", "list-sessions", "-F", SESSION_FORMAT)] = CommandResult(
                (),
                0,
                f"codex-a\t{resolved}\tcodex\t10\t0\ncodex-b\t{resolved}\tcodex\t11\t0\n",
                "",
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
            self.assertEqual(code, EXIT_DISCOVERY)
            self.assertEqual(payload["stage"], "discovery")
            self.assertFalse(any(call[:2] == ("agent-tmux", "capture") for call in runner.calls))


if __name__ == "__main__":
    unittest.main()
