import unittest

from agent_terminal_contact.classifier import PaneState, classify_pane, current_prompt_body


class PaneClassifierTests(unittest.TestCase):
    def test_idle_empty_codex_prompt(self):
        result = classify_pane(
            "previous assistant output\n\n\u203a \n  gpt-5.5 xhigh · /tmp/project\n",
            provider="codex",
            cursor_line_index=2,
        )
        self.assertEqual(result.state, PaneState.IDLE_EMPTY_PROMPT)

    def test_text_only_codex_prompt_footer_does_not_prove_idle(self):
        result = classify_pane("previous assistant output\n\n\u203a \n  gpt-5.5 xhigh · /tmp/project\n", provider="codex")
        self.assertEqual(result.state, PaneState.DEAD_OR_UNKNOWN)

    def test_codex_footer_before_prompt_does_not_prove_idle(self):
        result = classify_pane("assistant output\n  gpt-5.5 xhigh · /tmp/project\n\u203a \n", provider="codex")
        self.assertEqual(result.state, PaneState.DEAD_OR_UNKNOWN)

    def test_idle_empty_claude_prompt_with_cursor(self):
        result = classify_pane("ready\n> \u258c\n? for shortcuts\n", provider="claude", cursor_line_index=1)
        self.assertEqual(result.state, PaneState.IDLE_EMPTY_PROMPT)

    def test_current_claude_prompt_body_accepts_wrapped_cursor_continuation(self):
        text = (
            "ready\n"
            "> CONTACT_ID: AC-TEST\n"
            " MESSAGE_JSON: \"very-long\n"
            "-wrapped-message\"\u258c\n"
            "? for shortcuts\n"
        )
        self.assertEqual(
            current_prompt_body(text, provider="claude", cursor_line_index=3),
            'CONTACT_ID: AC-TEST\nMESSAGE_JSON: "very-long\n-wrapped-message"',
        )

    def test_pending_user_text_refuses(self):
        result = classify_pane(
            "latest answer\n\n\u203a please send this later\n  gpt-5.5 xhigh · /tmp/project\n",
            provider="codex",
        )
        self.assertEqual(result.state, PaneState.PENDING_USER_TEXT)

    def test_current_prompt_body_requires_provider_context(self):
        text = "latest answer\n\n\u203a CONTACT_ID: AC-TEST MESSAGE_JSON: \"hello\"\n  gpt-5.5 xhigh · /tmp/project\n"
        self.assertEqual(
            current_prompt_body(text, provider="codex", cursor_line_index=2),
            'CONTACT_ID: AC-TEST MESSAGE_JSON: "hello"',
        )
        self.assertIsNone(current_prompt_body(text, provider="codex", cursor_line_index=None))

    def test_current_prompt_body_ignores_marker_after_footer(self):
        text = (
            "latest answer\n\n"
            "\u203a unrelated draft\n"
            "  gpt-5.5 xhigh · /tmp/project\n"
            "CONTACT_ID: AC-TEST MESSAGE_JSON: \"hello\"\n"
        )
        self.assertIsNone(current_prompt_body(text, provider="codex", cursor_line_index=2))

    def test_current_prompt_body_uses_cursor_prompt_with_older_prompt_visible(self):
        text = (
            "older assistant output\n\n"
            "\u203a old request\n"
            "  gpt-5.5 xhigh · /tmp/project\n"
            "new assistant output\n\n"
            "\u203a CONTACT_ID: AC-TEST MESSAGE_JSON: \"hello\"\n"
            "  gpt-5.5 xhigh · /tmp/project\n"
        )
        self.assertEqual(
            current_prompt_body(text, provider="codex", cursor_line_index=6),
            'CONTACT_ID: AC-TEST MESSAGE_JSON: "hello"',
        )

    def test_cursor_backed_idle_prompt_ignores_older_prompt_visible_in_scrollback(self):
        result = classify_pane(
            "older assistant output\n\n"
            "\u203a old request\n"
            "  gpt-5.5 xhigh · /tmp/project\n"
            "new assistant output\n\n"
            "\u203a \n"
            "  gpt-5.5 xhigh · /tmp/project\n",
            provider="codex",
            cursor_line_index=6,
        )
        self.assertEqual(result.state, PaneState.IDLE_EMPTY_PROMPT)

    def test_current_prompt_body_accepts_wrapped_current_prompt(self):
        text = (
            "assistant output\n\n"
            "\u203a CONTACT_ID: AC-TEST\n"
            " MESSAGE_JSON: \"very-long\n"
            "-wrapped-message\"\n"
            "  gpt-5.5 xhigh · /tmp/project\n"
        )
        self.assertEqual(
            current_prompt_body(text, provider="codex", cursor_line_index=2),
            'CONTACT_ID: AC-TEST\nMESSAGE_JSON: "very-long\n-wrapped-message"',
        )
        result = classify_pane(text, provider="codex", cursor_line_index=2)
        self.assertEqual(result.state, PaneState.PENDING_USER_TEXT)

    def test_multiline_pending_user_text_refuses_when_prompt_line_empty(self):
        result = classify_pane(
            "latest answer\n\n\u203a \nsecond line of pending draft\n  gpt-5.5 xhigh · /tmp/project\n",
            provider="codex",
        )
        self.assertEqual(result.state, PaneState.PENDING_USER_TEXT)

    def test_bare_prompt_without_provider_context_refuses(self):
        result = classify_pane("ordinary output\n> \n")
        self.assertEqual(result.state, PaneState.DEAD_OR_UNKNOWN)

    def test_codex_does_not_accept_bare_greater_than_prompt(self):
        result = classify_pane("ordinary output\n> \n", provider="codex")
        self.assertEqual(result.state, PaneState.DEAD_OR_UNKNOWN)

    def test_codex_does_not_accept_bare_prompt_glyph_in_ordinary_output(self):
        result = classify_pane("ordinary output\n\u203a \n", provider="codex")
        self.assertEqual(result.state, PaneState.DEAD_OR_UNKNOWN)

    def test_claude_does_not_accept_bare_prompt_glyph_in_ordinary_output(self):
        result = classify_pane("ordinary output\n> \n", provider="claude")
        self.assertEqual(result.state, PaneState.DEAD_OR_UNKNOWN)

    def test_codex_does_not_accept_bullet_context_as_prompt_proof(self):
        result = classify_pane("• list item in output\nordinary output\n\u203a \n", provider="codex")
        self.assertEqual(result.state, PaneState.DEAD_OR_UNKNOWN)

    def test_claude_does_not_accept_name_context_as_prompt_proof(self):
        result = classify_pane("Claude ready\nassistant output\n> \n", provider="claude")
        self.assertEqual(result.state, PaneState.DEAD_OR_UNKNOWN)

    def test_codex_working_status_wins_over_prompt_footer(self):
        result = classify_pane(
            "Working for 12s\nRunning tests\n\n\u203a \n  gpt-5.5 xhigh · /tmp/project\n",
            provider="codex",
        )
        self.assertEqual(result.state, PaneState.AGENT_WORKING)

    def test_codex_prefixed_running_after_prompt_footer_is_not_idle(self):
        result = classify_pane(
            "previous\n\n\u203a \n  gpt-5.5 xhigh · /tmp/project\n• Running pytest\n",
            provider="codex",
        )
        self.assertEqual(result.state, PaneState.AGENT_WORKING)

    def test_codex_unknown_output_after_prompt_footer_refuses(self):
        result = classify_pane(
            "previous\n\n\u203a \n  gpt-5.5 xhigh · /tmp/project\nnew output after footer\n",
            provider="codex",
        )
        self.assertEqual(result.state, PaneState.DEAD_OR_UNKNOWN)

    def test_claude_footer_without_cursor_does_not_prove_idle_prompt(self):
        result = classify_pane("assistant output\n> \n? for shortcuts\n", provider="claude")
        self.assertEqual(result.state, PaneState.DEAD_OR_UNKNOWN)

    def test_codex_context_compacted_without_footer_does_not_prove_idle_prompt(self):
        result = classify_pane("Context compacted\n\n\u203a \n", provider="codex")
        self.assertEqual(result.state, PaneState.DEAD_OR_UNKNOWN)

    def test_codex_ascii_pipe_is_pending_text_not_cursor(self):
        result = classify_pane(
            "assistant output\n\u203a |\n  gpt-5.5 xhigh · /tmp/project\n",
            provider="codex",
        )
        self.assertEqual(result.state, PaneState.PENDING_USER_TEXT)

    def test_claude_ascii_pipe_is_pending_text_not_cursor(self):
        result = classify_pane("assistant output\n> |\n? for shortcuts\n", provider="claude")
        self.assertEqual(result.state, PaneState.PENDING_USER_TEXT)

    def test_codex_multiline_prompt_marker_block_is_pending_text(self):
        result = classify_pane(
            "assistant output\n\n\u203a first pending line\n\u203a \n  gpt-5.5 xhigh · /tmp/project\n",
            provider="codex",
        )
        self.assertEqual(result.state, PaneState.PENDING_USER_TEXT)

    def test_codex_blank_line_separated_prompt_marker_block_is_pending_text(self):
        result = classify_pane(
            "assistant output\n\n\u203a first pending line\n\n\u203a \n  gpt-5.5 xhigh · /tmp/project\n",
            provider="codex",
        )
        self.assertEqual(result.state, PaneState.PENDING_USER_TEXT)

    def test_claude_multiline_prompt_marker_block_is_pending_text(self):
        result = classify_pane("assistant\n> first pending line\n> \u258c\n? for shortcuts\n", provider="claude")
        self.assertEqual(result.state, PaneState.PENDING_USER_TEXT)

    def test_claude_blank_line_separated_prompt_marker_block_is_pending_text(self):
        result = classify_pane("assistant\n> first pending line\n\n> \u258c\n? for shortcuts\n", provider="claude")
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
