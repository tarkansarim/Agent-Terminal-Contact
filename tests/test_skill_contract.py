import hashlib
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_PATH = os.environ.get("PATH", "/usr/bin:/bin")
SIDECAR_REQUEST_PERMISSION = "-c sandbox_mode=workspace-write -c sandbox_workspace_write.network_access=false -a never"
SIDECAR_REQUEST_FILESYSTEM_ISOLATION = (
    "bwrap minimal root, selected host tool files only, private /tmp and /run, "
    "artifact directory writable for map output, separate wrapper-owned runtime directory"
)


def code_map_session_name(repo, anchor):
    def slug_component(raw):
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw.lower())
        slug = re.sub(r"-+", "-", slug).strip("-")[:32].rstrip("-")
        return slug or "x"

    digest = hashlib.sha256(f"{repo.resolve()}\n{anchor}".encode("utf-8")).hexdigest()[:12]
    return f"codex-map-{slug_component(repo.name)}-{slug_component(anchor)}-{digest}"


def write_validator_sidecar_manifest(artifact_dir, *, repo=None, anchor="test-anchor"):
    artifact_path = Path(artifact_dir)
    repo_path = Path(repo) if repo is not None else artifact_path.parent / "repo"
    registry_dir = artifact_path.parent / ".agent-tmux-sidecar-registry"
    repo_path.mkdir(parents=True, exist_ok=True)
    artifact_path.mkdir(parents=True, exist_ok=True)
    content = (
        f"session={artifact_path.name}\n"
        f"repo={repo_path.resolve()}\n"
        f"anchor={anchor}\n"
        f"allowed_output_dir={artifact_path.resolve()}\n"
        f"permission={SIDECAR_REQUEST_PERMISSION}\n"
        f"filesystem_isolation={SIDECAR_REQUEST_FILESYSTEM_ISOLATION}\n"
        f"validator=agent-tmux codex-code-map-validate-artifacts {artifact_path.resolve()}\n"
    )
    (artifact_path / "SIDECAR_REQUEST.txt").write_text(content, encoding="utf-8")
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / f"{artifact_path.name}.txt").write_text(content, encoding="utf-8")
    return repo_path


def write_code_map_delegate(tmp_path, *, has_rc=1, pipe_rc=0):
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
        f"  exit {pipe_rc}\n"
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
    state_file = tmp_path / "fake-tmux-session-state"
    tmux.write_text(
        "#!/usr/bin/env bash\n"
        f"STATE_FILE={str(state_file)!r}\n"
        "case \"$1\" in\n"
        "  start-server|set-option|set-window-option)\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n"
        "if [ \"$1\" = new-session ]; then\n"
        "  if [ \"${AGENT_TMUX_FAIL_NEW:-0}\" = 1 ]; then\n"
        "    printf 'duplicate session\\n' >&2\n"
        "    exit 1\n"
        "  fi\n"
        "  printf 'live\\n' >\"$STATE_FILE\"\n"
        "  printf '%s\\n' \"$@\" >\"${AGENT_TMUX_CAPTURE}\"\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = capture-pane ]; then\n"
        "  printf 'fake captured pane\\n'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = pipe-pane ]; then\n"
        "  if [ \"${AGENT_TMUX_FAIL_PIPE:-0}\" = 1 ]; then\n"
        "    printf 'forced pipe failure\\n' >&2\n"
        "    exit 1\n"
        "  fi\n"
        "  if [ -n \"${AGENT_TMUX_PIPE_CAPTURE:-}\" ]; then\n"
        "    printf '%s\\n' \"$4\" >\"${AGENT_TMUX_PIPE_CAPTURE}\"\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = kill-session ]; then\n"
        "  if [ \"${AGENT_TMUX_FAIL_KILL:-0}\" = 1 ]; then\n"
        "    printf 'forced kill failure\\n' >&2\n"
        "    exit 1\n"
        "  fi\n"
        "  rm -f \"$STATE_FILE\"\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = has-session ]; then\n"
        "  [ -f \"$STATE_FILE\" ] && exit 0\n"
        "  exit ${AGENT_TMUX_INITIAL_HAS_SESSION_RC:-1}\n"
        "fi\n"
        "printf 'unexpected tmux command: %s\\n' \"$*\" >&2\n"
        "exit 2\n",
        encoding="utf-8",
    )
    tmux.chmod(0o755)
    return bin_dir


def write_codex_latest_fixture(tmp_path, repo, *, thread_name="Thread Name", session_id=None, updated_at="2026-05-12T00:00:00Z"):
    codex_home = Path(tmp_path) / "codex-home"
    sessions = codex_home / "sessions" / "2026" / "05" / "12"
    sessions.mkdir(parents=True, exist_ok=True)
    session_id = session_id or "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    (codex_home / "session_index.jsonl").write_text(
        json.dumps(
            {
                "id": session_id,
                "thread_name": thread_name,
                "updated_at": updated_at,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (sessions / f"rollout-2026-05-12T00-00-00-{session_id}.jsonl").write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "cwd": str(Path(repo).resolve()),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return codex_home


def write_fake_chmod(bin_dir, body):
    chmod = Path(bin_dir) / "chmod"
    chmod.write_text(
        "#!/usr/bin/env bash\n" + body,
        encoding="utf-8",
    )
    chmod.chmod(0o755)


def write_fake_stat(bin_dir, body):
    stat = Path(bin_dir) / "stat"
    stat.write_text(
        "#!/usr/bin/env bash\n" + body,
        encoding="utf-8",
    )
    stat.chmod(0o755)


def write_fake_find(bin_dir):
    find = Path(bin_dir) / "find"
    find.write_text(
        "#!/usr/bin/env bash\n"
        "if [ -n \"${AGENT_TMUX_FAKE_FIND_ENTRY:-}\" ]; then\n"
        "  printf '%s\\0' \"${AGENT_TMUX_FAKE_FIND_ENTRY}\"\n"
        "fi\n"
        "printf 'forced find traversal failure\\n' >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    find.chmod(0o755)


def write_fake_mktemp(bin_dir):
    mktemp = Path(bin_dir) / "mktemp"
    mktemp.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'forced mktemp failure\\n' >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    mktemp.chmod(0o755)


class SkillContractTests(unittest.TestCase):
    def test_skill_description_is_compact_and_body_preserves_discovery_details(self):
        text = (ROOT / "skills" / "agent-tmux-control" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        match = re.match(r"---\n(?P<frontmatter>.*?)\n---\n(?P<body>.*)", text, re.S)
        self.assertIsNotNone(match)
        description_match = re.search(
            r'^description: "(?P<description>[^"]+)"$',
            match.group("frontmatter"),
            re.M,
        )
        self.assertIsNotNone(description_match)
        description = description_match.group("description")
        body = match.group("body")

        self.assertLessEqual(len(description), 260)
        for trigger in (
            "agent-tmux",
            "agent-contact",
            "repo agent",
            "latest Codex chat",
            "provider mismatch",
            "guarded contact",
            "unsafe raw PTY",
        ):
            self.assertIn(trigger, description)

        for moved_detail in (
            "Before spawning any tmux worker, identify whether the repo's active lane is\nCodex or Claude",
            "contacting or communicating with another terminal\nCodex/Claude repo agent",
            "finding or resuming the latest Codex chat in a repo",
            "provider\nmismatch refusals",
            "Do not use this skill for ordinary one-shot shell commands",
        ):
            self.assertIn(moved_detail, body)

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
        self.assertIn("native Claude version binary printed by `agent-contact trust-roots`", text)
        self.assertIn("fail closed before launch/contact", text)
        self.assertIn("--provider claude", text)
        self.assertIn("owner-ComfyComannder-109-claude", text)
        self.assertIn("do not start\na fresh chat first", text)
        self.assertIn("agent-tmux codex-latest", text)
        self.assertIn("agent-tmux codex-resume-latest", text)
        self.assertIn("Only use `agent-tmux codex <session> <repo>`", text)
        self.assertIn("visible composer text is\n  a control surface", text)
        self.assertIn("reports `would_clear_and_send`", text)
        self.assertIn("real send clears the composer before sending a fresh guarded payload", text)
        self.assertIn("starter placeholder text, stale\n  `CONTACT_ID`/`MESSAGE_JSON` residue", text)
        self.assertIn("arbitrary leftover worker composer text", text)
        self.assertIn("attached sessions, busy/working\n  panes, trust prompts, approval prompts", text)
        self.assertIn("agent-tmux clear-input <session>", text)
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
        self.assertIn("writable map-output\npath", text)
        self.assertIn("PROPOSED_CHANGES.patch", text)
        self.assertIn("requires the wrapper-written sidecar registry", text)
        self.assertIn("outside the sidecar-writable tree", text)
        self.assertIn("It rejects\n`PROPOSED_CHANGES.patch` and `PROPOSED_FILES/` entries", text)
        self.assertIn("change the anchor\nto launch a new sidecar", text)
        self.assertIn("validates both the sidecar registry outside the writable artifact", text)
        self.assertIn("sandbox permission,\nfilesystem-isolation description, and validator command", text)
        self.assertIn("unknown or partial audit manifests are\nrejected", text)
        self.assertIn("cleanup owner marker is also stored beside that registry", text)
        self.assertIn("artifact-local `SIDECAR_REQUEST.txt` binding", text)
        self.assertIn("agent-contact send --repo <repo> --provider codex --session <sidecar-session>", text)
        self.assertIn("If `agent-contact` returns `mutated_unsubmitted`, treat delivery as failed", text)
        self.assertIn("`--dry-run` reports `would_clear_and_send`", text)
        self.assertIn("real send clears the composer\nbefore sending a fresh guarded payload", text)
        self.assertIn("Do not fall back to raw `agent-tmux send`", text)
        self.assertIn("Do not use\n`--dangerously-bypass-approvals-and-sandbox`", text)
        self.assertIn("Codex launch/resume routes through this wrapper require the requested tmux", text)
        self.assertIn("legacy supervise-style shape", text)
        self.assertIn("a true no-existing-session result is `rc=1`, empty stdout", text)
        self.assertIn("the wrapper source-inspects that\nexact tmux session name", text)
        self.assertIn("must not collapse into a delegated multiple-session refusal", text)
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

    def test_install_check_refuses_skill_load_backup_artifacts(self):
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
            skill_dir = codex_home / "skills" / "agent-tmux-control"
            (skill_dir / "SKILL.md.bak-20260517T122141").write_text("stale backup\n", encoding="utf-8")
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
            self.assertIn("backup/temp artifact under Codex skill load root", check.stderr)
            self.assertIn("SKILL.md.bak-20260517T122141", check.stderr)

    def test_install_relocates_skill_load_backup_artifacts_on_install(self):
        with tempfile.TemporaryDirectory() as home:
            codex_home = Path(home) / ".codex"
            bin_dir = Path(home) / ".local" / "bin"
            first_install = subprocess.run(
                ["bash", "scripts/install.sh", "--force"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(first_install.returncode, 0, first_install.stderr)
            skills_root = codex_home / "skills"
            skill_dir = skills_root / "agent-tmux-control"
            stale_skill_backup = skill_dir / "SKILL.md.bak-20260517T122141"
            stale_skill_backup.write_text("stale skill backup\n", encoding="utf-8")
            stale_dir_backup = skills_root / "agent-tmux-control.bak-20260517T122141"
            stale_dir_backup.mkdir()
            (stale_dir_backup / "SKILL.md").write_text("stale skill dir backup\n", encoding="utf-8")

            reinstall = subprocess.run(
                ["bash", "scripts/install.sh", "--force"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": home, "CODEX_HOME": str(codex_home), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(reinstall.returncode, 0, reinstall.stderr)
            backup_dir = codex_home / "agent-terminal-contact" / "backups" / "agent-tmux-control"
            self.assertFalse(stale_skill_backup.exists())
            self.assertFalse(stale_dir_backup.exists())
            self.assertEqual(
                (backup_dir / "SKILL.md.bak-20260517T122141").read_text(encoding="utf-8"),
                "stale skill backup\n",
            )
            self.assertEqual(
                (backup_dir / "agent-tmux-control.bak-20260517T122141" / "SKILL.md").read_text(encoding="utf-8"),
                "stale skill dir backup\n",
            )
            self.assertEqual(list(skill_dir.glob("*.bak*")), [])
            self.assertEqual(list(skills_root.glob("agent-tmux-control.bak-*")), [])

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

    def test_install_force_backs_up_divergent_existing_skill_outside_skill_load_root(self):
        with tempfile.TemporaryDirectory() as home:
            codex_home = Path(home) / ".codex"
            skill_dir = codex_home / "skills" / "agent-tmux-control"
            skill_dir.mkdir(parents=True)
            installed_skill = skill_dir / "SKILL.md"
            installed_skill.write_text("local hardened skill\n", encoding="utf-8")
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
            backup_dir = codex_home / "agent-terminal-contact" / "backups" / "agent-tmux-control"
            backups = list(backup_dir.glob("SKILL.md.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "local hardened skill\n")
            self.assertEqual(list(skill_dir.glob("*.bak*")), [])
            self.assertEqual(installed_skill.read_text(encoding="utf-8"), source_skill.read_text(encoding="utf-8"))

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
            backup_dir = codex_home / "agent-terminal-contact" / "backups" / "agent-tmux-control"
            backups = list(backup_dir.glob("agent-tmux-control.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertTrue(backups[0].is_symlink())
            self.assertEqual(backups[0].resolve(), external_dir)
            self.assertEqual(list(skills_root.glob("agent-tmux-control.bak-*")), [])
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
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            fake_bin = write_fake_tmux(tmp_path)
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
                    "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = capture.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[:6], ["new-session", "-d", "-s", "sess", "-c", repo])
            self.assertEqual(lines[6], "codex -s danger-full-access -a never --model gpt-5.5")
            self.assertIn("__log-writer", (tmp_path / "pipe.txt").read_text(encoding="utf-8"))

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
            runtime_dir = artifact_root / ".agent-tmux-sidecar-runtime" / session
            pipe_command = pipe_capture.read_text(encoding="utf-8").strip()
            self.assertIn("__log-writer", pipe_command)
            self.assertIn(f"{session}.log", pipe_command)
            command = lines[6]
            self.assertNotIn("--ro-bind / /", command)
            self.assertIn("bwrap --die-with-parent --unshare-all --share-net --clearenv --dir /usr", command)
            self.assertNotIn("--ro-bind /usr/bin /usr/bin", command)
            self.assertNotIn("--ro-bind /usr/lib /usr/lib", command)
            self.assertNotIn("--ro-bind /usr/lib64 /usr/lib64", command)
            self.assertIn("--dir /usr/bin", command)
            self.assertIn("--dir /usr/lib", command)
            self.assertIn("--ro-bind /usr/bin/bash /usr/bin/bash", command)
            self.assertIn("--ro-bind /usr/bin/rg /usr/bin/rg", command)
            self.assertIn(f"--ro-bind {runtime_dir}/empty-usr-local-bin /usr/local/bin", command)
            self.assertIn("--ro-bind", command)
            self.assertIn(str(repo.resolve()).replace(" ", "\\ "), command)
            self.assertIn("--dev /dev", command)
            self.assertNotIn("--dev-bind /dev /dev", command)
            self.assertNotIn(f"{fake_bin}/codex", command)
            self.assertIn("/home/tarkan/.nvm/versions/node/", command)
            self.assertIn("/bin/node", command)
            self.assertIn("/lib/node_modules/@openai/codex/bin/codex.js", command)
            self.assertIn(f"--ro-bind {runtime_dir}/empty-dev-shm /dev/shm", command)
            self.assertIn("--tmpfs /tmp --tmpfs /run", command)
            self.assertIn(f"--bind {artifact_dir} {artifact_dir}", command)
            self.assertIn(f"--bind {runtime_dir} {runtime_dir}", command)
            self.assertIn("--setenv CODEX_NO_TMUX 1", command)
            self.assertNotIn("--setenv CODEX_REAL_BIN", command)
            self.assertIn(f"--setenv CODEX_HOME {runtime_dir}/codex-home", command)
            self.assertIn("/bin/node", command)
            self.assertIn("/lib/node_modules/@openai/codex/bin/codex.js -c sandbox_mode=workspace-write -c sandbox_workspace_write.network_access=false -a never", command)
            self.assertIn("permissions.filesystem.deny_read=", command)
            self.assertIn(f"{runtime_dir}/codex-home", command)
            self.assertIn(f"-C {artifact_dir}", command)
            self.assertIn("Repository root (read-only input):", command)
            self.assertIn(str(repo.resolve()), command)
            self.assertIn("Patch artifact directory (only writable map output):", command)
            self.assertIn(str(artifact_dir), command)
            self.assertIn("Filesystem isolation: bwrap minimal root without a host / bind", command)
            self.assertIn("supervisor keeps a sidecar registry outside this writable artifact directory", command)
            self.assertIn("Write map output files only under the patch artifact directory", command)
            self.assertIn("Do not create .agent-tmux-runtime/", command)
            self.assertIn("Allowed map/project-memory target paths", command)
            self.assertIn(".project-memory/code-map/**", command)
            self.assertIn("project-memory namespace files must use .md, .json, or .jsonl", command)
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
            self.assertIn("filesystem_isolation=bwrap minimal root", manifest)
            self.assertIn("validator=agent-tmux codex-code-map-validate-artifacts", manifest)
            registry_file = artifact_root / ".agent-tmux-sidecar-registry" / f"{session}.txt"
            registry = registry_file.read_text(encoding="utf-8")
            self.assertEqual(registry, manifest)
            (artifact_dir / "MAP_REPORT.md").write_text("map report\n", encoding="utf-8")
            validation = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)
            self.assertIn("ok (no proposed map update)", validation.stdout)
            owner_file = artifact_root / ".agent-tmux-sidecar-registry" / f"{session}.owner"
            self.assertTrue(owner_file.is_file())
            self.assertFalse((runtime_dir / "owner-token").exists())
            self.assertFalse((artifact_dir / ".agent-tmux-runtime").exists())
            self.assertTrue((runtime_dir / "codex-home").is_dir())
            self.assertIn(f"code-map sidecar session: {session}", result.stderr)
            self.assertIn(f"code-map sidecar artifact-dir: {artifact_dir}", result.stderr)
            self.assertIn(f"code-map sidecar runtime-dir: {runtime_dir}", result.stderr)
            self.assertIn(f"code-map sidecar registry: {registry_file}", result.stderr)
            self.assertIn(f"code-map sidecar log: {tmp_path / 'home' / '.local' / 'state' / 'agent-tmux' / f'{session}.log'}", result.stderr)

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
            write_validator_sidecar_manifest(artifact_dir)
            (artifact_dir / "MAP_REPORT.md").write_text("map report\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/docs/CODEBASE_ARCHITECTURE_INDEX.md b/docs/CODEBASE_ARCHITECTURE_INDEX.md\n"
                "--- a/docs/CODEBASE_ARCHITECTURE_INDEX.md\n"
                "+++ b/docs/CODEBASE_ARCHITECTURE_INDEX.md\n"
                "@@ -1,2 +1,2 @@\n"
                "-old\n"
                "--- Removed-looking note remains patch content\n"
                "+new\n"
                "+++ Added heading remains patch content\n"
                "diff --git a/.project-memory/code-map-state.json b/.project-memory/code-map-state.json\n"
                "--- a/.project-memory/code-map-state.json\n"
                "+++ b/.project-memory/code-map-state.json\n"
                "@@ -1 +1 @@\n"
                "-{}\n"
                "+{\"enabled\":true}\n"
                "diff --git a/.project-memory/code-map/routes.md b/.project-memory/code-map/routes.md\n"
                "--- a/.project-memory/code-map/routes.md\n"
                "+++ b/.project-memory/code-map/routes.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/.project-memory/routing/owners.jsonl b/.project-memory/routing/owners.jsonl\n"
                "--- a/.project-memory/routing/owners.jsonl\n"
                "+++ b/.project-memory/routing/owners.jsonl\n"
                "@@ -1 +1 @@\n"
                "-{}\n"
                "+{\"owner\":\"map\"}\n"
                "diff --git a/docs/SUBSYSTEMS/contact.md b/docs/SUBSYSTEMS/contact.md\n"
                "--- a/docs/SUBSYSTEMS/contact.md\n"
                "+++ b/docs/SUBSYSTEMS/contact.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n",
                encoding="utf-8",
            )
            proposed = artifact_dir / "PROPOSED_FILES" / "docs" / "SUBSYSTEMS"
            proposed.mkdir(parents=True)
            (proposed / "contact.md").write_text("subsystem\n", encoding="utf-8")
            code_map_proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory" / "code-map"
            code_map_proposed.mkdir(parents=True)
            (code_map_proposed / "routes.md").write_text("routes\n", encoding="utf-8")
            routing_proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory" / "routing"
            routing_proposed.mkdir(parents=True)
            (routing_proposed / "owners.jsonl").write_text('{"owner":"map"}\n', encoding="utf-8")
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

    def test_agent_tmux_code_map_artifact_validator_accepts_report_only_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            (artifact_dir / "MAP_REPORT.md").write_text("map report\n", encoding="utf-8")
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
            self.assertIn("code-map artifact validation: ok (no proposed map update)", result.stdout)

    def test_agent_tmux_code_map_artifact_validator_rejects_empty_artifact_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
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
            self.assertIn("code-map artifact validation found no MAP_REPORT.md or proposed map update", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_project_memory_outside_policy_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory"
            proposed.mkdir(parents=True)
            (proposed / "random.md").write_text("map note\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/.project-memory/random.md b/.project-memory/random.md\n"
                "--- a/.project-memory/random.md\n"
                "+++ b/.project-memory/random.md\n"
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
            self.assertIn("invalid code-map artifact target (proposed file): .project-memory/random.md", result.stderr)
            self.assertIn("invalid code-map artifact target (diff old path): .project-memory/random.md", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_reserved_names_inside_allowed_namespaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory" / "code-map"
            proposed.mkdir(parents=True)
            (proposed / "aws-access-key-id.md").write_text("map note\n", encoding="utf-8")
            (proposed / "aws+access+key.md").write_text("map note\n", encoding="utf-8")
            (proposed / "aws:access:key.md").write_text("map note\n", encoding="utf-8")
            (proposed / "id_rsa.backup.md").write_text("map note\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/.project-memory/routing/ssh-key.md b/.project-memory/routing/ssh-key.md\n"
                "--- a/.project-memory/routing/ssh-key.md\n"
                "+++ b/.project-memory/routing/ssh-key.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/.project-memory/indexes/Auth.json b/.project-memory/indexes/Auth.json\n"
                "--- a/.project-memory/indexes/Auth.json\n"
                "+++ b/.project-memory/indexes/Auth.json\n"
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
            self.assertIn(
                "invalid code-map artifact runtime/auth path: PROPOSED_FILES/.project-memory/code-map/aws-access-key-id.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact runtime/auth path: PROPOSED_FILES/.project-memory/code-map/aws+access+key.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact runtime/auth path: PROPOSED_FILES/.project-memory/code-map/aws:access:key.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact runtime/auth path: PROPOSED_FILES/.project-memory/code-map/id_rsa.backup.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/routing/ssh-key.md",
                result.stderr,
            )
    def test_agent_tmux_code_map_artifact_validator_rejects_project_memory_bad_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory" / "code-map"
            proposed.mkdir(parents=True)
            (proposed / "state").write_text("map note\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/.project-memory/code-map/state.txt b/.project-memory/code-map/state.txt\n"
                "--- a/.project-memory/code-map/state.txt\n"
                "+++ b/.project-memory/code-map/state.txt\n"
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
            self.assertIn(
                "invalid code-map artifact target (proposed file): .project-memory/code-map/state",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/code-map/state.txt",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_header_only_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/docs/CODE_MAP.md b/docs/CODE_MAP.md\n",
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
            self.assertIn("code-map patch artifact contains no hunks", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_nested_subsystem_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/docs/SUBSYSTEMS/nested/bad.md b/docs/SUBSYSTEMS/nested/bad.md\n"
                "--- a/docs/SUBSYSTEMS/nested/bad.md\n"
                "+++ b/docs/SUBSYSTEMS/nested/bad.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n",
                encoding="utf-8",
            )
            proposed = artifact_dir / "PROPOSED_FILES" / "docs" / "SUBSYSTEMS" / "nested"
            proposed.mkdir(parents=True)
            (proposed / "bad.md").write_text("nested\n", encoding="utf-8")
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
                "invalid code-map artifact directory: PROPOSED_FILES/docs/SUBSYSTEMS/nested",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (proposed file): docs/SUBSYSTEMS/nested/bad.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): docs/SUBSYSTEMS/nested/bad.md",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_requires_sidecar_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifact"
            artifact_dir.mkdir()
            (artifact_dir / "MAP_REPORT.md").write_text("map report\n", encoding="utf-8")
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
            self.assertIn("missing code-map sidecar registry directory", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_missing_artifact_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            (artifact_dir / "SIDECAR_REQUEST.txt").unlink()
            (artifact_dir / "MAP_REPORT.md").write_text("map report\n", encoding="utf-8")
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
            self.assertIn("missing sidecar request manifest", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_tampered_artifact_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            other_repo = tmp_path / "other-repo"
            other_repo.mkdir()
            write_validator_sidecar_manifest(artifact_dir)
            (artifact_dir / "SIDECAR_REQUEST.txt").write_text(
                f"session={artifact_dir.name}\nrepo={other_repo.resolve()}\nallowed_output_dir={artifact_dir.resolve()}\n",
                encoding="utf-8",
            )
            (artifact_dir / "MAP_REPORT.md").write_text("map report\n", encoding="utf-8")
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
            self.assertIn("sidecar request manifest does not byte-match code-map sidecar registry", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_secret_in_sidecar_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            manifest = artifact_dir / "SIDECAR_REQUEST.txt"
            manifest.write_text(
                manifest.read_text(encoding="utf-8") + "aws_secret_access_key: local-secret\n",
                encoding="utf-8",
            )
            registry = artifact_dir.parent / ".agent-tmux-sidecar-registry" / f"{artifact_dir.name}.txt"
            registry.write_text(manifest.read_text(encoding="utf-8"), encoding="utf-8")
            (artifact_dir / "MAP_REPORT.md").write_text("map report\n", encoding="utf-8")
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
            self.assertIn("invalid code-map sidecar registry line: aws_secret_access_key: local-secret", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_blank_sidecar_request_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            manifest = artifact_dir / "SIDECAR_REQUEST.txt"
            content = manifest.read_text(encoding="utf-8")
            tampered = content.replace("repo=", "\nrepo=", 1)
            manifest.write_text(tampered, encoding="utf-8")
            registry = artifact_dir.parent / ".agent-tmux-sidecar-registry" / f"{artifact_dir.name}.txt"
            registry.write_text(tampered, encoding="utf-8")
            (artifact_dir / "MAP_REPORT.md").write_text("map report\n", encoding="utf-8")
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
            self.assertIn("invalid code-map sidecar registry blank line", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_permission_manifest_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            manifest = artifact_dir / "SIDECAR_REQUEST.txt"
            manifest.write_text(
                manifest.read_text(encoding="utf-8") + "permission=-s danger-full-access -a never\n",
                encoding="utf-8",
            )
            (artifact_dir / "MAP_REPORT.md").write_text("map report\n", encoding="utf-8")
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
                "sidecar request manifest does not byte-match code-map sidecar registry",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_manifest_repo_containing_artifact_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            artifact_dir = repo / "artifact"
            write_validator_sidecar_manifest(artifact_dir, repo=repo)
            (artifact_dir / "MAP_REPORT.md").write_text("map report\n", encoding="utf-8")
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
            self.assertIn("code-map artifact directory must not be inside the repository root", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_traditional_unified_diff_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
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
            write_validator_sidecar_manifest(artifact_dir)
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
            write_validator_sidecar_manifest(artifact_dir)
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
            write_validator_sidecar_manifest(artifact_dir)
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
                "+worse\n"
                "--- src/bad file.py\n"
                "+++ src/bad file.py\n"
                "@@ -1 +1 @@\n"
                "-bad\n"
                "+worse\n"
                "--- bad file.py\n"
                "+++ bad file.py\n"
                "@@ -1 +1 @@\n"
                "-bad\n"
                "+worse\n"
                "--- Makefile\n"
                "+++ Makefile\n"
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
            self.assertIn("unsupported code-map patch --- header: --- src/bad file.py", result.stderr)
            self.assertIn("unsupported code-map patch +++ header: +++ src/bad file.py", result.stderr)
            self.assertIn("unsupported code-map patch --- header: --- bad file.py", result.stderr)
            self.assertIn("unsupported code-map patch +++ header: +++ bad file.py", result.stderr)
            self.assertIn("unsupported code-map patch --- header: --- Makefile", result.stderr)
            self.assertIn("unsupported code-map patch +++ header: +++ Makefile", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_binary_patch_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
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
            write_validator_sidecar_manifest(artifact_dir)
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
            self.assertIn("invalid code-map artifact target (proposed file): $'docs/CODE_MAP.md\\tshadow'", result.stderr)
            self.assertIn("invalid code-map artifact target (diff old path): $'docs/CODE_MAP.md\\tshadow'", result.stderr)
            self.assertIn("invalid code-map artifact target (--- path): $'docs/CODE_MAP.md\\tshadow'", result.stderr)
            self.assertNotIn("\tshadow", result.stderr)

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
            write_validator_sidecar_manifest(artifact_dir)
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
            write_validator_sidecar_manifest(artifact_dir)
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
                "invalid code-map artifact target (proposed file): .project-memory/auth.json",
                result.stderr,
            )
            self.assertIn(
                "code-map artifact appears to contain Codex auth/session structure: PROPOSED_FILES/.project-memory/auth.json",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_runtime_looking_project_memory_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory" / "codex-home" / "sessions" / "2026"
            proposed.mkdir(parents=True)
            (proposed / "trace.jsonl").write_text("map note\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/.project-memory/codex-home/sessions/2026/trace.jsonl b/.project-memory/codex-home/sessions/2026/trace.jsonl\n"
                "--- a/.project-memory/codex-home/sessions/2026/trace.jsonl\n"
                "+++ b/.project-memory/codex-home/sessions/2026/trace.jsonl\n"
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
            self.assertIn(
                "invalid code-map artifact runtime/auth path: PROPOSED_FILES/.project-memory/codex-home",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/codex-home/sessions/2026/trace.jsonl",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_sessions_under_allowed_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory" / "code-map" / "sessions" / "2026"
            proposed.mkdir(parents=True)
            (proposed / "trace.jsonl").write_text("map note\n", encoding="utf-8")
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
                "invalid code-map artifact runtime/auth path: PROPOSED_FILES/.project-memory/code-map/sessions",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_case_variant_runtime_looking_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory" / "Sessions"
            proposed.mkdir(parents=True)
            (proposed / "Trace.jsonl").write_text("map note\n", encoding="utf-8")
            auth_proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory" / "Auth.json"
            auth_proposed.write_text("map note\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/.project-memory/Sessions/Trace.jsonl b/.project-memory/Sessions/Trace.jsonl\n"
                "--- a/.project-memory/Sessions/Trace.jsonl\n"
                "+++ b/.project-memory/Sessions/Trace.jsonl\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/.project-memory/Auth.json b/.project-memory/Auth.json\n"
                "--- a/.project-memory/Auth.json\n"
                "+++ b/.project-memory/Auth.json\n"
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
            self.assertIn(
                "invalid code-map artifact runtime/auth path: PROPOSED_FILES/.project-memory/Sessions",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/Sessions/Trace.jsonl",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/Auth.json",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_auth_session_like_filenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory"
            proposed.mkdir(parents=True)
            (proposed / "Session.jsonl").write_text("map note\n", encoding="utf-8")
            (proposed / "Auth-Token.json").write_text("map note\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/.project-memory/Session.jsonl b/.project-memory/Session.jsonl\n"
                "--- a/.project-memory/Session.jsonl\n"
                "+++ b/.project-memory/Session.jsonl\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/.project-memory/Auth-Token.json b/.project-memory/Auth-Token.json\n"
                "--- a/.project-memory/Auth-Token.json\n"
                "+++ b/.project-memory/Auth-Token.json\n"
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
            self.assertIn(
                "invalid code-map artifact target (proposed file): .project-memory/Session.jsonl",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/Auth-Token.json",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_plural_auth_session_filenames(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory"
            proposed.mkdir(parents=True)
            (proposed / "credentials.json").write_text("map note\n", encoding="utf-8")
            (proposed / "secrets.json").write_text("map note\n", encoding="utf-8")
            (proposed / "sessions.jsonl").write_text("map note\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/.project-memory/credentials.json b/.project-memory/credentials.json\n"
                "--- a/.project-memory/credentials.json\n"
                "+++ b/.project-memory/credentials.json\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/.project-memory/secrets.json b/.project-memory/secrets.json\n"
                "--- a/.project-memory/secrets.json\n"
                "+++ b/.project-memory/secrets.json\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/.project-memory/sessions.jsonl b/.project-memory/sessions.jsonl\n"
                "--- a/.project-memory/sessions.jsonl\n"
                "+++ b/.project-memory/sessions.jsonl\n"
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
            self.assertIn(
                "invalid code-map artifact runtime/auth path: PROPOSED_FILES/.project-memory/credentials.json",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/secrets.json",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/sessions.jsonl",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_prefixed_and_suffixed_auth_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory"
            proposed.mkdir(parents=True)
            (proposed / "client_secret.md").write_text("map note\n", encoding="utf-8")
            (proposed / "api-key.md").write_text("map note\n", encoding="utf-8")
            (proposed / "private-key.md").write_text("map note\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/.project-memory/client_secret.md b/.project-memory/client_secret.md\n"
                "--- a/.project-memory/client_secret.md\n"
                "+++ b/.project-memory/client_secret.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/.project-memory/api-key.md b/.project-memory/api-key.md\n"
                "--- a/.project-memory/api-key.md\n"
                "+++ b/.project-memory/api-key.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/.project-memory/private-key.md b/.project-memory/private-key.md\n"
                "--- a/.project-memory/private-key.md\n"
                "+++ b/.project-memory/private-key.md\n"
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
            self.assertIn(
                "invalid code-map artifact runtime/auth path: PROPOSED_FILES/.project-memory/client_secret.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/api-key.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/private-key.md",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_access_key_path_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory"
            proposed.mkdir(parents=True)
            (proposed / "aws-access-key-id.md").write_text("map note\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/.project-memory/aws-access-key.md b/.project-memory/aws-access-key.md\n"
                "--- a/.project-memory/aws-access-key.md\n"
                "+++ b/.project-memory/aws-access-key.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/.project-memory/aws_access_key.md b/.project-memory/aws_access_key.md\n"
                "--- a/.project-memory/aws_access_key.md\n"
                "+++ b/.project-memory/aws_access_key.md\n"
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
            self.assertIn(
                "invalid code-map artifact runtime/auth path: PROPOSED_FILES/.project-memory/aws-access-key-id.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/aws-access-key.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/aws_access_key.md",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_ssh_private_key_path_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory"
            proposed.mkdir(parents=True)
            (proposed / "ssh-key.md").write_text("map note\n", encoding="utf-8")
            (proposed / "key.md").write_text("map note\n", encoding="utf-8")
            (proposed / "id_ecdsa.md").write_text("map note\n", encoding="utf-8")
            (proposed / "id-dsa.md").write_text("map note\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/.project-memory/ssh_key.md b/.project-memory/ssh_key.md\n"
                "--- a/.project-memory/ssh_key.md\n"
                "+++ b/.project-memory/ssh_key.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/.project-memory/private key.md b/.project-memory/private key.md\n"
                "--- a/.project-memory/private key.md\n"
                "+++ b/.project-memory/private key.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/.project-memory/id_ecdsa.md b/.project-memory/id_ecdsa.md\n"
                "--- a/.project-memory/id_ecdsa.md\n"
                "+++ b/.project-memory/id_ecdsa.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
                "diff --git a/.project-memory/id-dsa.md b/.project-memory/id-dsa.md\n"
                "--- a/.project-memory/id-dsa.md\n"
                "+++ b/.project-memory/id-dsa.md\n"
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
            self.assertIn(
                "invalid code-map artifact runtime/auth path: PROPOSED_FILES/.project-memory/ssh-key.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact runtime/auth path: PROPOSED_FILES/.project-memory/key.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact runtime/auth path: PROPOSED_FILES/.project-memory/id_ecdsa.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact runtime/auth path: PROPOSED_FILES/.project-memory/id-dsa.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/ssh_key.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/private key.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/id_ecdsa.md",
                result.stderr,
            )
            self.assertIn(
                "invalid code-map artifact target (diff old path): .project-memory/id-dsa.md",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_newline_path_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory"
            proposed.mkdir(parents=True)
            (proposed / "bad\nname.md").write_text("map note\n", encoding="utf-8")
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
            self.assertIn("invalid code-map artifact target (proposed file): $'.project-memory/bad\\nname.md'", result.stderr)
            self.assertNotIn("bad\nname", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_escape_path_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory"
            proposed.mkdir(parents=True)
            (proposed / "bad\x1bname.md").write_text("map note\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/.project-memory/bad\x1bname.md b/.project-memory/bad\x1bname.md\n"
                "--- a/.project-memory/bad\x1bname.md\n"
                "+++ b/.project-memory/bad\x1bname.md\n"
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
            self.assertIn("invalid code-map artifact target (proposed file): $'.project-memory/bad\\Ename.md'", result.stderr)
            self.assertIn("invalid code-map artifact target (diff old path): $'.project-memory/bad\\Ename.md'", result.stderr)
            self.assertNotIn("\x1b", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_c1_control_path_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory" / "code-map"
            proposed.mkdir(parents=True)
            (proposed / "bad\u0085name.md").write_text("map note\n", encoding="utf-8")
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
                "invalid code-map artifact target (proposed file): $'.project-memory/code-map/bad\\302\\205name.md'",
                result.stderr,
            )
            self.assertNotIn("\u0085", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_escapes_control_path_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / "docs" / "SUBSYSTEMS"
            proposed.mkdir(parents=True)
            (proposed / "bad\x1b]52;c;AAAA\x07.md").write_text("map note\n", encoding="utf-8")
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
            self.assertIn("invalid code-map artifact target (proposed file):", result.stderr)
            self.assertNotIn("\x1b", result.stderr)
            self.assertNotIn("\x07", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_additional_auth_structure_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory" / "code-map"
            proposed.mkdir(parents=True)
            (proposed / "state.json").write_text(
                '{"safe":"map","client_secret":"abc","credential":"opaque","private_key":"key"}\n',
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
                "code-map artifact appears to contain Codex auth/session structure: PROPOSED_FILES/.project-memory/code-map/state.json",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_prefixed_auth_structure_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory" / "code-map"
            proposed.mkdir(parents=True)
            (proposed / "state.md").write_text(
                "OPENAI_API_KEY=sk-local\n"
                "GITHUB_TOKEN=ghp-local\n"
                "github_token: ghp-local\n"
                "aws_secret_access_key = aws-local\n",
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
                "code-map artifact appears to contain Codex auth/session structure: PROPOSED_FILES/.project-memory/code-map/state.md",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_does_not_trust_path_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            (artifact_dir / "MAP_REPORT.md").write_text("OPENAI_API_KEY: sk-local\n", encoding="utf-8")
            fake_bin = tmp_path / "fake-bin"
            fake_bin.mkdir()
            fake_python = fake_bin / "python3"
            fake_python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            fake_python.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": f"{fake_bin}:/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn(
                "code-map artifact appears to contain Codex auth/session structure: MAP_REPORT.md",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_colon_auth_structure_keys(self):
        cases = [
            ("OPENAI_API_KEY", "MAP_REPORT.md"),
            ("GITHUB_TOKEN", "PROPOSED_FILES/.project-memory/code-map/state.md"),
            ("github_token", "PROPOSED_FILES/.project-memory/code-map/state.md"),
            ("aws_secret_access_key", "PROPOSED_FILES/.project-memory/code-map/state.md"),
            ("aws-secret-access-key", "PROPOSED_FILES/.project-memory/code-map/state.md"),
            ("aws+secret+access+key", "PROPOSED_FILES/.project-memory/code-map/state.md"),
            ("aws:secret:access:key", "PROPOSED_FILES/.project-memory/code-map/state.md"),
            ('"aws:access:key"', "PROPOSED_FILES/.project-memory/code-map/state.md"),
            ("aws-access-key-id", "PROPOSED_FILES/.project-memory/code-map/state.md"),
            ("service.secret.token", "PROPOSED_FILES/.project-memory/code-map/state.md"),
            ("'aws-secret-access-key'", "MAP_REPORT.md"),
            ("'github_token'", "PROPOSED_FILES/.project-memory/code-map/state.md"),
            ("ssh_key", "PROPOSED_FILES/.project-memory/code-map/state.md"),
            ("ssh-key", "PROPOSED_FILES/.project-memory/code-map/state.md"),
            ("'ssh+key'", "PROPOSED_FILES/.project-memory/code-map/state.md"),
            ("id_rsa", "MAP_REPORT.md"),
            ("id-ed25519", "PROPOSED_FILES/.project-memory/code-map/state.md"),
            ("private key", "MAP_REPORT.md"),
        ]
        for key, rel_path in cases:
            with self.subTest(key=key, rel_path=rel_path):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    artifact_dir = tmp_path / "artifact"
                    write_validator_sidecar_manifest(artifact_dir)
                    target = artifact_dir / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(f"{key}: local-secret\n", encoding="utf-8")
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
                        f"code-map artifact appears to contain Codex auth/session structure: {rel_path}",
                        result.stderr,
                    )

    def test_agent_tmux_code_map_artifact_validator_rejects_escaped_auth_structure_keys(self):
        cases = {
            "MAP_REPORT.md": r'{"aws_\u0073ecret_\u0061ccess_\u006bey":"local-secret"}' + "\n",
            "PROPOSED_FILES/.project-memory/code-map/state.md": r'"\u0073sh_\u006bey": local-secret' + "\n",
            "PROPOSED_FILES/.project-memory/routing/state.md": r"private\u0020key: local-secret" + "\n",
            "PROPOSED_CHANGES.patch": (
                "diff --git a/docs/CODE_MAP.md b/docs/CODE_MAP.md\n"
                "--- a/docs/CODE_MAP.md\n"
                "+++ b/docs/CODE_MAP.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                r'+"\u0069d_rsa": "local-secret"'
                "\n"
            ),
        }
        for rel_path, content in cases.items():
            with self.subTest(rel_path=rel_path):
                with tempfile.TemporaryDirectory() as tmp:
                    artifact_dir = Path(tmp) / "artifact"
                    write_validator_sidecar_manifest(artifact_dir)
                    target = artifact_dir / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
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
                        f"code-map artifact appears to contain Codex auth/session structure: {rel_path}",
                        result.stderr,
                    )

    def test_agent_tmux_code_map_artifact_validator_rejects_split_line_auth_structure_keys(self):
        cases = {
            "MAP_REPORT.md": "AWS_SECRET_ACCESS_KEY\n: local-secret\n",
            "PROPOSED_FILES/.project-memory/code-map/state.md": '"AWS_SECRET_ACCESS_KEY"\n= local-secret\n',
            "PROPOSED_FILES/.project-memory/routing/state.md": "'id_ecdsa'\n: local-secret\n",
            "PROPOSED_CHANGES.patch": (
                "diff --git a/docs/CODE_MAP.md b/docs/CODE_MAP.md\n"
                "--- a/docs/CODE_MAP.md\n"
                "+++ b/docs/CODE_MAP.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+AWS_SECRET_ACCESS_KEY\n"
                "+= local-secret\n"
            ),
        }
        for rel_path, content in cases.items():
            with self.subTest(rel_path=rel_path):
                with tempfile.TemporaryDirectory() as tmp:
                    artifact_dir = Path(tmp) / "artifact"
                    write_validator_sidecar_manifest(artifact_dir)
                    target = artifact_dir / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
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
                        f"code-map artifact appears to contain Codex auth/session structure: {rel_path}",
                        result.stderr,
                    )

    def test_agent_tmux_code_map_artifact_validator_rejects_private_key_blocks(self):
        cases = [
            "-----BEGIN OPENSSH PRIVATE KEY-----\nopaque\n-----END OPENSSH PRIVATE KEY-----\n",
            "-----BEGIN RSA PRIVATE KEY-----\nopaque\n-----END RSA PRIVATE KEY-----\n",
        ]
        for content in cases:
            with self.subTest(content=content.splitlines()[0]):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    artifact_dir = tmp_path / "artifact"
                    write_validator_sidecar_manifest(artifact_dir)
                    proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory" / "code-map"
                    proposed.mkdir(parents=True)
                    (proposed / "state.md").write_text(content, encoding="utf-8")
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
                        "code-map artifact appears to contain Codex auth/session structure: PROPOSED_FILES/.project-memory/code-map/state.md",
                        result.stderr,
                    )

    def test_agent_tmux_code_map_artifact_validator_rejects_secret_keys_inside_patch_hunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/docs/CODE_MAP.md b/docs/CODE_MAP.md\n"
                "--- a/docs/CODE_MAP.md\n"
                "+++ b/docs/CODE_MAP.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+aws-secret-access-key: local-secret\n"
                "+aws+secret+access+key: local-secret\n"
                "+id_rsa: local-secret\n",
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
                "code-map artifact appears to contain Codex auth/session structure: PROPOSED_CHANGES.patch",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_rejects_no_space_colon_secret_keys(self):
        cases = {
            "MAP_REPORT.md": "OPENAI_API_KEY:sk-local\n",
            "PROPOSED_FILES/.project-memory/code-map/state.md": "aws_secret_access_key:local-secret\n",
            "PROPOSED_CHANGES.patch": (
                "diff --git a/docs/CODE_MAP.md b/docs/CODE_MAP.md\n"
                "--- a/docs/CODE_MAP.md\n"
                "+++ b/docs/CODE_MAP.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+id_rsa:local-secret\n"
            ),
        }
        for rel_path, content in cases.items():
            with self.subTest(rel_path=rel_path):
                with tempfile.TemporaryDirectory() as tmp:
                    artifact_dir = Path(tmp) / "artifact"
                    write_validator_sidecar_manifest(artifact_dir)
                    target = artifact_dir / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
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
                        f"code-map artifact appears to contain Codex auth/session structure: {rel_path}",
                        result.stderr,
                    )

    def test_agent_tmux_code_map_artifact_validator_accepts_safe_structured_map_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            (artifact_dir / "MAP_REPORT.md").write_text(
                "Path: docs/CODE_MAP.md\n"
                "Owner: mapping\n"
                "Purpose: route source areas\n"
                "Auth: explain auth surface without secrets\n"
                "Tokenization: source map term, not a credential\n",
                encoding="utf-8",
            )
            proposed = artifact_dir / "PROPOSED_FILES" / ".project-memory" / "code-map"
            proposed.mkdir(parents=True)
            (proposed / "state.md").write_text(
                "Path: src/agent_terminal_contact/session.py\nPurpose: sidecar routing\n",
                encoding="utf-8",
            )
            (proposed / "codex.md").write_text("Codex routing map\n", encoding="utf-8")
            (proposed / "session-routing.md").write_text("session routing map\n", encoding="utf-8")
            (proposed / "tokenization.md").write_text("tokenization map\n", encoding="utf-8")
            (artifact_dir / "PROPOSED_CHANGES.patch").write_text(
                "diff --git a/.project-memory/code-map/state.md b/.project-memory/code-map/state.md\n"
                "--- a/.project-memory/code-map/state.md\n"
                "+++ b/.project-memory/code-map/state.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+Path: src/agent_terminal_contact/session.py\n"
                "diff --git a/.project-memory/code-map/session-routing.md b/.project-memory/code-map/session-routing.md\n"
                "--- a/.project-memory/code-map/session-routing.md\n"
                "+++ b/.project-memory/code-map/session-routing.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+Auth: explain auth surface without secrets\n"
                "diff --git a/.project-memory/code-map/tokenization.md b/.project-memory/code-map/tokenization.md\n"
                "--- a/.project-memory/code-map/tokenization.md\n"
                "+++ b/.project-memory/code-map/tokenization.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+Tokenization: source map term, not a credential\n",
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
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("code-map artifact validation: ok", result.stdout)

    def test_agent_tmux_code_map_artifact_validator_rejects_codex_session_jsonl_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            (artifact_dir / "MAP_REPORT.md").write_text(
                '{"timestamp":"2026-05-12T00:00:00Z","type":"session_meta","payload":{"id":"12345678-1234-1234-1234-123456789abc","cwd":"/tmp/repo","originator":"codex_cli"}}\n'
                '{"type":"response_item","message":"copied session transcript"}\n',
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
            self.assertIn("code-map artifact appears to contain Codex auth/session structure: MAP_REPORT.md", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_generic_session_jsonl_records(self):
        cases = {
            "MAP_REPORT.md": (
                '{"timestamp":"2026-05-13T00:00:00Z","type":"user_message","message":"copied transcript"},\n'
            ),
            "PROPOSED_FILES/.project-memory/code-map/session.md": (
                '{"type":"assistant_message","content":[{"text":"copied transcript"}]}\n'
            ),
            "PROPOSED_FILES/.project-memory/code-map/transcript.jsonl": (
                '{"timestamp":"2026-05-13T00:00:00Z","role":"user","content":"copied transcript"}\n'
            ),
            "PROPOSED_FILES/.project-memory/code-map/transcript.json": (
                "[\n"
                "  {\n"
                '    "timestamp": "2026-05-13T00:00:00Z",\n'
                '    "role": "user",\n'
                '    "content": "copied transcript"\n'
                "  }\n"
                "]\n"
            ),
            "PROPOSED_CHANGES.patch": (
                "diff --git a/docs/CODE_MAP.md b/docs/CODE_MAP.md\n"
                "--- a/docs/CODE_MAP.md\n"
                "+++ b/docs/CODE_MAP.md\n"
                "@@ -0,0 +1,10 @@\n"
                '+{"timestamp":"2026-05-13T00:00:00Z","type":"event","payload":{"message":"copied transcript"}}\n'
                '+{"type":"event","data":{"timestamp":"2026-05-13T00:00:00Z","message":"copied transcript","role":"assistant","content":"text"}}\n'
                '+{"timestamp":"2026-05-13T00:00:00Z","role":"user","content":"copied transcript"},\n'
                "+[\n"
                "+  {\n"
                '+    "timestamp": "2026-05-13T00:00:00Z",\n'
                '+    "role": "user",\n'
                '+    "content": "copied transcript"\n'
                "+  }\n"
                "+]\n"
            ),
        }
        for rel_path, content in cases.items():
            with self.subTest(rel_path=rel_path):
                with tempfile.TemporaryDirectory() as tmp:
                    artifact_dir = Path(tmp) / "artifact"
                    write_validator_sidecar_manifest(artifact_dir)
                    target = artifact_dir / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
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
                        f"code-map artifact appears to contain Codex auth/session structure: {rel_path}",
                        result.stderr,
                    )

    def test_agent_tmux_code_map_artifact_validator_rejects_invalid_utf8_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            (artifact_dir / "MAP_REPORT.md").write_bytes(b"map report\n\xff\xfe\n")
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
            self.assertIn("code-map artifact appears to contain Codex auth/session structure: MAP_REPORT.md", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_terminal_control_bytes(self):
        cases = [
            ("MAP_REPORT.md", "map report\u0085control\n"),
            ("PROPOSED_FILES/docs/SUBSYSTEMS/cr.md", "safe text\rspoofed prefix\n"),
            ("PROPOSED_FILES/docs/SUBSYSTEMS/tab.md", "sidecar\tnote\n"),
            ("PROPOSED_FILES/docs/SUBSYSTEMS/contact.md", "sidecar note \x1b]52;c;AAAA\x07\n"),
            (
                "PROPOSED_CHANGES.patch",
                "diff --git a/docs/CODE_MAP.md b/docs/CODE_MAP.md\n"
                "--- a/docs/CODE_MAP.md\n"
                "+++ b/docs/CODE_MAP.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\x1b[200~pasted\x1b[201~\n"
            ),
            (
                "PROPOSED_CHANGES.patch",
                "diff --git a/docs/CODE_MAP.md b/docs/CODE_MAP.md\n"
                "diff --git a/docs/CODE_MAP.md b/docs/CODE_MAP.md\x1b]52;c;AAAA\x07\n"
                "--- a/docs/CODE_MAP.md\n"
                "+++ b/docs/CODE_MAP.md\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n",
            ),
        ]
        for rel_path, content in cases:
            with self.subTest(rel_path=rel_path):
                with tempfile.TemporaryDirectory() as tmp:
                    artifact_dir = Path(tmp) / "artifact"
                    write_validator_sidecar_manifest(artifact_dir)
                    target = artifact_dir / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
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
                        f"code-map artifact contains terminal control bytes: {rel_path}",
                        result.stderr,
                    )
                    self.assertNotIn("\x1b", result.stderr)
                    self.assertNotIn("\x07", result.stderr)
                    self.assertNotIn("\u0085", result.stderr)
                    self.assertNotIn("\r", result.stderr)
                    self.assertNotIn("\t", result.stderr)

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
            write_validator_sidecar_manifest(artifact_dir)
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
            write_validator_sidecar_manifest(artifact_dir)
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
            write_validator_sidecar_manifest(artifact_dir)
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

    def test_agent_tmux_code_map_artifact_validator_rejects_runtime_session_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            runtime_session = artifact_dir / ".agent-tmux-runtime" / "codex-home" / "sessions" / "2026" / "05" / "13"
            runtime_session.mkdir(parents=True)
            (runtime_session / "rollout-12345678-1234-1234-1234-123456789abc.jsonl").write_text(
                '{"timestamp":"2026-05-13T00:00:00Z","type":"session_meta","session_id":"12345678-1234-1234-1234-123456789abc"}\n',
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
            self.assertIn("invalid code-map artifact runtime/auth path: .agent-tmux-runtime", result.stderr)
            self.assertIn(
                "invalid code-map artifact runtime/auth path: .agent-tmux-runtime/codex-home/sessions/2026/05/13/rollout-12345678-1234-1234-1234-123456789abc.jsonl",
                result.stderr,
            )

    def test_agent_tmux_code_map_artifact_validator_ignores_path_find_spoof(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            proposed = artifact_dir / "PROPOSED_FILES" / "docs" / "SUBSYSTEMS"
            proposed.mkdir(parents=True)
            proposed_file = proposed / "sidecar.md"
            proposed_file.write_text("sidecar\n", encoding="utf-8")
            unsafe = artifact_dir / "PROPOSED_FILES" / "src"
            unsafe.mkdir(parents=True)
            (unsafe / "bad.py").write_text("bad\n", encoding="utf-8")
            fake_bin = tmp_path / "fake-bin"
            fake_bin.mkdir()
            write_fake_find(fake_bin)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", str(artifact_dir)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_FAKE_FIND_ENTRY": str(proposed_file),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("forced find traversal failure", result.stderr)
            self.assertIn("invalid code-map artifact directory: PROPOSED_FILES/src", result.stderr)
            self.assertIn("invalid code-map artifact target (proposed file): src/bad.py", result.stderr)
            self.assertNotIn("code-map artifact validation: ok", result.stdout)

    def test_agent_tmux_code_map_artifact_validator_rejects_root_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
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

    def test_agent_tmux_code_map_artifact_validator_rejects_root_symlink_with_trailing_slash(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            artifact_link = tmp_path / "artifact-link"
            artifact_link.symlink_to(artifact_dir, target_is_directory=True)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", f"{artifact_link}/"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("code-map artifact directory must not be a symlink", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_root_symlink_dot_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
            artifact_link = tmp_path / "artifact-link"
            artifact_link.symlink_to(artifact_dir, target_is_directory=True)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-code-map-validate-artifacts", f"{artifact_link}/."],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("code-map artifact directory must not contain symlink path components", result.stderr)

    def test_agent_tmux_code_map_artifact_validator_rejects_symlink_patch_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_dir = tmp_path / "artifact"
            write_validator_sidecar_manifest(artifact_dir)
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

    def test_agent_tmux_code_map_sidecar_rejects_unsafe_anchor_before_artifact_creation(self):
        cases = {
            "empty": "",
            "control": "ticket\nanchor",
        }
        for label, anchor in cases.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    repo = tmp_path / "Example Repo"
                    repo.mkdir()
                    artifact_root = tmp_path / "artifacts"
                    result = subprocess.run(
                        ["bash", "bin/agent-tmux", "codex-code-map-sidecar", str(repo), anchor, "Focus"],
                        cwd=ROOT,
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env={
                            "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(artifact_root),
                            "PATH": "/usr/bin:/bin",
                        },
                    )
                    self.assertEqual(result.returncode, 2)
                    if label == "empty":
                        self.assertIn("code-map sidecar anchor must not be empty", result.stderr)
                    else:
                        self.assertIn(
                            "code-map sidecar anchor must not contain terminal control bytes",
                            result.stderr,
                        )
                    self.assertFalse(artifact_root.exists())

    def test_agent_tmux_code_map_sidecar_ignores_path_chmod_failure_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            artifact_root = tmp_path / "artifacts"
            delegate = write_code_map_delegate(tmp_path, has_rc=1)
            fake_bin = write_fake_tmux(tmp_path)
            write_fake_chmod(
                fake_bin,
                "printf 'forced chmod failure: %s\\n' \"$*\" >&2\n"
                "exit 1\n",
            )
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
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(capture.exists())
            session = capture.read_text(encoding="utf-8").splitlines()[3]
            artifact_dir = artifact_root / session
            registry_dir = artifact_root / ".agent-tmux-sidecar-registry"
            registry_file = registry_dir / f"{session}.txt"
            self.assertEqual(oct(artifact_dir.stat().st_mode & 0o777), "0o700")
            self.assertEqual(oct(registry_dir.stat().st_mode & 0o777), "0o700")
            self.assertEqual(oct(registry_file.stat().st_mode & 0o777), "0o600")

    def test_agent_tmux_code_map_sidecar_ignores_path_chmod_and_stat_spoof(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            artifact_root = tmp_path / "artifacts"
            delegate = write_code_map_delegate(tmp_path, has_rc=1)
            fake_bin = write_fake_tmux(tmp_path)
            write_fake_chmod(fake_bin, "exit 0\n")
            write_fake_stat(fake_bin, "printf '700\\n'\n")
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
            self.assertEqual(result.returncode, 0, result.stderr)
            session = capture.read_text(encoding="utf-8").splitlines()[3]
            artifact_dir = artifact_root / session
            registry_dir = artifact_root / ".agent-tmux-sidecar-registry"
            registry_file = registry_dir / f"{session}.txt"
            owner_file = registry_dir / f"{session}.owner"
            self.assertEqual(oct(artifact_dir.stat().st_mode & 0o777), "0o700")
            self.assertEqual(oct(registry_dir.stat().st_mode & 0o777), "0o700")
            self.assertEqual(oct(registry_file.stat().st_mode & 0o777), "0o600")
            self.assertEqual(oct(owner_file.stat().st_mode & 0o777), "0o600")

    def test_agent_tmux_code_map_sidecar_uses_trusted_chmod_for_registry_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            artifact_root = tmp_path / "artifacts"
            delegate = write_code_map_delegate(tmp_path, has_rc=1)
            fake_bin = write_fake_tmux(tmp_path)
            write_fake_chmod(
                fake_bin,
                "case \"${2:-}\" in\n"
                "  */.agent-tmux-sidecar-registry/*.txt)\n"
                "  printf 'forced registry file chmod failure: %s\\n' \"$*\" >&2\n"
                "  exit 1\n"
                "  ;;\n"
                "esac\n"
                "exec /usr/bin/chmod \"$@\"\n",
            )
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
            self.assertEqual(result.returncode, 0, result.stderr)
            session = capture.read_text(encoding="utf-8").splitlines()[3]
            registry_file = artifact_root / ".agent-tmux-sidecar-registry" / f"{session}.txt"
            self.assertEqual(oct(registry_file.stat().st_mode & 0o777), "0o600")

    def test_agent_tmux_code_map_sidecar_reports_failed_session_termination_after_pipe_log_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            artifact_root = tmp_path / "artifacts"
            delegate = write_code_map_delegate(tmp_path, has_rc=1, pipe_rc=1)
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
                    "AGENT_TMUX_FAIL_KILL": "1",
                    "AGENT_TMUX_FAIL_PIPE": "1",
                    "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                    "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(artifact_root),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("failed to terminate code-map sidecar session after pipe-log failure", result.stderr)
            self.assertIn("forced kill failure", result.stderr)
            self.assertIn("failed to enable log pipe for code-map sidecar session", result.stderr)
            if artifact_root.exists():
                self.assertFalse(any(artifact_root.iterdir()))

    def test_agent_tmux_code_map_sidecar_cleans_after_post_prepare_mktemp_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            artifact_root = tmp_path / "artifacts"
            delegate = write_code_map_delegate(tmp_path, has_rc=1)
            fake_bin = write_fake_tmux(tmp_path)
            write_fake_mktemp(fake_bin)
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
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("forced mktemp failure", result.stderr)
            self.assertFalse(capture.exists())
            if artifact_root.exists():
                self.assertFalse(any(artifact_root.iterdir()))

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

    def test_agent_tmux_code_map_sidecar_cleans_registry_when_runtime_parent_is_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "Example Repo"
            repo.mkdir()
            capture = tmp_path / "args.txt"
            artifact_root = tmp_path / "artifacts"
            artifact_root.mkdir()
            runtime_target = tmp_path / "runtime-target"
            runtime_target.mkdir()
            runtime_link = artifact_root / ".agent-tmux-sidecar-runtime"
            runtime_link.symlink_to(runtime_target, target_is_directory=True)
            delegate = write_code_map_delegate(tmp_path, has_rc=1)
            fake_bin = write_fake_tmux(tmp_path)
            session = code_map_session_name(repo, "cp-123")
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
            self.assertIn("code-map sidecar runtime parent must not be a symlink", result.stderr)
            self.assertFalse(capture.exists())
            self.assertFalse((artifact_root / session).exists())
            self.assertFalse((artifact_root / ".agent-tmux-sidecar-registry").exists())
            self.assertTrue(runtime_link.is_symlink())

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
                    "AGENT_TMUX_FAIL_PIPE": "1",
                    "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(artifact_root),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("failed to enable log pipe for code-map sidecar session", result.stderr)
            self.assertFalse(any(artifact_root.iterdir()))

    def test_agent_tmux_code_map_sidecar_uses_source_owned_log_path(self):
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
                    "AGENT_TMUX_CODE_MAP_ARTIFACT_ROOT": str(artifact_root),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            session = capture.read_text(encoding="utf-8").splitlines()[3]
            expected_log = tmp_path / "home" / ".local" / "state" / "agent-tmux" / f"{session}.log"
            self.assertIn(f"code-map sidecar log: {expected_log}", result.stderr)

    def test_agent_tmux_code_map_permissions_are_accepted_by_codex_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / "codex-home"
            codex_home.mkdir()
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
                env={"HOME": tmp, "CODEX_HOME": str(codex_home), "PATH": TEST_PATH},
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
            runtime_dir = artifact_root / ".agent-tmux-sidecar-runtime" / session
            command = lines[6]
            self.assertIn("/lib/node_modules/@openai/codex/bin/codex.js -c sandbox_mode=workspace-write -c sandbox_workspace_write.network_access=false -a never", command)
            self.assertIn("permissions.filesystem.deny_read=", command)
            self.assertIn(f"{runtime_dir}/codex-home", command)
            self.assertIn(f"-C {artifact_dir} fork {session_id}", command)
            self.assertFalse((artifact_dir / ".agent-tmux-runtime").exists())
            copied_sessions = list((runtime_dir / "codex-home" / "sessions").rglob("*.jsonl"))
            self.assertEqual(len(copied_sessions), 1)
            self.assertEqual(copied_sessions[0].read_text(encoding="utf-8"), "{\"session\":\"fixture\"}\n")
            self.assertIn(
                session_id,
                (runtime_dir / "codex-home" / "session_index.jsonl").read_text(encoding="utf-8"),
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
            codex_home = write_codex_latest_fixture(tmp_path, repo)
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            fake_bin = write_fake_tmux(tmp_path)
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
                    "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                    "CODEX_HOME": str(codex_home),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = capture.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[:6], ["new-session", "-d", "-s", "sess", "-c", repo])
            self.assertEqual(lines[6], "codex -s danger-full-access -a never resume Thread\\ Name Please\\ do\\ work")

    def test_agent_tmux_codex_latest_uses_source_index_instead_of_delegate_stale_thread(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            repo_path = Path(repo)
            codex_home = tmp_path / "codex-home"
            sessions = codex_home / "sessions" / "2026" / "05" / "19"
            sessions.mkdir(parents=True)
            stale_id = "11111111-1111-4111-8111-111111111111"
            latest_id = "22222222-2222-4222-8222-222222222222"
            (codex_home / "session_index.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "id": stale_id,
                                "thread_name": f"{repo_path.name}_old",
                                "updated_at": "2026-05-10T20:00:00Z",
                            }
                        ),
                        json.dumps(
                            {
                                "id": latest_id,
                                "thread_name": repo_path.name,
                                "updated_at": "2026-05-19T20:05:56Z",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (sessions / f"rollout-2026-05-10T20-00-00-{stale_id}.jsonl").write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": stale_id,
                            "cwd": str(repo_path.resolve()),
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (sessions / f"rollout-2026-05-19T20-05-56-{latest_id}.jsonl").write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": latest_id,
                            "cwd": str(tmp_path / "other-repo"),
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = codex-latest ]; then\n"
                "  printf 'stale-thread\\t11111111-1111-4111-8111-111111111111\\t2026-05-10T20:00:00Z\\t/tmp/stale.jsonl\\n'\n"
                "  exit 0\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-latest", str(repo_path)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "CODEX_HOME": str(codex_home),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            fields = result.stdout.rstrip("\n").split("\t")
            self.assertEqual(fields[:3], [repo_path.name, latest_id, "2026-05-19T20:05:56Z"])
            self.assertIn(latest_id, fields[3])

    def test_agent_tmux_codex_latest_fails_closed_on_equal_timestamp_ambiguity(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            repo_path = Path(repo)
            codex_home = tmp_path / "codex-home"
            sessions = codex_home / "sessions" / "2026" / "05" / "19"
            sessions.mkdir(parents=True)
            left_id = "33333333-3333-4333-8333-333333333333"
            right_id = "44444444-4444-4444-8444-444444444444"
            (codex_home / "session_index.jsonl").write_text(
                "\n".join(
                    json.dumps(
                        {
                            "id": session_id,
                            "thread_name": repo_path.name,
                            "updated_at": "2026-05-19T20:05:56Z",
                        }
                    )
                    for session_id in (left_id, right_id)
                )
                + "\n",
                encoding="utf-8",
            )
            for session_id in (left_id, right_id):
                (sessions / f"rollout-2026-05-19T20-05-56-{session_id}.jsonl").write_text(
                    json.dumps(
                        {
                            "type": "session_meta",
                            "payload": {
                                "id": session_id,
                                "cwd": str(repo_path.resolve()),
                            },
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-latest", str(repo_path)],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "CODEX_HOME": str(codex_home),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertIn("multiple latest Codex sessions found", result.stderr)

    def test_agent_tmux_resume_latest_full_uses_source_owned_latest_thread(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            repo_path = Path(repo)
            codex_home = tmp_path / "codex-home"
            sessions = codex_home / "sessions" / "2026" / "05" / "19"
            sessions.mkdir(parents=True)
            latest_id = "55555555-5555-4555-8555-555555555555"
            (codex_home / "session_index.jsonl").write_text(
                json.dumps(
                    {
                        "id": latest_id,
                        "thread_name": "Source Owned Thread",
                        "updated_at": "2026-05-19T20:05:56Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (sessions / f"rollout-2026-05-19T20-05-56-{latest_id}.jsonl").write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": latest_id,
                            "cwd": str(repo_path.resolve()),
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
                "fi\n"
                "if [ \"$1\" = codex-latest ]; then\n"
                "  exit 2\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            capture = tmp_path / "args.txt"
            fake_bin = write_fake_tmux(tmp_path)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-resume-latest-full", "sess", str(repo_path), "Please", "work"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                    "CODEX_HOME": str(codex_home),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = capture.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[:6], ["new-session", "-d", "-s", "sess", "-c", str(repo_path)])
            self.assertEqual(lines[6], "codex -s danger-full-access -a never resume Source\\ Owned\\ Thread Please\\ work")

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
            codex_home = write_codex_latest_fixture(tmp_path, repo)
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            fake_bin = write_fake_tmux(tmp_path)
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
                    "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                    "CODEX_HOME": str(codex_home),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = capture.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[:6], ["new-session", "-d", "-s", "sess", "-c", repo])
            self.assertEqual(lines[6], "codex -s danger-full-access -a never resume Thread\\ Name Please\\ do\\ work")

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
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            fake_bin = write_fake_tmux(tmp_path)
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
                    "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                    "HOME": str(tmp_path / "home"),
                    "PATH": f"{fake_bin}:{TEST_PATH}",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = capture.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[:6], ["new-session", "-d", "-s", "sess", "-c", repo])
            self.assertEqual(lines[6], "codex -s danger-full-access -a never resume Thread\\ Name Please\\ do\\ work")

    def test_agent_tmux_non_full_codex_commands_use_requested_session(self):
        cases = [
            (
                ["codex", "sess", "{repo}", "--model", "gpt-5.5"],
                "codex --model gpt-5.5",
            ),
            (
                ["codex-resume", "sess", "{repo}", "Thread Name", "Please", "do", "work"],
                "codex resume Thread\\ Name Please do work",
            ),
            (
                ["codex-resume-latest", "sess", "{repo}", "Please", "do", "work"],
                "codex resume Thread\\ Name Please\\ do\\ work",
            ),
        ]
        for argv_template, expected_command in cases:
            with self.subTest(command=argv_template[0]):
                with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
                    argv = [repo if arg == "{repo}" else arg for arg in argv_template]
                    tmp_path = Path(tmp)
                    capture = tmp_path / "args.txt"
                    codex_home = write_codex_latest_fixture(tmp_path, repo)
                    delegate = tmp_path / "delegate-agent-tmux"
                    delegate.write_text(
                        "#!/usr/bin/env bash\n"
                        "if [ \"$1\" = has ]; then\n"
                        "  exit 1\n"
                        "fi\n"
                        "exit 2\n",
                        encoding="utf-8",
                    )
                    delegate.chmod(0o755)
                    fake_bin = write_fake_tmux(tmp_path)
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
                            "AGENT_TMUX_PIPE_CAPTURE": str(tmp_path / "pipe.txt"),
                            "CODEX_HOME": str(codex_home),
                            "HOME": str(tmp_path / "home"),
                            "PATH": f"{fake_bin}:{TEST_PATH}",
                        },
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    lines = capture.read_text(encoding="utf-8").splitlines()
                    self.assertEqual(lines[:6], ["new-session", "-d", "-s", "sess", "-c", repo])
                    self.assertEqual(lines[6], expected_command)
                    pipe_command = (tmp_path / "pipe.txt").read_text(encoding="utf-8")
                    self.assertIn("__log-writer", pipe_command)
                    self.assertIn("sess.log", pipe_command)

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

    def test_agent_tmux_regular_non_log_command_delegates_unchanged(self):
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
                ["bash", "bin/agent-tmux", "capture", "sess", "20"],
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
            self.assertEqual(capture.read_text(encoding="utf-8").splitlines(), ["capture", "sess", "20"])

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

    def test_agent_tmux_codex_existing_exact_missing_session_does_not_delegate_to_ambiguity(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            capture = tmp_path / "delegate-called.txt"
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            tmux = bin_dir / "tmux"
            tmux.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has-session ]; then\n"
                "  printf 'missing exact session\\n' >&2\n"
                "  exit 1\n"
                "fi\n"
                "printf 'unexpected tmux command: %s\\n' \"$*\" >&2\n"
                "exit 2\n",
                encoding="utf-8",
            )
            tmux.chmod(0o755)
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "printf 'called\\n' >\"${AGENT_TMUX_CAPTURE}\"\n"
                "printf 'agent-tmux: multiple detached Codex tmux sessions\\n' >&2\n"
                "exit 3\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-existing", repo, "owner-missing-63"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "PATH": f"{bin_dir}:/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual("", result.stdout)
            self.assertIn("no Codex tmux session found for workdir:", result.stderr)
            self.assertIn("session: owner-missing-63", result.stderr)
            self.assertFalse(capture.exists())

    def test_agent_tmux_codex_existing_exact_existing_session_is_source_inspected(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            resolved_repo = Path(repo).resolve()
            capture = tmp_path / "delegate-called.txt"
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            tmux = bin_dir / "tmux"
            tmux.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has-session ]; then\n"
                "  [ \"$3\" = '=owner-present-63' ] && exit 0\n"
                "  exit 1\n"
                "fi\n"
                "if [ \"$1\" = display-message ] && [ \"$4\" = '=owner-present-63:' ] && [ \"$5\" = '#{pane_current_path}' ]; then\n"
                f"  printf '%s\\n' '{resolved_repo}'\n"
                "  exit 0\n"
                "fi\n"
                "if [ \"$1\" = display-message ] && [ \"$4\" = '=owner-present-63:' ] && [ \"$5\" = '#{pane_current_command}' ]; then\n"
                "  printf 'node\\n'\n"
                "  exit 0\n"
                "fi\n"
                "printf 'unexpected tmux command: %s\\n' \"$*\" >&2\n"
                "exit 2\n",
                encoding="utf-8",
            )
            tmux.chmod(0o755)
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "printf 'called\\n' >\"${AGENT_TMUX_CAPTURE}\"\n"
                "printf 'agent-tmux: multiple detached Codex tmux sessions\\n' >&2\n"
                "exit 3\n",
                encoding="utf-8",
            )
            delegate.chmod(0o755)
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "codex-existing", repo, "owner-present-63"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={
                    "AGENT_TMUX_DELEGATE": str(delegate),
                    "AGENT_TMUX_CAPTURE": str(capture),
                    "PATH": f"{bin_dir}:/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual("owner-present-63\n", result.stdout)
            self.assertEqual("", result.stderr)
            self.assertFalse(capture.exists())

    def test_agent_tmux_resume_latest_full_rejects_malformed_source_index(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            codex_home = tmp_path / "codex-home"
            codex_home.mkdir()
            (codex_home / "sessions").mkdir()
            (codex_home / "session_index.jsonl").write_text("not-json\n", encoding="utf-8")
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
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
                    "CODEX_HOME": str(codex_home),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("malformed Codex session index record", result.stderr)

    def test_agent_tmux_resume_latest_full_rejects_missing_source_index(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            codex_home = tmp_path / "codex-home"
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
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
                    "CODEX_HOME": str(codex_home),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Codex session index not found", result.stderr)

    def test_agent_tmux_resume_latest_full_rejects_multiple_session_files(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo:
            tmp_path = Path(tmp)
            repo_path = Path(repo)
            codex_home = tmp_path / "codex-home"
            sessions = codex_home / "sessions" / "2026" / "05" / "12"
            sessions.mkdir(parents=True)
            session_id = "66666666-6666-4666-8666-666666666666"
            (codex_home / "session_index.jsonl").write_text(
                json.dumps(
                    {
                        "id": session_id,
                        "thread_name": repo_path.name,
                        "updated_at": "2026-05-12T00:00:00Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            for prefix in ("left", "right"):
                (sessions / f"{prefix}-{session_id}.jsonl").write_text(
                    json.dumps(
                        {
                            "type": "session_meta",
                            "payload": {
                                "id": session_id,
                                "cwd": str(repo_path.resolve()),
                            },
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
            delegate = tmp_path / "delegate-agent-tmux"
            delegate.write_text(
                "#!/usr/bin/env bash\n"
                "if [ \"$1\" = has ]; then\n"
                "  exit 1\n"
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
                    "CODEX_HOME": str(codex_home),
                    "PATH": "/usr/bin:/bin",
                },
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Codex session id matched multiple files", result.stderr)

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

    def test_agent_tmux_log_writer_rotates_at_configured_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "state" / "agent-tmux" / "sess.log"
            payload = b"a" * 40 + b"b" * 40 + b"c" * 40
            result = subprocess.run(
                ["bash", "bin/agent-tmux", "__log-writer", str(log_path), "50", "2"],
                cwd=ROOT,
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
            self.assertTrue(log_path.exists())
            rotated = log_path.with_name("sess.log.1")
            self.assertTrue(rotated.exists())
            self.assertLessEqual(log_path.stat().st_size, 50)
            self.assertLessEqual(rotated.stat().st_size, 80)
            self.assertEqual(oct(log_path.stat().st_mode & 0o777), "0o600")

    def test_agent_tmux_logs_status_and_prune_reclaim_closed_log_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            log_dir = tmp_path / ".local" / "state" / "agent-tmux"
            log_dir.mkdir(parents=True)
            old_log = log_dir / "closed.log"
            old_log.write_bytes(b"x" * 120)
            old_time = 1_700_000_000
            os.utime(old_log, (old_time, old_time))
            oversized_log = log_dir / "recent.log"
            oversized_log.write_bytes(b"y" * 120)
            status = subprocess.run(
                ["bash", "bin/agent-tmux", "logs", "status"],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("files=2", status.stdout)
            self.assertIn("total_bytes=240", status.stdout)
            prune = subprocess.run(
                [
                    "bash",
                    "bin/agent-tmux",
                    "logs",
                    "prune",
                    "--older-than",
                    "1d",
                    "--max-size",
                    "50",
                ],
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(prune.returncode, 0, prune.stderr)
            self.assertIn("deleted=1", prune.stdout)
            self.assertIn("capped=1", prune.stdout)
            self.assertFalse(old_log.exists())
            self.assertEqual(oversized_log.stat().st_size, 50)


if __name__ == "__main__":
    unittest.main()
