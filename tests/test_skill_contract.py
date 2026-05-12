import subprocess
import tempfile
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
        self.assertIn("Normal user-launched `codex` chats are not tmux-managed by default", text)
        self.assertIn("Before spawning any tmux worker, identify whether the repo's active lane is\nCodex or Claude", text)
        self.assertIn("Do not choose the provider from the supervising agent", text)
        self.assertIn("If the signals disagree, if both providers have plausible active chats", text)
        self.assertIn("do not start\na fresh chat first", text)
        self.assertIn("agent-tmux codex-latest", text)
        self.assertIn("agent-tmux codex-resume-latest", text)
        self.assertIn("Only use `agent-tmux codex <session> <repo>`", text)
        self.assertIn("Unexpected visible composer text in a tmux-managed agent is stale session", text)
        self.assertIn("Stale contact residue created by a failed `agent-contact` attempt", text)
        self.assertIn("agent-tmux clear-input <session>", text)
        self.assertIn("known to be a human draft", text)
        self.assertIn("continue through guarded `agent-contact`", text)
        self.assertIn("after the prompt is idle", text)
        self.assertIn("If `agent-contact` refuses, stop", text)
        self.assertIn("agent-contact trust-roots", text)
        self.assertIn("## Codex Worker Permission Profile", text)
        self.assertIn("agent-tmux codex-full <session> <repo>", text)
        self.assertIn(
            "agent-tmux codex-resume-full <session> <repo> <thread-name-or-id>",
            text,
        )
        self.assertIn("agent-tmux codex-resume-latest-full <session> <repo>", text)
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
