from contextlib import contextmanager
import os
import shlex
import tempfile
import unittest
from pathlib import Path

from agent_terminal_contact.runner import CommandResult
from agent_terminal_contact.session import DiscoveryError, PANE_FORMAT, revalidate_target, select_target


@contextmanager
def trusted_provider_root(root):
    old_value = os.environ.get("AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS")
    old_launcher_value = os.environ.get("AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS")
    root_path = Path(root)
    candidate_roots = (
        root_path,
        root_path / "node_modules" / "@openai" / "codex",
        root_path / "node_modules" / "@anthropic-ai" / "claude-code",
    )
    trusted_roots = [str(candidate) for candidate in candidate_roots if candidate.exists()]
    os.environ["AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS"] = os.pathsep.join(trusted_roots or [str(root_path)])
    os.environ["AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS"] = "/usr/bin"
    try:
        yield
    finally:
        if old_value is None:
            os.environ.pop("AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS", None)
        else:
            os.environ["AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS"] = old_value
        if old_launcher_value is None:
            os.environ.pop("AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS", None)
        else:
            os.environ["AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS"] = old_launcher_value


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def run(self, args, input_text=None):
        key = tuple(args)
        self.calls.append((key, input_text))
        response = self.responses.get(key)
        if response is None:
            return CommandResult(key, 127, "", f"unexpected command: {key}")
        return response


def pane_line(session, pane_id, repo, command="node", pid=1234, dead=0, tty="/dev/pts/7"):
    return f"{session}\t{pane_id}\t{tty}\t{Path(repo).resolve()}\t{command}\t{pid}\t1\t{dead}\t10\t0\n"


def write_provider_package(root, provider="codex"):
    root_path = Path(root)
    if provider == "codex":
        package_root = root_path / "node_modules" / "@openai" / "codex"
        script = package_root / "bin" / "codex.js"
        package_json = '{"name":"@openai/codex","bin":{"codex":"bin/codex.js"}}\n'
    else:
        package_root = root_path / "node_modules" / "@anthropic-ai" / "claude-code"
        script = package_root / "bin" / "claude.exe"
        package_json = '{"name":"@anthropic-ai/claude-code","bin":{"claude":"bin/claude.exe"}}\n'
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    (package_root / "package.json").write_text(package_json, encoding="utf-8")
    return script


def write_sidecar_request(artifact_dir, *, session, repo):
    artifact_path = Path(artifact_dir)
    content = (
        f"session={session}\n"
        f"repo={Path(repo).resolve()}\n"
        f"allowed_output_dir={artifact_path.resolve()}\n"
    )
    artifact_path.joinpath("SIDECAR_REQUEST.txt").write_text(content, encoding="utf-8")
    registry_dir = artifact_path.parent / ".agent-tmux-sidecar-registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / f"{session}.txt").write_text(content, encoding="utf-8")


def ps_response(pid=1234, args="node /home/tarkan/.nvm/lib/node_modules/@openai/codex/bin/codex.js --no-alt-screen"):
    return {("ps", "-p", str(pid), "-o", "args="): CommandResult((), 0, args + "\n", "")}


def tty_response(tty="/dev/pts/7", args="node /home/tarkan/.nvm/lib/node_modules/@openai/codex/bin/codex.js --no-alt-screen", pid=1234):
    return {
        ("ps", "-t", tty, "-o", "pid=,ppid=,pgid=,stat=,args="): CommandResult(
            (), 0, f"{pid} 1 {pid} Sl+ {args}\n", ""
        )
    }


def proc_response(pid=1234, args="node /home/tarkan/.nvm/lib/node_modules/@openai/codex/bin/codex.js --no-alt-screen", exe="/usr/bin/node"):
    argv = tuple(shlex.split(args))
    return {
        ("cat", f"/proc/{pid}/cmdline"): CommandResult((), 0, "\0".join(argv) + "\0", ""),
        ("readlink", "-f", f"/proc/{pid}/exe"): CommandResult((), 0, f"{exe}\n", ""),
        ("cat", f"/proc/{pid}/environ"): CommandResult((), 0, "PATH=/usr/bin\0", ""),
    }


def proc_argv_response(pid=1234, argv=("node", "/home/tarkan/.nvm/lib/node_modules/@openai/codex/bin/codex.js"), exe="/usr/bin/node"):
    return {
        ("cat", f"/proc/{pid}/cmdline"): CommandResult((), 0, "\0".join(argv) + "\0", ""),
        ("readlink", "-f", f"/proc/{pid}/exe"): CommandResult((), 0, f"{exe}\n", ""),
        ("cat", f"/proc/{pid}/environ"): CommandResult((), 0, "PATH=/usr/bin\0", ""),
    }


def package_tty_response(root, tty="/dev/pts/7", pid=1234, provider="codex"):
    script = write_provider_package(root, provider=provider)
    args = f"node {script} --no-alt-screen"
    return {
        **tty_response(tty=tty, args=args, pid=pid),
        **proc_response(pid=pid, args=args),
    }


class SessionDiscoveryTests(unittest.TestCase):
    def test_selects_single_matching_pane(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo), ""
                    ),
                    **package_tty_response(repo),
                }
            )
            with trusted_provider_root(repo):
                selected = select_target(repo=repo, provider="codex", runner=runner)
            self.assertEqual(selected.pane.session_name, "codex-demo")
            self.assertEqual(selected.pane.pane_id, "%1")
            self.assertEqual(selected.provider, "codex")
            self.assertEqual(selected.pane.provider_evidence, "pane process args match codex")

    def test_selects_provider_package_path_with_spaces_from_proc_argv(self):
        with tempfile.TemporaryDirectory(prefix="agent contact ") as root:
            repo = Path(root) / "repo"
            repo.mkdir()
            script = write_provider_package(root)
            ps_args = f"node {script} --no-alt-screen"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo), ""
                    ),
                    **tty_response(args=ps_args),
                    **proc_argv_response(argv=("node", str(script), "--no-alt-screen")),
                }
            )
            with trusted_provider_root(root):
                selected = select_target(repo=str(repo), provider="codex", runner=runner)
            self.assertEqual(selected.pane.provider_pid, 1234)
            self.assertIn(str(script), selected.pane.process_args)

    def test_accepts_provider_package_path_with_mixed_case_parent(self):
        with tempfile.TemporaryDirectory(prefix="CodexCase") as root:
            repo = Path(root) / "repo"
            repo.mkdir()
            script = write_provider_package(root)
            args = f"node {script} --no-alt-screen"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo), ""
                    ),
                    **tty_response(args=args),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(root):
                selected = select_target(repo=str(repo), provider="codex", runner=runner)
            self.assertEqual(selected.pane.provider_pid, 1234)

    def test_refuses_exec_a_spoofed_provider_args_when_exe_is_not_launcher(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            args = f"node {script} --no-alt-screen"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(pid=1234, args=args, exe="/usr/bin/cat"),
                }
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_bare_node_argv_when_exe_is_untrusted_launcher_path(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            args = f"node {script} --no-alt-screen"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(pid=1234, args=args, exe="/tmp/node"),
                }
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_fake_node_under_broad_trusted_launcher_parent(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            fake_node = Path(repo) / "fake-bin" / "node"
            fake_node.parent.mkdir()
            fake_node.write_text("#!/bin/sh\n", encoding="utf-8")
            args = f"{fake_node} {script} --no-alt-screen"
            old_provider = os.environ.get("AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS")
            old_launcher = os.environ.get("AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS")
            os.environ["AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS"] = str(
                Path(repo).resolve() / "node_modules" / "@openai" / "codex"
            )
            os.environ["AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS"] = str(Path(repo).resolve())
            try:
                runner = FakeRunner(
                    {
                        ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                            (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                        ),
                        **tty_response(args=args, pid=1234),
                        **proc_response(pid=1234, args=args, exe=str(fake_node)),
                    }
                )
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=repo, provider="codex", runner=runner)
            finally:
                if old_provider is None:
                    os.environ.pop("AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS", None)
                else:
                    os.environ["AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS"] = old_provider
                if old_launcher is None:
                    os.environ.pop("AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS", None)
                else:
                    os.environ["AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS"] = old_launcher

    def test_refuses_node_argv0_spoofed_as_trusted_provider_entrypoint(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            not_agent = Path(repo) / "not-agent.js"
            not_agent.write_text("console.log('not agent')\n", encoding="utf-8")
            args = f"{script} {not_agent}"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(pid=1234, args=args, exe="/usr/bin/node"),
                }
            )
            runner.responses[("cat", "/proc/1234/environ")] = CommandResult(
                (), 0, "PATH=/usr/bin\0NODE_OPTIONS=--require /tmp/evil.js\0", ""
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_provider_match_when_authoritative_cmdline_is_unavailable(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            args = f"node {script} --no-alt-screen"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    ("cat", "/proc/1234/cmdline"): CommandResult((), 1, "", "permission denied"),
                }
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_provider_name_without_agent_process_args(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-build", "%1", repo, command="bash"), ""
                    ),
                    **tty_response(args="bash", pid=1234),
                    **ps_response(args="bash"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_multiple_matching_panes(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            args = f"node {script} --no-alt-screen"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (),
                        0,
                        pane_line("codex-a", "%1", repo, pid=111, tty="/dev/pts/7")
                        + pane_line("codex-b", "%2", repo, pid=222, tty="/dev/pts/8"),
                        "",
                    ),
                    **tty_response(tty="/dev/pts/7", args=args, pid=111),
                    **tty_response(tty="/dev/pts/8", args=args, pid=222),
                    **proc_response(pid=111, args=args),
                    **proc_response(pid=222, args=args),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "multiple"):
                with trusted_provider_root(repo):
                    select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_no_matching_provider(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("plain", "%1", repo, command="bash"), ""
                    ),
                    **tty_response(args="bash", pid=1234),
                    **ps_response(args="bash"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_unlabeled_node_session_even_with_explicit_session(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-s", "-t", "agent-terminal-contact", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("agent-terminal-contact", "%1", repo), ""
                    ),
                    **tty_response(args="node /tmp/codexical-dev-server.js", pid=1234),
                    **ps_response(args="node /tmp/codexical-dev-server.js"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(
                    repo=repo,
                    provider="codex",
                    runner=runner,
                    explicit_session="agent-terminal-contact",
                )

    def test_refuses_node_script_with_provider_only_in_later_argument(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args="node /tmp/not-an-agent.js --log /tmp/@openai/codex-cache", pid=1234),
                    **ps_response(args="node /tmp/not-an-agent.js --log /tmp/@openai/codex-cache"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_node_require_provider_script_when_program_is_not_agent(self):
        with tempfile.TemporaryDirectory() as repo:
            trusted = Path(repo) / "trusted"
            script = write_provider_package(trusted)
            not_agent = Path(repo) / "not-agent.js"
            not_agent.write_text("console.log('not agent')\n", encoding="utf-8")
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args=f"node --require {script} {not_agent}", pid=1234),
                    **ps_response(args=f"node --require {script} {not_agent}"),
                }
            )
            with trusted_provider_root(trusted):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_node_preload_before_trusted_provider_entrypoint(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            preload = Path(repo) / "preload.js"
            preload.write_text("console.log('spoof')\n", encoding="utf-8")
            args = f"node --require {preload} {script} --no-alt-screen"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_node_options_preload_before_trusted_provider_entrypoint(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            preload = Path(repo) / "preload.js"
            preload.write_text("console.log('spoof')\n", encoding="utf-8")
            args = f"node {script} --no-alt-screen"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            runner.responses[("cat", "/proc/1234/environ")] = CommandResult(
                (), 0, f"PATH=/usr/bin\0NODE_OPTIONS=--require {preload}\0", ""
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_unrecognized_node_options_before_trusted_provider_entrypoint(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            args = f"node {script} --no-alt-screen"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            runner.responses[("cat", "/proc/1234/environ")] = CommandResult(
                (), 0, "PATH=/usr/bin\0NODE_OPTIONS=--preserve-symlinks\0", ""
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_node_import_provider_script_when_program_is_not_agent(self):
        with tempfile.TemporaryDirectory() as repo:
            trusted = Path(repo) / "trusted"
            script = write_provider_package(trusted)
            not_agent = Path(repo) / "not-agent.js"
            not_agent.write_text("console.log('not agent')\n", encoding="utf-8")
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args=f"node --import {script} {not_agent}", pid=1234),
                    **ps_response(args=f"node --import {script} {not_agent}"),
                }
            )
            with trusted_provider_root(trusted):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_node_loader_before_trusted_provider_entrypoint(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            loader = Path(repo) / "loader.mjs"
            loader.write_text("export function load() {}\n", encoding="utf-8")
            args = f"node --loader={loader} {script} --no-alt-screen"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_unknown_node_option_before_trusted_provider_entrypoint(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            args = f"node --env-file=/tmp/agent-contact.env {script} --no-alt-screen"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_node_script_with_provider_substring_path(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args="node /tmp/@openai/codex-fake.js", pid=1234),
                    **ps_response(args="node /tmp/@openai/codex-fake.js"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_fake_package_shaped_codex_path_without_package_metadata(self):
        with tempfile.TemporaryDirectory() as repo:
            fake_script = Path(repo) / "fake" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            fake_script.parent.mkdir(parents=True)
            fake_script.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args=f"node {fake_script} --fake", pid=1234),
                    **ps_response(args=f"node {fake_script} --fake"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_fake_package_shaped_codex_path_with_untrusted_package_metadata(self):
        with tempfile.TemporaryDirectory() as repo:
            fake_script = write_provider_package(repo)
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args=f"node {fake_script} --fake", pid=1234),
                    **ps_response(args=f"node {fake_script} --fake"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_fake_package_under_broad_trusted_parent_root(self):
        with tempfile.TemporaryDirectory() as repo:
            fake_script = write_provider_package(repo)
            old_value = os.environ.get("AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS")
            old_launcher = os.environ.get("AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS")
            os.environ["AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS"] = str(Path(repo).resolve())
            os.environ["AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS"] = "/usr/bin"
            try:
                runner = FakeRunner(
                    {
                        ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                            (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                        ),
                        **tty_response(args=f"node {fake_script} --fake", pid=1234),
                        **proc_response(args=f"node {fake_script} --fake"),
                    }
                )
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=repo, provider="codex", runner=runner)
            finally:
                if old_value is None:
                    os.environ.pop("AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS", None)
                else:
                    os.environ["AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS"] = old_value
                if old_launcher is None:
                    os.environ.pop("AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS", None)
                else:
                    os.environ["AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS"] = old_launcher

    def test_refuses_package_under_default_home_roots_without_explicit_trust(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as repo:
            old_home = os.environ.get("HOME")
            old_trusted = os.environ.get("AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS")
            old_launcher = os.environ.get("AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS")
            os.environ["HOME"] = home
            os.environ.pop("AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS", None)
            os.environ["AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS"] = "/usr/bin"
            try:
                fake_script = write_provider_package(Path(home) / ".nvm" / "fake-install")
                args = f"node {fake_script} --fake-provider"
                runner = FakeRunner(
                    {
                        ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                            (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                        ),
                        **tty_response(args=args, pid=1234),
                        **proc_response(args=args),
                    }
                )
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=repo, provider="codex", runner=runner)
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home
                if old_trusted is None:
                    os.environ.pop("AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS", None)
                else:
                    os.environ["AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS"] = old_trusted
                if old_launcher is None:
                    os.environ.pop("AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS", None)
                else:
                    os.environ["AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS"] = old_launcher

    def test_refuses_fake_package_shaped_claude_path_without_package_metadata(self):
        with tempfile.TemporaryDirectory() as repo:
            fake_script = Path(repo) / "fake" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
            fake_script.parent.mkdir(parents=True)
            fake_script.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("claude-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args=f"node {fake_script} --fake", pid=1234),
                    **ps_response(args=f"node {fake_script} --fake"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed claude pane"):
                select_target(repo=repo, provider="claude", runner=runner)

    def test_accepts_scoped_claude_package_identity_with_explicit_trust(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root) / "repo"
            repo.mkdir()
            script = write_provider_package(root, provider="claude")
            args = f"node {script} --no-alt-screen"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("claude-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(root):
                selected = select_target(repo=str(repo), provider="claude", runner=runner)
            self.assertEqual(selected.pane.provider_pid, 1234)
            self.assertEqual(selected.pane.provider_evidence, "pane process args match claude")

    def test_refuses_package_launcher_when_provider_package_is_not_command(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args="npx --package @openai/codex cowsay", pid=1234),
                    **ps_response(args="npx --package @openai/codex cowsay"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_package_launcher_without_provider_package_spec(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args="npx codex --fake", pid=1234),
                    **ps_response(args="npx codex --fake"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_package_launcher_even_when_provider_package_is_command(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    **tty_response(args="npx --package @openai/codex codex --no-alt-screen", pid=1234),
                    **ps_response(args="npx --package @openai/codex codex --no-alt-screen"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_package_launcher_from_untrusted_executable_path(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="npx"), ""
                    ),
                    **tty_response(args="/tmp/npx --package @openai/codex codex --fake", pid=1234),
                    **ps_response(args="/tmp/npx --package @openai/codex codex --fake"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_background_provider_process_on_shell_pane(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="bash", pid=100), ""
                    ),
                    ("ps", "-t", "/dev/pts/7", "-o", "pid=,ppid=,pgid=,stat=,args="): CommandResult(
                        (),
                        0,
                        "100 1 100 Ss+ bash\n"
                        "200 100 200 Sl node /opt/node_modules/@openai/codex/bin/codex.js --no-alt-screen\n",
                        "",
                    ),
                    **ps_response(100, args="bash"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_stopped_foreground_provider_process(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    ("ps", "-t", "/dev/pts/7", "-o", "pid=,ppid=,pgid=,stat=,args="): CommandResult(
                        (),
                        0,
                        "1234 1 1234 T+ node /opt/node_modules/@openai/codex/bin/codex.js --no-alt-screen\n",
                        "",
                    ),
                    **ps_response(args="node /opt/node_modules/@openai/codex/bin/codex.js --no-alt-screen"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_when_tty_process_inspection_fails(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node"), ""
                    ),
                    ("ps", "-t", "/dev/pts/7", "-o", "pid=,ppid=,pgid=,stat=,args="): CommandResult(
                        (), 1, "", "ps failed"
                    ),
                    **ps_response(args="node /opt/node_modules/@openai/codex/bin/codex.js --no-alt-screen"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "failed to inspect target pane TTY processes"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_foreground_non_agent_that_mentions_provider(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="vim", pid=300), ""
                    ),
                    ("ps", "-t", "/dev/pts/7", "-o", "pid=,ppid=,pgid=,stat=,args="): CommandResult(
                        (), 0, "300 1 300 Sl+ vim codex\n", ""
                    ),
                    **ps_response(300, args="vim codex"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_direct_provider_executable_from_untrusted_path(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="codex"), ""
                    ),
                    ("ps", "-t", "/dev/pts/7", "-o", "pid=,ppid=,pgid=,stat=,args="): CommandResult(
                        (), 0, "1234 1 1234 Sl+ /tmp/codex --fake\n", ""
                    ),
                    **ps_response(args="/tmp/codex --fake"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_bare_provider_executable_name(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="codex"), ""
                    ),
                    ("ps", "-t", "/dev/pts/7", "-o", "pid=,ppid=,pgid=,stat=,args="): CommandResult(
                        (), 0, "1234 1 1234 Sl+ codex --fake\n", ""
                    ),
                    **ps_response(args="codex --fake"),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_malformed_pane_metadata(self):
        with tempfile.TemporaryDirectory() as repo:
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (),
                        0,
                        pane_line("codex-demo", "%1", repo) + "malformed\tmetadata\n",
                        "",
                    ),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "failed to parse tmux list-panes metadata line"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_refuses_malformed_numeric_and_boolean_pane_metadata(self):
        with tempfile.TemporaryDirectory() as repo:
            line = (
                f"codex-demo\t%1\t/dev/pts/7\t{Path(repo).resolve()}\tnode\t"
                "notpid\tmaybe\tmaybe\tnotcreated\tnotattached\n"
            )
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult((), 0, line, ""),
                }
            )
            with self.assertRaisesRegex(DiscoveryError, "failed to parse tmux list-panes pid"):
                select_target(repo=repo, provider="codex", runner=runner)

    def test_unrelated_pane_path_with_tab_does_not_break_discovery(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root) / "repo"
            repo.mkdir()
            unrelated = Path(root) / "has\ttab"
            unrelated.mkdir()
            script = write_provider_package(repo)
            args = f"node {script}"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (),
                        0,
                        pane_line("plain", "%9", unrelated, command="bash", pid=999, tty="/dev/pts/9")
                        + pane_line("codex-demo", "%1", repo, command="node", pid=1234),
                        "",
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(repo):
                selected = select_target(repo=str(repo), provider="codex", runner=runner)
            self.assertEqual(selected.pane.pane_id, "%1")

    def test_explicit_session_can_select_verified_codex_process(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            args = f"node {script}"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-s", "-t", "agent-terminal-contact", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("agent-terminal-contact", "%1", repo), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(repo):
                selected = select_target(
                    repo=repo,
                    provider="codex",
                    runner=runner,
                    explicit_session="agent-terminal-contact",
                )
            self.assertEqual(selected.pane.provider_evidence, "pane process args match codex")

    def test_explicit_sidecar_session_matches_original_repo_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            session = "codex-map-repo-ticket58-123456789abc"
            artifact_dir = tmp_path / session
            repo.mkdir()
            artifact_dir.mkdir()
            write_sidecar_request(artifact_dir, session=session, repo=repo)
            script = write_provider_package(repo)
            args = f"node {script}"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-s", "-t", session, "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line(session, "%1", artifact_dir), ""
                    ),
                    ("tmux", "display-message", "-p", "-t", "%1", PANE_FORMAT): CommandResult(
                        (), 0, pane_line(session, "%1", artifact_dir), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(repo):
                selected = select_target(
                    repo=str(repo),
                    provider="codex",
                    runner=runner,
                    explicit_session=session,
                )
                revalidated = revalidate_target(selected, runner)
            self.assertEqual(selected.repo, str(repo.resolve()))
            self.assertEqual(selected.expected_pane_path, str(artifact_dir.resolve()))
            self.assertEqual(selected.pane.session_name, session)
            self.assertEqual(revalidated.path, str(artifact_dir.resolve()))

    def test_explicit_sidecar_session_refuses_artifact_basename_session_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            artifact_dir = tmp_path / "not-the-session-name"
            repo.mkdir()
            artifact_dir.mkdir()
            session = "codex-map-repo-ticket58-123456789abc"
            write_sidecar_request(artifact_dir, session=session, repo=repo)
            script = write_provider_package(repo)
            args = f"node {script}"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-s", "-t", session, "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line(session, "%1", artifact_dir), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(
                        repo=str(repo),
                        provider="codex",
                        runner=runner,
                        explicit_session=session,
                    )

    def test_implicit_discovery_refuses_sidecar_manifest_repo_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            artifact_dir = tmp_path / "sidecar-artifact"
            repo.mkdir()
            artifact_dir.mkdir()
            session = "codex-map-repo-ticket58-123456789abc"
            write_sidecar_request(artifact_dir, session=session, repo=repo)
            script = write_provider_package(repo)
            args = f"node {script}"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line(session, "%1", artifact_dir), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(repo=str(repo), provider="codex", runner=runner)

    def test_explicit_sidecar_session_refuses_manifest_session_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            artifact_dir = tmp_path / "sidecar-artifact"
            repo.mkdir()
            artifact_dir.mkdir()
            session = "codex-map-repo-ticket58-123456789abc"
            write_sidecar_request(artifact_dir, session="codex-map-other-123456789abc", repo=repo)
            script = write_provider_package(repo)
            args = f"node {script}"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-s", "-t", session, "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line(session, "%1", artifact_dir), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(
                        repo=str(repo),
                        provider="codex",
                        runner=runner,
                        explicit_session=session,
                    )

    def test_explicit_sidecar_session_refuses_repo_root_pane_without_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            repo.mkdir()
            session = "codex-map-repo-ticket58-123456789abc"
            script = write_provider_package(repo)
            args = f"node {script}"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-s", "-t", session, "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line(session, "%1", repo), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(
                        repo=str(repo),
                        provider="codex",
                        runner=runner,
                        explicit_session=session,
                    )

    def test_explicit_sidecar_session_refuses_missing_registry_even_with_artifact_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            artifact_dir = tmp_path / "sidecar-artifact"
            repo.mkdir()
            artifact_dir.mkdir()
            session = "codex-map-repo-ticket58-123456789abc"
            write_sidecar_request(artifact_dir, session=session, repo=repo)
            (artifact_dir.parent / ".agent-tmux-sidecar-registry" / f"{session}.txt").unlink()
            script = write_provider_package(repo)
            args = f"node {script}"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-s", "-t", session, "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line(session, "%1", artifact_dir), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(
                        repo=str(repo),
                        provider="codex",
                        runner=runner,
                        explicit_session=session,
                    )

    def test_explicit_sidecar_session_refuses_artifact_dir_inside_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            artifact_dir = repo / ".sidecars" / "codex-map-repo-ticket58-123456789abc"
            repo.mkdir()
            artifact_dir.mkdir(parents=True)
            session = artifact_dir.name
            write_sidecar_request(artifact_dir, session=session, repo=repo)
            script = write_provider_package(repo)
            args = f"node {script}"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-s", "-t", session, "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line(session, "%1", artifact_dir), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(
                        repo=str(repo),
                        provider="codex",
                        runner=runner,
                        explicit_session=session,
                    )

    def test_explicit_sidecar_session_refuses_tampered_artifact_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            other_repo = tmp_path / "other"
            artifact_dir = tmp_path / "sidecar-artifact"
            repo.mkdir()
            other_repo.mkdir()
            artifact_dir.mkdir()
            session = "codex-map-repo-ticket58-123456789abc"
            write_sidecar_request(artifact_dir, session=session, repo=repo)
            (artifact_dir / "SIDECAR_REQUEST.txt").write_text(
                f"session={session}\nrepo={other_repo.resolve()}\nallowed_output_dir={artifact_dir.resolve()}\n",
                encoding="utf-8",
            )
            script = write_provider_package(repo)
            args = f"node {script}"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-s", "-t", session, "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line(session, "%1", artifact_dir), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "no tmux-managed codex pane"):
                    select_target(
                        repo=str(repo),
                        provider="codex",
                        runner=runner,
                        explicit_session=session,
                    )

    def test_sidecar_revalidate_refuses_artifact_path_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            session = "codex-map-repo-ticket58-123456789abc"
            artifact_dir = tmp_path / session
            other_artifact_dir = tmp_path / "other-sidecar-artifact"
            repo.mkdir()
            artifact_dir.mkdir()
            other_artifact_dir.mkdir()
            write_sidecar_request(artifact_dir, session=session, repo=repo)
            script = write_provider_package(repo)
            args = f"node {script}"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-s", "-t", session, "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line(session, "%1", artifact_dir), ""
                    ),
                    ("tmux", "display-message", "-p", "-t", "%1", PANE_FORMAT): CommandResult(
                        (), 0, pane_line(session, "%1", other_artifact_dir), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(args=args),
                }
            )
            with trusted_provider_root(repo):
                selected = select_target(
                    repo=str(repo),
                    provider="codex",
                    runner=runner,
                    explicit_session=session,
                )
                with self.assertRaisesRegex(DiscoveryError, "moved from"):
                    revalidate_target(selected, runner)

    def test_explicit_session_refuses_matching_panes_across_windows(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            args = f"node {script}"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-s", "-t", "agent-terminal-contact", "-F", PANE_FORMAT): CommandResult(
                        (),
                        0,
                        pane_line("agent-terminal-contact", "%1", repo, pid=111, tty="/dev/pts/7")
                        + pane_line("agent-terminal-contact", "%2", repo, pid=222, tty="/dev/pts/8"),
                        "",
                    ),
                    **tty_response(tty="/dev/pts/7", args=args, pid=111),
                    **tty_response(tty="/dev/pts/8", args=args, pid=222),
                    **proc_response(pid=111, args=args),
                    **proc_response(pid=222, args=args),
                }
            )
            with trusted_provider_root(repo):
                with self.assertRaisesRegex(DiscoveryError, "multiple"):
                    select_target(
                        repo=repo,
                        provider="codex",
                        runner=runner,
                        explicit_session="agent-terminal-contact",
                    )

    def test_revalidate_refuses_process_drift(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            args = f"node {script} --no-alt-screen"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, pid=1234), ""
                    ),
                    ("tmux", "display-message", "-p", "-t", "%1", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, pid=9999), ""
                    ),
                    **tty_response(args=args, pid=1234),
                    **proc_response(pid=1234, args=args),
                }
            )
            with trusted_provider_root(repo):
                selected = select_target(repo=repo, provider="codex", runner=runner)
            with self.assertRaisesRegex(DiscoveryError, "process changed"):
                revalidate_target(selected, runner)

    def test_revalidate_refuses_provider_process_drift(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, pid=100), ""
                    ),
                    ("tmux", "display-message", "-p", "-t", "%1", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, pid=100), ""
                    ),
                    ("ps", "-t", "/dev/pts/7", "-o", "pid=,ppid=,pgid=,stat=,args="): CommandResult(
                        (),
                        0,
                        f"200 100 200 Sl+ node {script} --no-alt-screen\n",
                        "",
                    ),
                    ("ps", "-p", "100", "-o", "args="): CommandResult((), 0, "bash\n", ""),
                    **proc_response(pid=200, args=f"node {script} --no-alt-screen"),
                    **proc_response(pid=300, args=f"node {script} --no-alt-screen"),
                }
            )
            with trusted_provider_root(repo):
                selected = select_target(repo=repo, provider="codex", runner=runner)
                runner.responses[("ps", "-t", "/dev/pts/7", "-o", "pid=,ppid=,pgid=,stat=,args=")] = CommandResult(
                    (),
                    0,
                    f"300 100 300 Sl+ node {script} --no-alt-screen\n",
                    "",
                )
                with self.assertRaisesRegex(DiscoveryError, "provider process changed"):
                    revalidate_target(selected, runner)

    def test_detects_provider_from_foreground_child_when_pane_pid_is_shell(self):
        with tempfile.TemporaryDirectory() as repo:
            script = write_provider_package(repo)
            args = f"node {script} --no-alt-screen"
            runner = FakeRunner(
                {
                    ("tmux", "list-panes", "-a", "-F", PANE_FORMAT): CommandResult(
                        (), 0, pane_line("codex-demo", "%1", repo, command="node", pid=100), ""
                    ),
                    ("ps", "-t", "/dev/pts/7", "-o", "pid=,ppid=,pgid=,stat=,args="): CommandResult(
                        (), 0, f"100 1 100 Ss bash\n200 100 200 Sl+ {args}\n", ""
                    ),
                    **ps_response(100, args="bash"),
                    **proc_response(pid=200, args=args),
                }
            )
            with trusted_provider_root(repo):
                selected = select_target(repo=repo, provider="codex", runner=runner)
            self.assertEqual(selected.pane.provider_pid, 200)


if __name__ == "__main__":
    unittest.main()
