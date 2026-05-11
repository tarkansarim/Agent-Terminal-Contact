import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_skill_requires_agent_contact_for_cross_agent_messages(self):
        text = (ROOT / "skills" / "agent-tmux-control" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Use `agent-contact send`", text)
        self.assertIn("Raw `agent-tmux send` is a low-level transport primitive", text)
        self.assertIn("Pending visible composer text is user-owned state and is a hard stop", text)
        self.assertIn("If `agent-contact` refuses, stop", text)

    def test_install_dry_run_names_non_invasive_targets(self):
        result = subprocess.run(
            ["bash", "scripts/install.sh", "--dry-run"],
            cwd=ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(".local/bin/agent-contact", result.stdout)
        self.assertIn(".codex/skills/agent-tmux-control/SKILL.md", result.stdout)
        self.assertNotIn("/usr/local/bin/agent-tmux", result.stdout)


if __name__ == "__main__":
    unittest.main()
