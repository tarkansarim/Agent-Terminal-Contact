import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from agent_terminal_contact.cli import EXIT_DISCOVERY, EXIT_OK, main


def write_manifest(root, installed_tool, installed_skill, source_tool, source_skill):
    manifest = Path(root) / "artifact_ownership.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project": "Example",
                "rollout_command": "cd {source_repo} && ./install.sh",
                "artifacts": [
                    {
                        "id": "example-tool",
                        "kind": "command",
                        "ownership": "owned",
                        "installed_path": str(installed_tool),
                        "source_path": str(source_tool.relative_to(root)),
                        "install_command": "cd {source_repo} && ./install.sh",
                        "check_command": "cd {source_repo} && ./install.sh --check",
                        "command_names": ["example-tool"],
                    },
                    {
                        "id": "example-skill",
                        "kind": "skill",
                        "ownership": "owned",
                        "installed_path": str(installed_skill),
                        "source_path": str(source_skill.relative_to(root)),
                    },
                    {
                        "id": "external-helper",
                        "kind": "command",
                        "ownership": "not_owned",
                        "installed_path": str(Path(root) / "external-helper"),
                        "source_path": None,
                        "notes": "owned by another repo",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


class ArtifactOwnershipCliTests(unittest.TestCase):
    def test_artifact_info_reports_owned_symlink_match_as_json(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source_tool = root_path / "bin" / "example-tool"
            source_tool.parent.mkdir()
            source_tool.write_text("#!/bin/sh\n", encoding="utf-8")
            source_skill = root_path / "skills" / "example" / "SKILL.md"
            source_skill.parent.mkdir(parents=True)
            source_skill.write_text("skill\n", encoding="utf-8")
            installed_tool = root_path / "installed" / "example-tool"
            installed_tool.parent.mkdir()
            installed_tool.symlink_to(source_tool)
            installed_skill = root_path / "installed" / "SKILL.md"
            installed_skill.write_text("skill\n", encoding="utf-8")
            manifest = write_manifest(root_path, installed_tool, installed_skill, source_tool, source_skill)

            stdout = io.StringIO()
            code = main(
                ["artifact-info", str(installed_tool), "--json", "--manifest", str(manifest)],
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            match = payload["matches"][0]
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(match["id"], "example-tool")
            self.assertTrue(match["owns_artifact"])
            self.assertTrue(match["installed_matches_source"])
            self.assertEqual(match["match_type"], "symlink")

    def test_artifact_info_reports_owned_copied_skill_match(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source_tool = root_path / "bin" / "example-tool"
            source_tool.parent.mkdir()
            source_tool.write_text("#!/bin/sh\n", encoding="utf-8")
            source_skill = root_path / "skills" / "example" / "SKILL.md"
            source_skill.parent.mkdir(parents=True)
            source_skill.write_text("skill\n", encoding="utf-8")
            installed_tool = root_path / "installed" / "example-tool"
            installed_tool.parent.mkdir()
            installed_tool.symlink_to(source_tool)
            installed_skill = root_path / "installed" / "SKILL.md"
            installed_skill.write_text("skill\n", encoding="utf-8")
            manifest = write_manifest(root_path, installed_tool, installed_skill, source_tool, source_skill)

            stdout = io.StringIO()
            code = main(
                ["artifact-info", "example-skill", "--json", "--manifest", str(manifest)],
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            match = payload["matches"][0]
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(match["kind"], "skill")
            self.assertTrue(match["installed_matches_source"])
            self.assertEqual(match["match_type"], "bytes")

    def test_artifact_info_reports_explicit_not_owned_artifact(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source_tool = root_path / "bin" / "example-tool"
            source_tool.parent.mkdir()
            source_tool.write_text("#!/bin/sh\n", encoding="utf-8")
            source_skill = root_path / "skills" / "example" / "SKILL.md"
            source_skill.parent.mkdir(parents=True)
            source_skill.write_text("skill\n", encoding="utf-8")
            installed_tool = root_path / "installed" / "example-tool"
            installed_tool.parent.mkdir()
            installed_tool.symlink_to(source_tool)
            installed_skill = root_path / "installed" / "SKILL.md"
            installed_skill.write_text("skill\n", encoding="utf-8")
            manifest = write_manifest(root_path, installed_tool, installed_skill, source_tool, source_skill)

            stdout = io.StringIO()
            code = main(
                ["artifact-info", "external-helper", "--json", "--manifest", str(manifest)],
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            match = payload["matches"][0]
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(match["ownership"], "not_owned")
            self.assertFalse(match["owns_artifact"])
            self.assertIsNone(match["installed_matches_source"])

    def test_artifact_info_unknown_query_returns_discovery_code(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source_tool = root_path / "bin" / "example-tool"
            source_tool.parent.mkdir()
            source_tool.write_text("#!/bin/sh\n", encoding="utf-8")
            source_skill = root_path / "skills" / "example" / "SKILL.md"
            source_skill.parent.mkdir(parents=True)
            source_skill.write_text("skill\n", encoding="utf-8")
            installed_tool = root_path / "installed" / "example-tool"
            installed_tool.parent.mkdir()
            installed_tool.symlink_to(source_tool)
            installed_skill = root_path / "installed" / "SKILL.md"
            installed_skill.write_text("skill\n", encoding="utf-8")
            manifest = write_manifest(root_path, installed_tool, installed_skill, source_tool, source_skill)

            stdout = io.StringIO()
            code = main(
                ["artifact-info", "missing-artifact", "--json", "--manifest", str(manifest)],
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, EXIT_DISCOVERY)
            self.assertEqual(payload["status"], "unknown")
            self.assertEqual(payload["matches"], [])

    def test_repository_manifest_names_owned_and_non_owned_surfaces(self):
        root = Path(__file__).resolve().parents[1]
        manifest = root / "artifact_ownership.json"
        stdout = io.StringIO()
        old_home = os.environ.get("HOME")
        old_codex_home = os.environ.get("CODEX_HOME")
        with tempfile.TemporaryDirectory() as home:
            os.environ["HOME"] = home
            os.environ["CODEX_HOME"] = str(Path(home) / ".codex")
            try:
                code = main(["artifact-info", "--all", "--json", "--manifest", str(manifest)], stdout=stdout)
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home
                if old_codex_home is None:
                    os.environ.pop("CODEX_HOME", None)
                else:
                    os.environ["CODEX_HOME"] = old_codex_home
        payload = json.loads(stdout.getvalue())
        ids = {match["id"]: match for match in payload["matches"]}
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(ids["agent-contact"]["ownership"], "owned")
        self.assertEqual(ids["agent-tmux-wrapper"]["ownership"], "owned")
        self.assertEqual(ids["agent-tmux-control-skill"]["ownership"], "owned")
        self.assertEqual(ids["system-agent-tmux-helper"]["ownership"], "not_owned")


if __name__ == "__main__":
    unittest.main()
