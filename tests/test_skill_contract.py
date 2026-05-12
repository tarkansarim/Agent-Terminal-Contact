import hashlib
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_PATH = os.environ.get("PATH", "/usr/bin:/bin")


def code_map_session_name(repo, anchor):
    def slug_component(raw):
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw.lower())
        slug = re.sub(r"-+", "-", slug).strip("-")[:32].rstrip("-")
        return slug or "x"

    digest = hashlib.sha256(f"{repo.resolve()}\n{anchor}".encode("utf-8")).hexdigest()[:12]
    return f"codex-map-{slug_component(repo.name)}-{slug_component(anchor)}-{digest}"


def write_code_map_delegate(tmp_path, *, has_rc=1):
    delegate = tmp_path / "delegate-agent-tmux"
    delegate.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = has ]; then\n"
        f"  exit {has_rc}\n"
        "fi\n"
        "if [ \"$1\" = log ]; then\n"
        "  printf '/tmp/agent-tmux/%s.log\\n' \"$2\"\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = pipe-log ]; then\n"
        "  printf '%s\\n' \"$2\" >\"${AGENT_TMUX_PIPE_CAPTURE}\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    delegate.chmod(0o755)
    return delegate


def write_fake_tmux(tmp_path):
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    tmux = bin_dir / "tmux"
    tmux.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = new-session ]; then\n"
        "  if [ \"${AGENT_TMUX_FAIL_NEW:-0}\" = 1 ]; then\n"
        "    printf 'duplicate session\\n' >&2\n"
        "    exit 1\n"
        "  fi\n"
        "  printf '%s\\n' \"$@\" >\"${AGENT_TMUX_CAPTURE}\"\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = kill-session ]; then\n"
        "  exit 0\n"
        "fi\n"
        "printf 'unexpected tmux command: %s\\n' \"$*\" >&2\n"
        "exit 2\n",
        encoding="utf-8",
    )
    tmux.chmod(0o755)
    return bin_dir


class SkillContractTests(unittest.TestCase):
    def test_skill_requires_agent_contact_for_cross_agent_messages(self):
        text = (ROOT / "skills" / "agent-tmux-control" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Use `agent-contact send`", text)
        self.assertIn("Raw `agent-tmux send` is a low-level transport primitive", text)
        self.assertIn("Normal user-launched `codex` chats are not tmux-managed by default", text)
        self.assertIn("Before spawning any tmux worker, identify whether the repo's active lane is\nCodex or Claude", text)
        self.assertIn("Do not choose the provider from the supervising agent", text)
        self.assertIn("If the signals disagree, if both providers have plausible active chats", text)
        self.assertIn("do not start\na fresh chat first", text)
        self.assertIn("agent-tmux codex-latest", text)
        self.assertIn("agent-tmux codex-resume-latest", text)
        self.assertIn("Only use `agent-tmux codex <session> <repo>`", text)
        self.assertIn("Unexpected visible composer text in a tmux-managed agent is user-owned pending", text)
        self.assertIn("Stop and do not clear it, submit it, or send over it", text)
        self.assertIn("current operator explicitly approves clearing that exact text", text)
        self.assertIn("Stale contact residue created by a failed `agent-contact` attempt", text)
        self.assertIn("mutated_unsubmitted`, and it is not a human draft", text)
        self.assertIn("agent-tmux clear-input <session>", text)
        self.assertIn("clear only that proven\n  residue", text)
        self.assertIn("rerun guarded\n  `agent-contact`", text)
        self.assertNotIn("Unexpected visible composer text in a tmux-managed agent is stale session", text)
        self.assertIn("If `agent-contact` refuses, stop", text)
        self.assertIn("agent-contact trust-roots", text)
        self.assertIn("## Codex Worker Permission Profile", text)
        self.assertIn("agent-tmux codex-full <session> <repo>", text)
        self.assertIn(
            "agent-tmux codex-resume-full <session> <repo> <thread-name-or-id>",
            text,
        )
        self.assertIn("agent-tmux codex-resume-latest-full <session> <repo>", text)
        self.assertIn("agent-tmux codex-code-map-sidecar <repo> <anchor>", text)
        self.assertIn("agent-tmux codex-code-map-sidecar-fork <repo> <anchor> <codex-session-id>", text)
        self.assertIn("agent-tmux codex-code-map-validate-artifacts <artifact-dir>", text)
        self.assertIn("code-map patch-artifact sidecar", text)
        self.assertIn("must not edit production source, tests, config, install scripts", text)
        self.assertIn("writable output path", text)
        self.assertIn("PROPOSED_CHANGES.patch", text)
        self.assertIn("The validator rejects `PROPOSED_CHANGES.patch` and `PROPOSED_FILES/` entries", text)
        self.assertIn("change the anchor\nto launch a new sidecar", text)
        self.assertIn("validates the sidecar's artifact-local `SIDECAR_REQUEST.txt`\nmanifest", text)
        self.assertIn("agent-contact send --repo <repo> --provider codex --session <sidecar-session>", text)
        self.assertIn("agent-contact send --repo <artifact-dir> --provider codex --session <sidecar-session>", text)
        self.assertIn("If `agent-contact` returns `mutated_unsubmitted`, treat delivery as failed", text)
        self.assertIn("Do not fall back to raw `agent-tmux send`", text)
        self.assertIn("Do not use\n`--dangerously-bypass-approvals-and-sandbox`", text)
        self.assertIn("Codex launch/resume routes through this wrapper require the requested tmux", text)
        self.assertIn("legacy supervise-style shape", text)
        self.assertIn("a true no-existing-session result is `rc=1`, empty stdout", text)
        self.assertIn("Latest-thread parsing for these aliases is fail-closed", text)
        self.assertIn("source-owned user-level wrapper", text)
        self.assertIn("/usr/local/bin/agent-tmux", text)

    def test_install_dry_run_names_non_invasive_targets(self):
        with tempfile.TemporaryDirectory() as home:
            result = subprocess.run(
                ["bash", "scripts/install.sh", "--dry-run"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(".local/bin/agent-contact", result.stdout)
            self.assertIn(".local/bin/agent-tmux", result.stdout)
            self.assertIn(".codex/skills/agent-tmux-control/SKILL.md", result.stdout)
            self.assertNotIn("/usr/local/bin/agent-tmux", result.stdout)

    def test_install_check_verifies_user_level_command_and_skill_are_current(self):
        with tempfile.TemporaryDirectory() as home:
            codex_home = Path(home) / ".codex"
            bin_dir = Path(home) / ".local" / "bin"
            install = subprocess.run(
                ["bash", "scripts/install.sh", "--force"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            check = subprocess.run(
                ["bash", "scripts/install.sh", "--check"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "HOME": home,
                    "CODEX_HOME": str(codex_home),
                    "BIN_DIR": str(bin_dir),
                    "PATH": f"{bin_dir}:/usr/bin:/bin",
                },
            )
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertIn("agent-contact install check: ok", check.stdout)
            self.assertIn("agent-tmux wrapper:", check.stdout)

    def test_install_check_refuses_when_agent_contact_is_not_on_path(self):
        with tempfile.TemporaryDirectory() as home:
            codex_home = Path(home) / ".codex"
            bin_dir = Path(home) / ".local" / "bin"
            install = subprocess.run(
                ["bash", "scripts/install.sh", "--force"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            check = subprocess.run(
                ["bash", "scripts/install.sh", "--check"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "HOME": home,
                    "CODEX_HOME": str(codex_home),
                    "BIN_DIR": str(bin_dir),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(check.returncode, 3)
            self.assertIn("agent-contact is not discoverable on PATH", check.stderr)

    def test_install_check_refuses_stale_user_level_skill(self):
        with tempfile.TemporaryDirectory() as home:
            codex_home = Path(home) / ".codex"
            bin_dir = Path(home) / ".local" / "bin"
            install = subprocess.run(
                ["bash", "scripts/install.sh", "--force"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            skill = codex_home / "skills" / "agent-tmux-control" / "SKILL.md"
            skill.write_text("stale skill\n", encoding="utf-8")
            check = subprocess.run(
                ["bash", "scripts/install.sh", "--check"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "HOME": home,
                    "CODEX_HOME": str(codex_home),
                    "BIN_DIR": str(bin_dir),
                    "PATH": f"{bin_dir}:/usr/bin:/bin",
                },
            )
            self.assertEqual(check.returncode, 3)
            self.assertIn("installed skill differs from repo source", check.stderr)

    def test_install_refuses_divergent_existing_skill_without_force(self):
        with tempfile.TemporaryDirectory() as home:
            codex_home = Path(home) / ".codex"
            skill_dir = codex_home / "skills" / "agent-tmux-control"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("local hardened skill\n", encoding="utf-8")
            result = subprocess.run(
                ["bash", "scripts/install.sh"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("refusing to overwrite divergent installed skill", result.stderr)
            self.assertEqual((skill_dir / "SKILL.md").read_text(encoding="utf-8"), "local hardened skill\n")

    def test_install_refuses_symlinked_existing_skill_without_force(self):
        with tempfile.TemporaryDirectory() as home:
            codex_home = Path(home) / ".codex"
            skill_dir = codex_home / "skills" / "agent-tmux-control"
            skill_dir.mkdir(parents=True)
            external_skill = Path(home) / "external-skill.md"
            external_skill.write_text("external skill must survive\n", encoding="utf-8")
            (skill_dir / "SKILL.md").symlink_to(external_skill)
            result = subprocess.run(
                ["bash", "scripts/install.sh"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("refusing to overwrite symlinked installed skill", result.stderr)
            self.assertEqual(external_skill.read_text(encoding="utf-8"), "external skill must survive\n")

    def test_install_refuses_symlinked_skill_directory_without_force(self):
        with tempfile.TemporaryDirectory() as home:
            codex_home = Path(home) / ".codex"
            skills_root = codex_home / "skills"
            skills_root.mkdir(parents=True)
            external_dir = Path(home) / "external-skill-dir"
            external_dir.mkdir()
            skill_dir = skills_root / "agent-tmux-control"
            skill_dir.symlink_to(external_dir, target_is_directory=True)
            result = subprocess.run(
                ["bash", "scripts/install.sh"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("refusing to write through symlinked skill directory", result.stderr)
            self.assertFalse((external_dir / "SKILL.md").exists())

    def test_install_force_replaces_symlinked_skill_directory_without_writing_through(self):
        with tempfile.TemporaryDirectory() as home:
            codex_home = Path(home) / ".codex"
            skills_root = codex_home / "skills"
            skills_root.mkdir(parents=True)
            external_dir = Path(home) / "external-skill-dir"
            external_dir.mkdir()
            skill_dir = skills_root / "agent-tmux-control"
            skill_dir.symlink_to(external_dir, target_is_directory=True)
            source_skill = ROOT / "skills" / "agent-tmux-control" / "SKILL.md"
            result = subprocess.run(
                ["bash", "scripts/install.sh", "--force"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            backups = list(skills_root.glob("agent-tmux-control.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertTrue(backups[0].is_symlink())
            self.assertEqual(backups[0].resolve(), external_dir)
            self.assertFalse(skill_dir.is_symlink())
            self.assertEqual((skill_dir / "SKILL.md").read_text(encoding="utf-8"), source_skill.read_text(encoding="utf-8"))
            self.assertFalse((external_dir / "SKILL.md").exists())

    def test_install_force_replaces_populated_symlinked_skill_directory_without_state_leak(self):
        with tempfile.TemporaryDirectory() as home:
            codex_home = Path(home) / ".codex"
            skills_root = codex_home / "skills"
            skills_root.mkdir(parents=True)
            external_dir = Path(home) / "external-skill-dir"
            external_dir.mkdir()
            (external_dir / "SKILL.md").write_text("external skill must survive\n", encoding="utf-8")
            skill_dir = skills_root / "agent-tmux-control"
            skill_dir.symlink_to(external_dir, target_is_directory=True)
            source_skill = ROOT / "skills" / "agent-tmux-control" / "SKILL.md"
            result = subprocess.run(
                ["bash", "scripts/install.sh", "--force"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(skill_dir.is_symlink())
            self.assertEqual((skill_dir / "SKILL.md").read_text(encoding="utf-8"), source_skill.read_text(encoding="utf-8"))
            self.assertEqual((external_dir / "SKILL.md").read_text(encoding="utf-8"), "external skill must survive\n")

    def test_install_force_replaces_symlinked_skill_without_overwriting_referent(self):
        with tempfile.TemporaryDirectory() as home:
            codex_home = Path(home) / ".codex"
            skill_dir = codex_home / "skills" / "agent-tmux-control"
            skill_dir.mkdir(parents=True)
            external_skill = Path(home) / "external-skill.md"
            external_skill.write_text("external skill must survive\n", encoding="utf-8")
            installed_skill = skill_dir / "SKILL.md"
            installed_skill.symlink_to(external_skill)
            source_skill = ROOT / "skills" / "agent-tmux-control" / "SKILL.md"
            result = subprocess.run(
                ["bash", "scripts/install.sh", "--force"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(installed_skill.is_symlink())
            self.assertEqual(installed_skill.read_text(encoding="utf-8"), source_skill.read_text(encoding="utf-8"))
            self.assertEqual(external_skill.read_text(encoding="utf-8"), "external skill must survive\n")

    def test_install_refuses_divergent_existing_bin_without_force(self):
        with tempfile.TemporaryDirectory() as home:
            codex_home = Path(home) / ".codex"
            bin_dir = Path(home) / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            existing_bin = bin_dir / "agent-contact"
            existing_bin.write_text("existing command\n", encoding="utf-8")
            skill_dir = codex_home / "skills" / "agent-tmux-control"
            skill_dir.mkdir(parents=True)
            source_skill = ROOT / "skills" / "agent-tmux-control" / "SKILL.md"
            (skill_dir / "SKILL.md").write_text(source_skill.read_text(encoding="utf-8"), encoding="utf-8")
            result = subprocess.run(
                ["bash", "scripts/install.sh"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("refusing to overwrite divergent agent-contact target", result.stderr)
            self.assertEqual(existing_bin.read_text(encoding="utf-8"), "existing command\n")

    def test_install_refuses_divergent_existing_agent_tmux_wrapper_without_force(self):
        with tempfile.TemporaryDirectory() as home:
            codex_home = Path(home) / ".codex"
            bin_dir = Path(home) / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            existing_bin = bin_dir / "agent-tmux"
            existing_bin.write_text("existing wrapper\n", encoding="utf-8")
            skill_dir = codex_home / "skills" / "agent-tmux-control"
            skill_dir.mkdir(parents=True)
            source_skill = ROOT / "skills" / "agent-tmux-control" / "SKILL.md"
            (skill_dir / "SKILL.md").write_text(source_skill.read_text(encoding="utf-8"), encoding="utf-8")
            (bin_dir / "agent-contact").symlink_to(ROOT / "bin" / "agent-contact")
            result = subprocess.run(
                ["bash", "scripts/install.sh"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("refusing to overwrite divergent agent-tmux wrapper target", result.stderr)
            self.assertEqual(existing_bin.read_text(encoding="utf-8"), "existing wrapper\n")

    def test_install_force_backs_up_divergent_existing_bin_symlink(self):
        with tempfile.TemporaryDirectory() as home:
            codex_home = Path(home) / ".codex"
            bin_dir = Path(home) / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            other_target = Path(home) / "other-agent-contact"
            other_target.write_text("other command\n", encoding="utf-8")
            existing_bin = bin_dir / "agent-contact"
            existing_bin.symlink_to(other_target)
            skill_dir = codex_home / "skills" / "agent-tmux-control"
            skill_dir.mkdir(parents=True)
            source_skill = ROOT / "skills" / "agent-tmux-control" / "SKILL.md"
            (skill_dir / "SKILL.md").write_text(source_skill.read_text(encoding="utf-8"), encoding="utf-8")
            result = subprocess.run(
                ["bash", "scripts/install.sh", "--force"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            backups = list(bin_dir.glob("agent-contact.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertTrue(backups[0].is_symlink())
            self.assertEqual(backups[0].resolve(), other_target)
            self.assertEqual(existing_bin.resolve(), ROOT / "bin" / "agent-contact")

    def test_agent_tmux_full_alias_expands_permission_args(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            capture = tmp_path / "args.txt"
            env_capture = tmp_path / "env.txt"
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
                "fi\n"
                "printf '%s\\n' \"${AGENT_TMUX_ALLOW_DUPLICATE:-}\" >\"${AGENT_TMUX_ENV_CAPTURE}\"\n"
                "printf '%s\\n' \"$@\" >\"${AGENT_TMUX_CAPTURE}\"\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-full", "sess", repo, "--model", "gpt-5.5"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_ENV_CAPTURE": str(env_capture),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("-s danger-full-access -a never", result.stderr)
            self.assertEqual(env_capture.read_text(encoding="utf-8").strip(), "1")
            self.assertEqual(
                capture.read_text(encoding="utf-8").splitlines(),
                ["codex", "sess", repo, "-s", "danger-full-access", "-a", "never", "--model", "gpt-5.5"],
            )

    def test_agent_tmux_full_alias_refuses_existing_requested_session(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            capture = tmp_path / "args.txt"
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 0\n"
                "fi\n"
                "printf '%s\\n' \"$@\" >\"${AGENT_TMUX_CAPTURE}\"\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-full", "sess", repo, "--model", "gpt-5.5"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("requested session already exists: sess", result.stderr)
            self.assertFalse(capture.exists())

    def test_agent_tmux_code_map_sidecar_uses_deterministic_artifact_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            capture_second = tmp_path / "args-second.txt"
            pipe_capture = tmp_path / "pipe.txt"
            artifact_root = tmp_path / "artifacts"
            artifact_root_second = tmp_path / "artifacts-second"
            delegate = write_code_map_delegate(tmp_path, has_rc=1)
            fake_bin = write_fake_tmux(tmp_path)
            env = {
                "AGENT_TMUX_DELEGATE": str(delegate),
                "AGENT_TMUX_CAPTURE": str(capture),
                "AGENT_TMUX_PIPE_CAPTURE": str(pipe_capture),
                "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(artifact_root),
                "HOME": str(tmp_path / "home"),
                "PATH": f"{fake_bin}:{TEST_PATH}",
            }
            result = subprocess.run(
                [
                    "bash",
                    "bin/agent-tmux",
                    "codex-code-map-sidecar",
                    str(repo),
                    "cp-123:branch point",
                    "Focus on runner wiring",
                ],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = capture.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[:3], ["new-session", "-d", "-s"])
            session = lines[3]
            self.assertRegex(session, r"^codex-map-example-repo-cp-123-branch-point-[0-9a-f]{12}$")
            artifact_dir = artifact_root / session
            self.assertEqual(lines[4:6], ["-c", str(artifact_dir)])
            self.assertTrue(artifact_dir.is_dir())
            self.assertEqual(pipe_capture.read_text(encoding="utf-8").strip(), session)
            command = lines[6]
            self.assertIn("bwrap --die-with-parent --unshare-all --share-net --clearenv --ro-bind / /", command)
            self.assertIn("--tmpfs /home", command)
            self.assertIn(f"--ro-bind {artifact_dir}/.agent-tmux-runtime/empty-usr-local-bin /usr/local/bin", command)
            self.assertIn("--ro-bind", command)
            self.assertIn(str(repo.resolve()).replace(" ", "\\ "), command)
            self.assertIn("--dev /dev", command)
            self.assertNotIn("--dev-bind /dev /dev", command)
            self.assertNotIn(f"{fake_bin}/codex", command)
            self.assertIn("/home/tarkan/.nvm/versions/node/", command)
            self.assertIn("/bin/node", command)
            self.assertIn("/lib/node_modules/@openai/codex/bin/codex.js", command)
            self.assertIn(f"--ro-bind {artifact_dir}/.agent-tmux-runtime/empty-dev-shm /dev/shm", command)
            self.assertIn("--tmpfs /tmp --tmpfs /run", command)
            self.assertIn(f"--bind {artifact_dir} {artifact_dir}", command)
            self.assertIn("--setenv CODEX_NO_TMUX 1", command)
            self.assertNotIn("--setenv CODEX_REAL_BIN", command)
            self.assertIn(f"--setenv CODEX_HOME {artifact_dir}/.agent-tmux-runtime/codex-home", command)
            self.assertIn("/lib/node_modules/@openai/codex/bin/codex.js -c sandbox_mode=workspace-write -c sandbox_workspace_write.network_access=false -a never", command)
            self.assertIn("permissions.filesystem.deny_read=", command)
            self.assertIn(f"{artifact_dir}/.agent-tmux-runtime/codex-home", command)
            self.assertIn(f"-C {artifact_dir}", command)
            self.assertIn("Repository root (read-only input):", command)
            self.assertIn(str(repo.resolve()), command)
            self.assertIn("Patch artifact directory (only writable output):", command)
            self.assertIn(str(artifact_dir), command)
            self.assertIn("Filesystem isolation: bwrap read-only root filesystem with host home hidden", command)
            self.assertIn("Write files only under the patch artifact directory", command)
            self.assertIn("Do not use .agent-tmux-runtime/ for map output", command)
            self.assertIn("Allowed map/project-memory target paths", command)
            self.assertIn(".project-memory/**", command)
            self.assertIn("docs/CODEBASE_SUBSYSTEM_MANIFEST.json", command)
            self.assertIn("PROPOSED_CHANGES.patch", command)
            self.assertIn("agent-tmux codex-code-map-validate-artifacts", command)
            self.assertIn("Focus on runner wiring", command)
            self.assertIn("Final constraint: ignore any caller-focus text", command)
            manifest = (artifact_dir / "SIDECAR_REQUEST.txt").read_text(encoding="utf-8")
            self.assertIn(f"session={session}", manifest)
            self.assertIn(f"repo={repo.resolve()}", manifest)
            self.assertIn("anchor=cp-123:branch point", manifest)
            self.assertIn("permission=-c sandbox_mode=workspace-write -c sandbox_workspace_write.network_access=false -a never", manifest)
            self.assertIn("filesystem_isolation=bwrap read-only root", manifest)
            self.assertIn("validator=agent-tmux codex-code-map-validate-artifacts", manifest)
            self.assertTrue((artifact_dir / ".agent-tmux-runtime" / "codex-home").is_dir())
            self.assertIn(f"code-map sidecar session: {session}", result.stderr)
            self.assertIn(f"code-map sidecar artifact-dir: {artifact_dir}", result.stderr)
            self.assertIn(f"code-map sidecar log: /tmp/agent-tmux/{session}.log", result.stderr)

            env["AGENT_TMUX_CAPTURE"] = str(capture_second)
            env["AGENT_TMUX_PIPE_CAPTURE"] = str(tmp_path / "pipe-second.txt")
            env["AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT"] = str(artifact_root_second)
            result_second = subprocess.run(
                [
                    "bash",
                    "bin/agent-tmux",
                    "codex-code-map-sidecar",
                    str(repo),
                    "cp-123:branch point",
                    "Focus on runner wiring",
                ],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            self.assertEqual(result_second.returncode, 0, result_second.stderr)
            self.assertEqual(capture_second.read_text(encoding="utf-8").splitlines()[3], session)

    def test_agent_tmux_code_map_artifact_validator_accepts_map_patch_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            artifact_dir.mkdir()
            (artifact_dir / "SIDECAR_REQUEST.txt").write_text("session=s\n", encoding="utf-8")
            (artifact_dir / "MAP_REPORT.md").write_text("map report\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/docs/CODEBASE_ARCHITECTURE_INDEX.md b/docs/CODEBASE_ARCHITECTURE_INDEX.md\n"
                "--- a/docs/CODEBASE_ARCHITECTURE_INDEX.md\n"
                "+++ b/docs/CODEBASE_ARCHITECTURE_INDEX.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/.project-memory/code-map-state.json b/.project-memory/code-map-state.json\n"
                "--- a/.project-memory/code-map-state.json\n"
                "+++ b/.project-memory/code-map-state.json\n"
                "@@ -1 +1 @@\n"
                "-{}\n"
                "+{\"enabled\":true}\n",
                encoding="utf-8",
            )
            proposed = artifact_dir / "PROPOSED_FILES" / "docs" / "SUBSYSTEMS"
            proposed.mkdir(parents=True)
            (proposed / "contact.md").write_text("subsystem\n", encoding="utf-8")
            runtime = artifact_dir / ".agent-tmux-runtime" / "codex-home"
            runtime.mkdir(parents=True)
            (runtime / "session.json").write_text("{}\n", encoding="utf-8")
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("code-map artifact validation: ok", result.stdout)

    def test_agent_tmux_code_map_artifact_validator_rejects_traditional_unified_diff_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            artifact_dir.mkdir()
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/docs/CODE_MAP.md b/docs/CODE_MAP.md\n"
                "--- a/docs/CODE_MAP.md\n"
                "+++ b/docs/CODE_MAP.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "--- x/src/bad.py\n"
                "+++ x/src/bad.py\n"
                "@@ -1 +1 @@\n"
                "-bad\n"
                "+worse\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("unsupported code-map patch --- header: --- x/src/bad.py", result.stderr)
            self.assertIn("unsupported code-map patch +++ header: +++ x/src/bad.py", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_plain_unified_diff_even_for_map_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            artifact_dir.mkdir()
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "--- a/docs/CODE_MAP.md\n"
                "+++ b/docs/CODE_MAP.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("unsupported code-map patch --- header: --- a/docs/CODE_MAP.md", result.stderr)
            self.assertIn("unsupported code-map patch +++ header: +++ b/docs/CODE_MAP.md", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_non_map_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            artifact_dir.mkdir()
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/src/agent_terminal_contact/cli.py b/src/agent_terminal_contact/cli.py\n"
                "--- a/src/agent_terminal_contact/cli.py\n"
                "+++ b/src/agent_terminal_contact/cli.py\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/scripts/install.sh b/scripts/install.sh\n"
                "--- a/scripts/install.sh\n"
                "+++ b/scripts/install.sh\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n",
                encoding="utf-8",
            )
            proposed = artifact_dir / "PROPOSED_FILES" / "src"
            proposed.mkdir(parents=True)
            (proposed / "bad.py").write_text("bad\n", encoding="utf-8")
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid code-map artifact target (proposed file): src/bad.py", result.stderr)
            self.assertIn("invalid code-map artifact target (diff old path): src/agent_terminal_contact/cli.py", result.stderr)
            self.assertIn("invalid code-map artifact target (diff new path): scripts/install.sh", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_mixed_plain_unified_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            artifact_dir.mkdir()
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/docs/CODEBASE_ARCHITECTURE_INDEX.md b/docs/CODEBASE_ARCHITECTURE_INDEX.md\n"
                "--- a/docs/CODEBASE_ARCHITECTURE_INDEX.md\n"
                "+++ b/docs/CODEBASE_ARCHITECTURE_INDEX.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "--- src/agent_terminal_contact/cli.py\n"
                "+++ src/agent_terminal_contact/cli.py\n"
                "@@ -1 +1 @@\n"
                "-bad\n"
                "+worse\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("unsupported code-map patch --- header: --- src/agent_terminal_contact/cli.py", result.stderr)
            self.assertIn("unsupported code-map patch +++ header: +++ src/agent_terminal_contact/cli.py", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_binary_patch_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            artifact_dir.mkdir()
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/docs/CODE_MAP.md b/docs/CODE_MAP.md\n"
                "GIT binary patch\n"
                "literal 4\n"
                "abcd\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("unsupported code-map binary patch content: GIT binary patch", result.stderr)
            self.assertIn("unsupported code-map binary patch content: literal 4", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_tab_suffixed_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            proposed = artifact_dir / "PROPOSED_FILES" / "docs"
            proposed.mkdir(parents=True)
            (proposed / "CODE_MAP.md\tshadow").write_text("bad\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/docs/CODE_MAP.md\tshadow b/docs/CODE_MAP.md\tshadow\n"
                "--- a/docs/CODE_MAP.md\tshadow\n"
                "+++ b/docs/CODE_MAP.md\tshadow\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid code-map artifact target (proposed file): docs/CODE_MAP.md\tshadow", result.stderr)
            self.assertIn("invalid code-map artifact target (diff old path): docs/CODE_MAP.md\tshadow", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_codex_auth_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            codex_home = tmp_path / "codex-home"
            codex_home.mkdir()
            token = "sk-test-" + ("a" * 64)
            (codex_home / "auth.json").write_text(
                f'{{"access_token":"{token}","refresh_token":"{"b" * 64}"}}\n',
                encoding="utf-8",
            )
            artifact_dir = tmp_path / "artifact"
            artifact_dir.mkdir()
            (artifact_dir / "MAP_REPORT.md").write_text(
                f"leaked token: {token}\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("code-map artifact appears to contain Codex auth material: MAP_REPORT.md", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_structural_auth_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory"
            proposed.mkdir(parents=True)
            (proposed / "auth.json").write_text(
                '{"access_token":"not-the-current-token-but-still-auth-shaped"}\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn(
                "code-map artifact appears to contain Codex auth/session structure: PROPOSED_FILES/.project-memory/auth.json",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_binary_proposed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            proposed = artifact_dir / "PROPOSED_FILES" / "docs" / "SUBSYSTEMS"
            proposed.mkdir(parents=True)
            (proposed / "binary.md").write_bytes(b"map\x00binary\n")
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("code-map artifact must be text, not binary: PROPOSED_FILES/docs/SUBSYSTEMS/binary.md", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_removes_auth_patterns_after_patch_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            codex_home = tmp_path / "codex-home"
            codex_home.mkdir()
            token = "sk-test-" + ("c" * 64)
            (codex_home / "auth.json").write_text(
                f'{{"access_token":"{token}"}}\n',
                encoding="utf-8",
            )
            scratch_tmp = tmp_path / "scratch-tmp"
            scratch_tmp.mkdir()
            artifact_dir = tmp_path / "artifact"
            artifact_dir.mkdir()
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "not a patch\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"CODEX_HOME": str(codex_home), "TMPDIR": str(scratch_tmp), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("code-map patch artifact contains no target paths", result.stderr)
            self.assertFalse(any(scratch_tmp.iterdir()))

    def test_agent_tmux_code_map_artifact_validator_rejects_symlink_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            proposed = artifact_dir / "PROPOSED_FILES" / "docs" / "SUBSYSTEMS"
            proposed.mkdir(parents=True)
            (proposed / "sidecar.md").symlink_to("/etc/passwd")
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid code-map artifact entry (symlink): PROPOSED_FILES/docs/SUBSYSTEMS/sidecar.md", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_runtime_symlink_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            runtime = artifact_dir / ".agent-tmux-runtime" / "codex-home"
            runtime.mkdir(parents=True)
            (runtime / "unsafe-link").symlink_to("/etc/passwd")
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid code-map artifact entry (symlink): .agent-tmux-runtime/codex-home/unsafe-link", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_root_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            artifact_dir.mkdir()
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/docs/CODE_MAP.md b/docs/CODE_MAP.md\n"
                "--- a/docs/CODE_MAP.md\n"
                "+++ b/docs/CODE_MAP.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n",
                encoding="utf-8",
            )
            artifact_link = tmp_path / "artifact-link"
            artifact_link.symlink_to(artifact_dir, target_is_directory=True)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_link)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("code-map artifact directory must not be a symlink", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_symlink_patch_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            artifact_dir.mkdir()
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/docs/SUBSYSTEMS/sidecar.md b/docs/SUBSYSTEMS/sidecar.md\n"
                "new file mode 120000\n"
                "index 0000000..1111111 120000\n"
                "--- /dev/null\n"
                "+++ b/docs/SUBSYSTEMS/sidecar.md\n"
                "@@ -0,0 +1 @@\n"
                "+/etc/passwd\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid code-map patch file mode: 120000", result.stderr)
            self.assertIn("invalid code-map patch index mode: 120000", result.stderr)

    def test_agent_tmux_code_map_sidecar_refuses_nonempty_artifact_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            capture_second = tmp_path / "args-second.txt"
            artifact_root = tmp_path / "artifacts"
            delegate = write_code_map_delegate(tmp_path, has_rc=1)
            fake_bin = write_fake_tmux(tmp_path)
            env = {
                "AGENT_TMUX_DELEGATE": str(delegate),
                "AGENT_TMUX_CAPTURE": str(capture),
                "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(artifact_root),
                "HOME": str(tmp_path / "home"),
                "PATH": f"{fake_bin}:{TEST_PATH}",
            }
            first = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-sidecar", str(repo), "cp-123", "Focus"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            env["AGENT_TMUX_CAPTURE"] = str(capture_second)
            second = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-sidecar", str(repo), "cp-123", "Focus"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            self.assertEqual(second.returncode, 2)
            self.assertIn("code-map artifact directory already exists", second.stderr)
            self.assertFalse(capture_second.exists())

    def test_agent_tmux_code_map_sidecar_refuses_preexisting_empty_artifact_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            artifact_root = tmp_path / "artifacts"
            artifact_root.mkdir()
            session = code_map_session_name(repo, "cp-123")
            (artifact_root / session).mkdir()
            delegate = write_code_map_delegate(tmp_path, has_rc=1)
            fake_bin = write_fake_tmux(tmp_path)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-sidecar", str(repo), "cp-123", "Focus"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                    "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(artifact_root),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("code-map artifact directory already exists", result.stderr)
            self.assertFalse(capture.exists())

    def test_agent_tmux_code_map_sidecar_refuses_artifact_root_inside_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            delegate = write_code_map_delegate(tmp_path, has_rc=1)
            fake_bin = write_fake_tmux(tmp_path)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-sidecar", str(repo), "cp-123", "Focus"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                    "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(repo / ".sidecars"),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("code-map artifact directory must not be inside the repository root", result.stderr)
            self.assertFalse(capture.exists())
            self.assertFalse((repo / ".sidecars").exists())

    def test_agent_tmux_code_map_sidecar_refuses_symlink_artifact_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            symlink_target = repo / "sidecar-target"
            symlink_target.mkdir()
            artifact_root = tmp_path / "artifacts"
            artifact_root.mkdir()
            session = code_map_session_name(repo, "cp-123")
            (artifact_root / session).symlink_to(symlink_target, target_is_directory=True)
            capture = tmp_path / "args.txt"
            delegate = write_code_map_delegate(tmp_path, has_rc=1)
            fake_bin = write_fake_tmux(tmp_path)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-sidecar", str(repo), "cp-123", "Focus"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                    "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(artifact_root),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("code-map artifact directory must not be a symlink", result.stderr)
            self.assertFalse(capture.exists())
            self.assertFalse((symlink_target / "SIDECAR_REQUEST.txt").exists())
            self.assertFalse((symlink_target / ".agent-tmux-runtime").exists())

    def test_agent_tmux_code_map_sidecar_refuses_tmux_new_session_race(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            artifact_root = tmp_path / "artifacts"
            delegate = write_code_map_delegate(tmp_path, has_rc=1)
            fake_bin = write_fake_tmux(tmp_path)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-sidecar", str(repo), "cp-123", "Focus"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                    "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(artifact_root),
                    "AGENT_TMUX_FAIL_NEW": "1",
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("failed to start new code-map sidecar session", result.stderr)
            self.assertIn("duplicate session", result.stderr)
            self.assertFalse(any(artifact_root.iterdir()))

    def test_agent_tmux_code_map_sidecar_cleans_artifact_directory_on_pipe_log_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            artifact_root = tmp_path / "artifacts"
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
                "fi\n"
                "if [ \"$1\" = log ]; then\n"
                "  printf '/tmp/agent-tmux/%s.log\\n' \"$2\"\n"
                "  exit 0\n"
                "fi\n"
                "if [ \"$1\" = pipe-log ]; then\n"
                "  printf 'pipe failed\\n' >&2\n"
                "  exit 2\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            fake_bin = write_fake_tmux(tmp_path)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-sidecar", str(repo), "cp-123", "Focus"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(artifact_root),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("failed to enable log pipe for code-map sidecar session", result.stderr)
            self.assertFalse(any(artifact_root.iterdir()))

    def test_agent_tmux_code_map_sidecar_refuses_log_path_failure_before_artifact_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            artifact_root = tmp_path / "artifacts"
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
                "fi\n"
                "if [ \"$1\" = log ]; then\n"
                "  printf 'log failed\\n' >&2\n"
                "  exit 2\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            fake_bin = write_fake_tmux(tmp_path)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-sidecar", str(repo), "cp-123", "Focus"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(artifact_root),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("failed to resolve code-map sidecar log path", result.stderr)
            self.assertFalse(capture.exists())
            self.assertFalse(artifact_root.exists())

    def test_agent_tmux_code_map_permissions_are_accepted_by_codex_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = str(Path(tmp) / "codex-home")
            result = subprocess.run(
                [
                    "codex",
                    "debug",
                    "prompt-input",
                    "-c",
                    "sandbox_mode=workspace-write",
                    "-c",
                    "sandbox_workspace_write.network_access=false",
                    "-c",
                    f'permissions.filesystem.deny_read=["{codex_home}"]',
                    "x",
                ],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": TEST_PATH},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("`sandbox_mode` is `workspace-write`", result.stdout)
            self.assertIn("Network access is restricted", result.stdout)

    def test_agent_tmux_code_map_sidecar_refuses_existing_session_before_log_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            log_probe = tmp_path / "log-probe.txt"
            delegate = write_code_map_delegate(tmp_path, has_rc=0)
            fake_bin = write_fake_tmux(tmp_path)
            result = subprocess.run(
                [
                    "bash",
                    "bin/agent-tmux",
                    "codex-code-map-sidecar",
                    str(repo),
                    "cp-123",
                    "Focus",
                ],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_LOG_PROBE": str(log_probe),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("requested session already exists: codex-map-example-repo-cp-123-", result.stderr)
            self.assertFalse(capture.exists())
            self.assertFalse(log_probe.exists())

    def test_agent_tmux_code_map_sidecar_fork_maps_session_id_to_codex_fork(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            artifact_root = tmp_path / "artifacts"
            codex_home = tmp_path / "codex-home"
            session_path = codex_home / "sessions" / "2026" / "05" / "12"
            session_path.mkdir(parents=True)
            delegate = write_code_map_delegate(tmp_path, has_rc=1)
            fake_bin = write_fake_tmux(tmp_path)
            session_id = "12345678-1234-1234-1234-123456789abc"
            (session_path / f"rollout-2026-05-12T00-00-00-{session_id}.jsonl").write_text(
                "{\"session\":\"fixture\"}\n",
                encoding="utf-8",
            )
            (codex_home / "session_index.jsonl").write_text(
                f"fixture {session_id}\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "bash",
                    "bin/agent-tmux",
                    "codex-code-map-sidecar-fork",
                    str(repo),
                    "ticket58-pre-edit",
                    session_id,
                    "Map the launch path only",
                ],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                    "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(artifact_root),
                    "CODEX_HOME": str(codex_home),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = capture.read_text(encoding="utf-8").splitlines()
            session = lines[3]
            artifact_dir = artifact_root / session
            command = lines[6]
            self.assertIn("/lib/node_modules/@openai/codex/bin/codex.js -c sandbox_mode=workspace-write -c sandbox_workspace_write.network_access=false -a never", command)
            self.assertIn("permissions.filesystem.deny_read=", command)
            self.assertIn(f"{artifact_dir}/.agent-tmux-runtime/codex-home", command)
            self.assertIn(f"-C {artifact_dir} fork {session_id}", command)
            copied_sessions = list((artifact_dir / ".agent-tmux-runtime" / "codex-home" / "sessions").rglob("*.jsonl"))
            self.assertEqual(len(copied_sessions), 1)
            self.assertEqual(copied_sessions[0].read_text(encoding="utf-8"), "{\"session\":\"fixture\"}\n")
            self.assertIn(
                session_id,
                (artifact_dir / ".agent-tmux-runtime" / "codex-home" / "session_index.jsonl").read_text(encoding="utf-8"),
            )
            self.assertRegex(session, r"^codex-map-repo-ticket58-pre-edit-[0-9a-f]{12}$")
            self.assertIn("Map the launch path only", command)

    def test_agent_tmux_code_map_sidecar_fork_refuses_missing_codex_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            artifact_root = tmp_path / "artifacts"
            codex_home = tmp_path / "codex-home"
            (codex_home / "sessions").mkdir(parents=True)
            delegate = write_code_map_delegate(tmp_path, has_rc=1)
            fake_bin = write_fake_tmux(tmp_path)
            session_id = "12345678-1234-1234-1234-123456789abc"
            result = subprocess.run(
                [
                    "bash",
                    "bin/agent-tmux",
                    "codex-code-map-sidecar-fork",
                    str(repo),
                    "ticket58-pre-edit",
                    session_id,
                    "Map the launch path only",
                ],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                    "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(artifact_root),
                    "CODEX_HOME": str(codex_home),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Codex session UUID not found", result.stderr)
            self.assertFalse(capture.exists())
            self.assertFalse(artifact_root.exists())
            self.assertNotIn("code-map sidecar session:", result.stderr)

    def test_agent_tmux_code_map_sidecar_fork_refuses_ambiguous_codex_session_uuid(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            artifact_root = tmp_path / "artifacts"
            codex_home = tmp_path / "codex-home"
            session_path = codex_home / "sessions" / "2026" / "05" / "12"
            second_session_path = codex_home / "sessions" / "2026" / "05" / "13"
            session_path.mkdir(parents=True)
            second_session_path.mkdir(parents=True)
            delegate = write_code_map_delegate(tmp_path, has_rc=1)
            fake_bin = write_fake_tmux(tmp_path)
            session_id = "12345678-1234-1234-1234-123456789abc"
            (session_path / f"rollout-2026-05-12T00-00-00-{session_id}.jsonl").write_text(
                "{\"session\":\"first\"}\n",
                encoding="utf-8",
            )
            (second_session_path / f"rollout-2026-05-13T00-00-00-{session_id}.jsonl").write_text(
                "{\"session\":\"second\"}\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "bash",
                    "bin/agent-tmux",
                    "codex-code-map-sidecar-fork",
                    str(repo),
                    "ticket58-pre-edit",
                    session_id,
                    "Map the launch path only",
                ],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                    "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(artifact_root),
                    "CODEX_HOME": str(codex_home),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Codex session UUID matched multiple files", result.stderr)
            self.assertFalse(capture.exists())
            self.assertFalse(artifact_root.exists())
            self.assertNotIn("code-map sidecar session:", result.stderr)

    def test_agent_tmux_code_map_sidecar_fork_refuses_non_uuid_anchor_session(self):
        cases = ["--last", "Thread Name", "codex fork 12345678-1234-1234-1234-123456789abc"]
        for session_id in cases:
            with self.subTest(session_id=session_id):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    repo = tmp_path / "Repo"
                    repo.mkdir()
                    capture = tmp_path / "args.txt"
                    delegate = write_code_map_delegate(tmp_path, has_rc=1)
                    fake_bin = write_fake_tmux(tmp_path)
                    result = subprocess.run(
                        [
                            "bash",
                            "bin/agent-tmux",
                            "codex-code-map-sidecar-fork",
                            str(repo),
                            "ticket58-pre-edit",
                            session_id,
                            "Map the launch path only",
                        ],
                        cwd=ROOT,
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env={
                            "AGENT_TMUX_DELEGATE": str(delegate),
                            "AGENT_TMUX_CAPTURE": str(capture),
                            "HOME": str(tmp_path / "home"),
                            "PATH": f"{fake_bin}:{TEST_PATH}",
                        },
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("requires a Codex session UUID", result.stderr)
                    self.assertFalse(capture.exists())

    def test_agent_tmux_resume_latest_full_resolves_thread_before_prompt(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            capture = tmp_path / "args.txt"
            env_capture = tmp_path / "env.txt"
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
                "fi\n"
                "if [ \"$1\" = codex-latest ]; then\n"
                "  printf 'Thread Name\\tid-123\\t2026-05-12T00:00:00Z\\t/tmp/session.jsonl\\n'\n"
                "  exit 0\n"
                "fi\n"
                "printf '%s\\n' \"${AGENT_TMUX_ALLOW_DUPLICATE:-}\" >\"${AGENT_TMUX_ENV_CAPTURE}\"\n"
                "printf '%s\\n' \"$@\" >\"${AGENT_TMUX_CAPTURE}\"\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-resume-latest-full", "sess", repo, "Please", "do", "work"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_ENV_CAPTURE": str(env_capture),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(env_capture.read_text(encoding="utf-8").strip(), "1")
            self.assertEqual(
                capture.read_text(encoding="utf-8").splitlines(),
                [
                    "codex",
                    "sess",
                    repo,
                    "-s",
                    "danger-full-access",
                    "-a",
                    "never",
                    "resume",
                    "Thread Name",
                    "Please do work",
                ],
            )

    def test_agent_tmux_resume_latest_full_refuses_existing_session_before_thread_lookup(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            capture = tmp_path / "args.txt"
            latest_capture = tmp_path / "latest.txt"
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 0\n"
                "fi\n"
                "if [ \"$1\" = codex-latest ]; then\n"
                "  printf 'called\\n' >\"${AGENT_TMUX_LATEST_CAPTURE}\"\n"
                "  exit 2\n"
                "fi\n"
                "printf '%s\\n' \"$@\" >\"${AGENT_TMUX_CAPTURE}\"\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-resume-latest-full", "sess", repo, "Please do work"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_LATEST_CAPTURE": str(latest_capture),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("requested session already exists: sess", result.stderr)
            self.assertFalse(capture.exists())
            self.assertFalse(latest_capture.exists())

    def test_agent_tmux_legacy_full_profile_resume_latest_uses_deterministic_route(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            capture = tmp_path / "args.txt"
            env_capture = tmp_path / "env.txt"
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
                "fi\n"
                "if [ \"$1\" = codex-latest ]; then\n"
                "  printf 'Thread Name\\tid-123\\t2026-05-12T00:00:00Z\\t/tmp/session.jsonl\\n'\n"
                "  exit 0\n"
                "fi\n"
                "printf '%s\\n' \"${AGENT_TMUX_ALLOW_DUPLICATE:-}\" >\"${AGENT_TMUX_ENV_CAPTURE}\"\n"
                "printf '%s\\n' \"$@\" >\"${AGENT_TMUX_CAPTURE}\"\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                [
                    "bash",
                    "bin/agent-tmux",
                    "codex-resume-latest",
                    "sess",
                    repo,
                    "-s",
                    "danger-full-access",
                    "-a",
                    "never",
                    "Please",
                    "do",
                    "work",
                ],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_ENV_CAPTURE": str(env_capture),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(env_capture.read_text(encoding="utf-8").strip(), "1")
            self.assertEqual(
                capture.read_text(encoding="utf-8").splitlines(),
                [
                    "codex",
                    "sess",
                    repo,
                    "-s",
                    "danger-full-access",
                    "-a",
                    "never",
                    "resume",
                    "Thread Name",
                    "Please do work",
                ],
            )

    def test_agent_tmux_legacy_full_profile_resume_latest_refuses_existing_session_before_thread_lookup(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            capture = tmp_path / "args.txt"
            latest_capture = tmp_path / "latest.txt"
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 0\n"
                "fi\n"
                "if [ \"$1\" = codex-latest ]; then\n"
                "  printf 'called\\n' >\"${AGENT_TMUX_LATEST_CAPTURE}\"\n"
                "  exit 2\n"
                "fi\n"
                "printf '%s\\n' \"$@\" >\"${AGENT_TMUX_CAPTURE}\"\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                [
                    "bash",
                    "bin/agent-tmux",
                    "codex-resume-latest",
                    "sess",
                    repo,
                    "-s",
                    "danger-full-access",
                    "-a",
                    "never",
                    "Please do work",
                ],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_LATEST_CAPTURE": str(latest_capture),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("requested session already exists: sess", result.stderr)
            self.assertFalse(capture.exists())
            self.assertFalse(latest_capture.exists())

    def test_agent_tmux_legacy_full_profile_resume_uses_deterministic_route(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            capture = tmp_path / "args.txt"
            env_capture = tmp_path / "env.txt"
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
                "fi\n"
                "printf '%s\\n' \"${AGENT_TMUX_ALLOW_DUPLICATE:-}\" >\"${AGENT_TMUX_ENV_CAPTURE}\"\n"
                "printf '%s\\n' \"$@\" >\"${AGENT_TMUX_CAPTURE}\"\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                [
                    "bash",
                    "bin/agent-tmux",
                    "codex-resume",
                    "sess",
                    repo,
                    "Thread Name",
                    "-s",
                    "danger-full-access",
                    "-a",
                    "never",
                    "Please",
                    "do",
                    "work",
                ],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_ENV_CAPTURE": str(env_capture),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(env_capture.read_text(encoding="utf-8").strip(), "1")
            self.assertEqual(
                capture.read_text(encoding="utf-8").splitlines(),
                [
                    "codex",
                    "sess",
                    repo,
                    "-s",
                    "danger-full-access",
                    "-a",
                    "never",
                    "resume",
                    "Thread Name",
                    "Please do work",
                ],
            )

    def test_agent_tmux_non_full_codex_commands_use_requested_session(self):
        cases = [
            (
                ["codex", "sess", "{repo}", "--model", "gpt-5.5"],
                ["codex", "sess", "{repo}", "--model", "gpt-5.5"],
            ),
            (
                ["codex-resume", "sess", "{repo}", "Thread Name", "Please", "do", "work"],
                ["codex-resume", "sess", "{repo}", "Thread Name", "Please", "do", "work"],
            ),
            (
                ["codex-resume-latest", "sess", "{repo}", "Please", "do", "work"],
                ["codex-resume-latest", "sess", "{repo}", "Please", "do", "work"],
            ),
        ]
        for argv_template, expected_template in cases:
            with self.subTest(command=argv_template[0]):
                with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
                    argv = [repo if arg == "{repo}" else arg for arg in argv_template]
                    expected = [repo if arg == "{repo}" else arg for arg in expected_template]
                    tmp_path = Path(tmp)
                    capture = tmp_path / "args.txt"
                    env_capture = tmp_path / "env.txt"
                    delegate = tmp_path / "delegate-agent-tmux"
                    delegate.write_text(
                        "#!/usr/bin/env bash\n"
                        "if [ \"$1\" = has ]; then\n"
                        "  exit 1\n"
                        "fi\n"
                        "printf '%s\\n' \"${AGENT_TMUX_ALLOW_DUPLICATE:-}\" >\"${AGENT_TMUX_ENV_CAPTURE}\"\n"
                        "printf '%s\\n' \"$@\" >\"${AGENT_TMUX_CAPTURE}\"\n",
                        encoding="utf-8",
                    )
                    delegate.chmod(0o755)
                    result = subprocess.run(
                        ["bash", "bin/agent-tmux", *argv],
                        cwd=ROOT,
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env={
                            "AGENT_TMUX_DELEGATE": str(delegate),
                            "AGENT_TMUX_CAPTURE": str(capture),
                            "AGENT_TMUX_ENV_CAPTURE": str(env_capture),
                            "PATH": "/usr/bin:/bin",
                        },
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(env_capture.read_text(encoding="utf-8").strip(), "1")
                    self.assertEqual(capture.read_text(encoding="utf-8").splitlines(), expected)

    def test_agent_tmux_non_full_codex_commands_refuse_existing_requested_session(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            capture = tmp_path / "args.txt"
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 0\n"
                "fi\n"
                "printf '%s\\n' \"$@\" >\"${AGENT_TMUX_CAPTURE}\"\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-resume-latest", "sess", repo, "Please do work"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("requested session already exists: sess", result.stderr)
            self.assertFalse(capture.exists())

    def test_agent_tmux_regular_command_delegates_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            capture = tmp_path / "args.txt"
            env_capture = tmp_path / "env.txt"
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"${AGENT_TMUX_ALLOW_DUPLICATE:-}\" >\"${AGENT_TMUX_ENV_CAPTURE}\"\n"
                "printf '%s\\n' \"$@\" >\"${AGENT_TMUX_CAPTURE}\"\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "log", "sess"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_ENV_CAPTURE": str(env_capture),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(env_capture.read_text(encoding="utf-8").strip(), "")
            self.assertEqual(capture.read_text(encoding="utf-8").splitlines(), ["log", "sess"])

    def test_agent_tmux_codex_existing_empty_absence_gets_explicit_message(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            delegate = Path(tmp) / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = codex-existing ]; then\n"
                "  exit 1\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-existing", repo],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual("", result.stdout)
            self.assertIn("no Codex tmux session found for workdir:", result.stderr)
            self.assertIn(repo, result.stderr)

    def test_agent_tmux_codex_existing_existing_session_is_delegated_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            env_capture = Path(tmp) / "env.txt"
            delegate = Path(tmp) / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = codex-existing ]; then\n"
                "  printf '%s\\n' \"${AGENT_TMUX_ALLOW_DUPLICATE:-}\" >\"${AGENT_TMUX_ENV_CAPTURE}\"\n"
                "  printf 'owner-session\\n'\n"
                "  exit 0\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-existing", repo],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_ENV_CAPTURE": str(env_capture),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual("owner-session\n", result.stdout)
            self.assertEqual("", result.stderr)
            self.assertEqual(env_capture.read_text(encoding="utf-8").strip(), "")

    def test_agent_tmux_codex_existing_failure_detail_is_not_absence(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            delegate = Path(tmp) / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = codex-existing ]; then\n"
                "  printf 'agent-tmux: multiple detached Codex tmux sessions\\n' >&2\n"
                "  exit 3\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-existing", repo],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 3)
            self.assertEqual("", result.stdout)
            self.assertEqual("agent-tmux: multiple detached Codex tmux sessions\n", result.stderr)
            self.assertNotIn("no Codex tmux session found", result.stderr)

    def test_agent_tmux_resume_latest_full_rejects_malformed_latest_output(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            delegate = Path(tmp) / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
                "fi\n"
                "if [ \"$1\" = codex-latest ]; then\n"
                "  echo malformed-success-line-without-tabs\n"
                "  exit 0\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-resume-latest-full", "sess", repo, "Please do work"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("codex-latest returned malformed output", result.stderr)

    def test_agent_tmux_resume_latest_full_rejects_latest_extra_output_line(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            delegate = Path(tmp) / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
                "fi\n"
                "if [ \"$1\" = codex-latest ]; then\n"
                "  printf 'Thread\\tid-123\\t2026-05-12T00:00:00Z\\t/tmp/session.jsonl\\nextra\\n'\n"
                "  exit 0\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-resume-latest-full", "sess", repo, "Please do work"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("codex-latest returned malformed output", result.stderr)

    def test_agent_tmux_resume_latest_full_rejects_latest_stderr_warning(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            delegate = Path(tmp) / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
                "fi\n"
                "if [ \"$1\" = codex-latest ]; then\n"
                "  printf 'warning: stale state\\n' >&2\n"
                "  printf 'Thread\\tid-123\\t2026-05-12T00:00:00Z\\t/tmp/session.jsonl\\n'\n"
                "  exit 0\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-resume-latest-full", "sess", repo, "Please do work"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("warning: stale state", result.stderr)
            self.assertIn("codex-latest wrote stderr", result.stderr)

    def test_agent_tmux_full_alias_rejects_bypass_flag(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            capture = tmp_path / "args.txt"
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$@\" >\"${AGENT_TMUX_CAPTURE}\"\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                [
                    "bash",
                    "bin/agent-tmux",
                    "codex-full",
                    "sess",
                    repo,
                    "--dangerously-bypass-approvals-and-sandbox",
                ],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("must use -s danger-full-access -a never", result.stderr)
            self.assertFalse(capture.exists())


if __name__ == "__main__":
    unittest.main()
