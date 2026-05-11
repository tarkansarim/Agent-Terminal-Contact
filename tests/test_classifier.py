import unittest

from agent_terminal_contact.classifier import PaneState, classify_pane


class PaneClassifierTests(unittest.TestCase):
    def test_idle_empty_codex_prompt(self):
        result = classify_pane("some previous output\n\n\u203a \n")
        self.assertEqual(result.state, PaneState.IDLE_EMPTY_PROMPT)

    def test_idle_empty_prompt_with_cursor(self):
        result = classify_pane("ready\n> \u258c\n")
        self.assertEqual(result.state, PaneState.IDLE_EMPTY_PROMPT)

    def test_pending_user_text_refuses(self):
        result = classify_pane("latest answer\n\n\u203a please send this later\n")
        self.assertEqual(result.state, PaneState.PENDING_USER_TEXT)

    def test_trust_prompt_wins_before_menu_prompt(self):
        text = """
> You are in /tmp/project
Do you trust the contents of this directory?

\u203a 1. Yes, continue
  2. No, quit
Press enter to continue
"""
        result = classify_pane(text)
        self.assertEqual(result.state, PaneState.TRUST_PROMPT)

    def test_approval_prompt_refuses(self):
        text = "Do you want to allow this command?\n> 1. Yes\n"
        result = classify_pane(text)
        self.assertEqual(result.state, PaneState.APPROVAL_PROMPT)

    def test_working_state_refuses(self):
        result = classify_pane("Working for 1m 11s\nRunning tests\n")
        self.assertEqual(result.state, PaneState.AGENT_WORKING)

    def test_unknown_refuses(self):
        result = classify_pane("plain terminal output with no prompt\n")
        self.assertEqual(result.state, PaneState.DEAD_OR_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
