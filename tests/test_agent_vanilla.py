import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "bin" / "agent-vanilla"


def load_launcher():
    loader = importlib.machinery.SourceFileLoader("agent_vanilla", str(LAUNCHER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class AgentVanillaTests(unittest.TestCase):
    def setUp(self):
        self.module = load_launcher()

    def make_provider(self, root: Path, name: str) -> Path:
        binary = root / "providers" / name
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)
        return binary

    def test_claude_uses_native_safe_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            claude = self.make_provider(root, "claude")
            with mock.patch.dict(
                os.environ,
                {"AGENT_VANILLA_CLAUDE_BIN": str(claude), "HOME": str(root)},
                clear=False,
            ):
                command, _env, metadata = self.module.build_launch("claude", root, ["hello"])
            self.assertEqual(command, [str(claude), "--safe-mode", "hello"])
            self.assertEqual(metadata["isolation"], "claude-native-safe-mode")
            self.assertTrue(metadata["fresh_session"])

    def test_claude_refuses_resume_and_custom_settings(self):
        for argument in ("--resume", "--continue", "--settings", "--mcp-config"):
            with self.subTest(argument=argument):
                with self.assertRaises(self.module.UsageError):
                    self.module.reject_customization("claude", [argument])

    def test_codex_builds_isolated_profile_and_disables_repo_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "AGENTS.md").write_text("DO_NOT_LOAD_REPO_RULE\n", encoding="utf-8")
            skill = repo / ".agents" / "skills" / "project-sentinel" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: project-sentinel\ndescription: sentinel\n---\n", encoding="utf-8")
            legacy_skill = repo / ".codex" / "skills" / "legacy-sentinel" / "SKILL.md"
            legacy_skill.parent.mkdir(parents=True)
            legacy_skill.write_text("---\nname: legacy-sentinel\ndescription: sentinel\n---\n", encoding="utf-8")
            user_skill = root / ".agents" / "skills" / "user-sentinel" / "SKILL.md"
            user_skill.parent.mkdir(parents=True)
            user_skill.write_text("---\nname: user-sentinel\ndescription: sentinel\n---\n", encoding="utf-8")
            auth = root / ".codex" / "auth.json"
            auth.parent.mkdir(parents=True)
            auth.write_text("{}\n", encoding="utf-8")
            codex = self.make_provider(root, "codex")
            state = root / "state"

            with mock.patch.dict(
                os.environ,
                {
                    "AGENT_VANILLA_CODEX_BIN": str(codex),
                    "AGENT_VANILLA_CODEX_AUTH": str(auth),
                    "AGENT_VANILLA_STATE_HOME": str(state),
                    "HOME": str(root),
                },
                clear=False,
            ):
                with mock.patch.object(Path, "home", return_value=root):
                    command, env, metadata = self.module.build_launch("codex", repo, ["exec", "hello"])

            profile = Path(env["CODEX_HOME"])
            config = (profile / "config.toml").read_text(encoding="utf-8")
            self.assertEqual(command, [str(codex), "-C", str(repo), "exec", "hello"])
            self.assertIn("project_doc_max_bytes = 0", config)
            self.assertIn('trust_level = "untrusted"', config)
            self.assertIn(str(skill), config)
            self.assertIn(str(legacy_skill), config)
            self.assertIn(str(user_skill), config)
            self.assertEqual((profile / "auth.json").resolve(), auth)
            self.assertEqual(metadata["isolation"], "isolated-codex-home")

    def test_codex_refuses_configuration_overrides(self):
        for argument in ("-c", "--config=project_doc_max_bytes=999", "--profile"):
            with self.subTest(argument=argument):
                with self.assertRaises(self.module.UsageError):
                    self.module.reject_customization("codex", [argument])

    def test_dry_run_reports_fresh_vanilla_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            claude = self.make_provider(root, "claude")
            result = subprocess.run(
                [str(LAUNCHER), "claude", "--workdir", str(root), "--dry-run"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    **os.environ,
                    "AGENT_VANILLA_CLAUDE_BIN": str(claude),
                    "HOME": str(root),
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["fresh_session"])
            self.assertEqual(payload["command"][1], "--safe-mode")


if __name__ == "__main__":
    unittest.main()
