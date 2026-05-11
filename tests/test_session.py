import tempfile
import unittest
from pathlib import Path

from agent_terminal_contact.runner import CommandResult
from agent_terminal_contact.session import DiscoveryError, SESSION_FORMAT, select_target


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def run(self, args):
        key = tuple(args)
        self.calls.append(key)
        response = self.responses.get(key)
        if response is None:
            return CommandResult(key, 127, "", f"unexpected command: {key}")
        return response


class SessionDiscoveryTests(unittest.TestCase):
    def test_selects_single_matching_session(self):
        with tempfile.TemporaryDirectory() as repo:
            line = f"codex-demo\t{Path(repo).resolve()}\tcodex\t10\t0\n"
            runner = FakeRunner(
                {
                    ("tmux", "list-sessions", "-F", SESSION_FORMAT): CommandResult(
                        (), 0, line, ""
                    )
                }
            )
            selected = select_target(repo=repo, provider="codex", runner=runner)
            self.assertEqual(selected.session.name, "codex-demo")
            self.assertEqual(selected.provider, "codex")

    def test_refuses_multiple_matching_sessions(self):
        with tempfile.TemporaryDirectory() as repo:
            resolved = Path(repo).resolve()
            line = f"codex-a\t{resolved}\tcodex\t10\t0\ncodex-b\t{resolved}\tcodex\t11\t0\n"
            runner = FakeRunner(
                {
                    ("tmux", "list-sessions", "-F", SESSION_FORMAT): CommandResult(
                        (), 0, line, ""
                    )
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "multiple"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_no_matching_provider(self):
        with tempfile.TemporaryDirectory() as repo:
            line = f"plain\t{Path(repo).resolve()}\tbash\t10\t0\n"
            runner = FakeRunner(
                {
                    ("tmux", "list-sessions", "-F", SESSION_FORMAT): CommandResult(
                        (), 0, line, ""
                    )
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex session"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_unlabeled_node_session_without_explicit_session(self):
        with tempfile.TemporaryDirectory() as repo:
            line = f"agent-terminal-contact\t{Path(repo).resolve()}\tnode\t10\t0\n"
            runner = FakeRunner(
                {
                    ("tmux", "list-sessions", "-F", SESSION_FORMAT): CommandResult(
                        (), 0, line, ""
                    )
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex session"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_allows_explicit_unlabeled_node_session_when_no_opposite_label(self):
        with tempfile.TemporaryDirectory() as repo:
            line = f"agent-terminal-contact\t{Path(repo).resolve()}\tnode\t10\t0\n"
            runner = FakeRunner(
                {
                    (
                        "tmux",
                        "display-message",
                        "-p",
                        "-t",
                        "agent-terminal-contact",
                        SESSION_FORMAT,
                    ): CommandResult((), 0, line, "")
                }
            )
            selected = select_target(
                repo=repo,
                provider="codex",
                runner=runner,
                explicit_session="agent-terminal-contact",
            )
            self.assertEqual(selected.session.provider_evidence, "explicit session uses node command and is not labeled claude")

    def test_explicit_session_must_match_repo(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as other:
            line = f"codex-demo\t{Path(other).resolve()}\tcodex\t10\t0\n"
            runner = FakeRunner(
                {
                    (
                        "tmux",
                        "display-message",
                        "-p",
                        "-t",
                        "codex-demo",
                        SESSION_FORMAT,
                    ): CommandResult((), 0, line, "")
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "not"):
                select_target(
                    repo=repo,
                    provider="codex",
                    runner=runner,
                    explicit_session="codex-demo",
                )


if __name__ == "__main__":
    unittest.main()
