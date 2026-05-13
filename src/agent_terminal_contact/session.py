"""tmux pane discovery for guarded agent contact."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
from typing import Sequence

from .runner import Runner


PANE_FORMAT = (
    "#{session_name}\t#{pane_id}\t#{pane_tty}\t#{pane_current_path}\t#{pane_current_command}\t"
    "#{pane_pid}\t#{pane_active}\t#{pane_dead}\t#{session_created}\t#{session_attached}"
)
SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
PANE_ID_RE = re.compile(r"^%[0-9]+$")
PROVIDER_EXECUTABLES = {
    "codex": {"codex", "codex.js"},
    "claude": {"claude", "claude.exe", "claude.js", "claude-code"},
}
PROVIDER_PATH_COMMANDS = {
    "codex": ("codex",),
    "claude": ("claude", "claude-code"),
}
NODE_LAUNCHERS = {"node", "nodejs", "bun", "deno"}
TRUSTED_PROVIDER_ROOTS_ENV = "AGENT_CONTACT_TRUSTED_PROVIDER_ROOTS"
TRUSTED_LAUNCHER_ROOTS_ENV = "AGENT_CONTACT_TRUSTED_LAUNCHER_ROOTS"
NODE_VALUE_OPTIONS = {
    "--conditions",
    "-C",
    "--icu-data-dir",
    "--openssl-config",
    "--title",
}
NODE_CODE_LOADING_OPTIONS = {"--require", "-r", "--import", "--loader", "--experimental-loader"}
NODE_INLINE_CODE_OPTIONS = {"--eval", "-e", "--print", "-p", "--check", "-c"}


class DiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderPackage:
    name: str
    path_components: tuple[str, ...]


PROVIDER_PACKAGES = {
    "codex": ProviderPackage("@openai/codex", ("node_modules", "@openai", "codex")),
    "claude": ProviderPackage("@anthropic-ai/claude-code", ("node_modules", "@anthropic-ai", "claude-code")),
}


@dataclass(frozen=True)
class TmuxPane:
    session_name: str
    pane_id: str
    tty: str
    path: str
    command: str
    pid: int
    provider_pid: int
    active: bool
    dead: bool
    created: int
    attached: int
    provider_evidence: str
    process_args: str


@dataclass(frozen=True)
class TargetSelection:
    repo: str
    provider: str
    pane: TmuxPane
    candidates: tuple[TmuxPane, ...]
    expected_pane_path: str


@dataclass(frozen=True)
class TrustedRootSuggestion:
    repo: str
    provider: str
    session_name: str
    pane_id: str
    provider_pid: int
    provider_root: str
    launcher_root: str | None
    process_args: str


def select_target(
    *,
    repo: str,
    provider: str,
    runner: Runner,
    explicit_session: str | None = None,
) -> TargetSelection:
    repo_path = _resolve_existing_repo(repo)
    provider = _normalize_provider(provider)

    panes = _list_panes(runner, explicit_session=explicit_session)
    candidates: list[tuple[TmuxPane, str]] = []
    for pane in panes:
        if pane.dead:
            continue
        expected_pane_path = _expected_pane_path_for_repo(
            pane,
            repo_path,
            explicit_session=explicit_session,
        )
        if expected_pane_path is None:
            continue
        matched = _with_provider_evidence(pane, provider, runner)
        if matched is not None:
            candidates.append((matched, expected_pane_path))

    if not candidates:
        scope = f" in session {explicit_session!r}" if explicit_session else ""
        raise DiscoveryError(f"no tmux-managed {provider} pane found for {repo_path}{scope}")
    if len(candidates) > 1:
        names = ", ".join(f"{pane.session_name}:{pane.pane_id}" for pane, _expected in candidates)
        raise DiscoveryError(f"multiple tmux-managed {provider} panes found for {repo_path}: {names}")

    pane, expected_pane_path = candidates[0]
    return TargetSelection(repo_path, provider, pane, tuple(candidate for candidate, _expected in candidates), expected_pane_path)


def suggest_trusted_roots(
    *,
    repo: str,
    provider: str,
    runner: Runner,
    explicit_session: str | None = None,
) -> tuple[TrustedRootSuggestion, ...]:
    repo_path = _resolve_existing_repo(repo)
    provider = _normalize_provider(provider)
    panes = _list_panes(runner, explicit_session=explicit_session)
    suggestions: list[TrustedRootSuggestion] = []
    opposite = "claude" if provider == "codex" else "codex"

    for pane in panes:
        if pane.dead:
            continue
        if _expected_pane_path_for_repo(pane, repo_path, explicit_session=explicit_session) is None:
            continue
        if opposite in pane.session_name.lower():
            continue
        suggestion = _trusted_root_suggestion_for_pane(repo_path, provider, pane, runner)
        if suggestion is not None:
            suggestions.append(suggestion)

    if not suggestions:
        scope = f" in session {explicit_session!r}" if explicit_session else ""
        raise DiscoveryError(f"no trusted-root suggestion found for {provider} pane at {repo_path}{scope}")
    return tuple(suggestions)


def revalidate_target(selection: TargetSelection, runner: Runner) -> TmuxPane:
    current = _read_pane(selection.pane.pane_id, runner)
    if current.dead:
        raise DiscoveryError(f"target pane {selection.pane.pane_id} is dead")
    if current.attached > 0:
        raise DiscoveryError(f"target pane {selection.pane.pane_id} session is attached")
    if _resolve_path(current.path) != selection.expected_pane_path:
        raise DiscoveryError(
            f"target pane {selection.pane.pane_id} moved from {selection.expected_pane_path!r} to {current.path!r}"
        )
    if current.command != selection.pane.command or current.pid != selection.pane.pid:
        raise DiscoveryError(
            f"target pane {selection.pane.pane_id} process changed from "
            f"{selection.pane.command}/{selection.pane.pid} to {current.command}/{current.pid}"
        )
    matched = _with_provider_evidence(current, selection.provider, runner)
    if matched is None:
        raise DiscoveryError(
            f"target pane {selection.pane.pane_id} no longer looks like provider {selection.provider!r}"
        )
    if matched.provider_pid != selection.pane.provider_pid or matched.process_args != selection.pane.process_args:
        raise DiscoveryError(
            f"target pane {selection.pane.pane_id} provider process changed from "
            f"{selection.pane.provider_pid} to {matched.provider_pid}"
        )
    return matched


def validate_session_name(session: str) -> None:
    if not SESSION_NAME_RE.match(session):
        raise DiscoveryError("session name must match [A-Za-z0-9_.-]+")


def validate_pane_id(pane_id: str) -> None:
    if not PANE_ID_RE.match(pane_id):
        raise DiscoveryError("pane id must match %[0-9]+")


def _read_pane(pane_id: str, runner: Runner) -> TmuxPane:
    validate_pane_id(pane_id)
    result = runner.run(["tmux", "display-message", "-p", "-t", pane_id, PANE_FORMAT])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise DiscoveryError(f"failed to inspect pane {pane_id!r}: {detail}")
    panes = _parse_pane_lines(result.stdout.splitlines(), source=f"pane {pane_id!r}")
    if len(panes) != 1:
        raise DiscoveryError(f"failed to parse pane metadata for {pane_id!r}")
    return panes[0]


def _list_panes(runner: Runner, *, explicit_session: str | None) -> tuple[TmuxPane, ...]:
    if explicit_session:
        validate_session_name(explicit_session)
        args = ["tmux", "list-panes", "-s", "-t", explicit_session, "-F", PANE_FORMAT]
    else:
        args = ["tmux", "list-panes", "-a", "-F", PANE_FORMAT]
    result = runner.run(args)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise DiscoveryError(f"tmux pane discovery failed: {detail}")
    return tuple(_parse_pane_lines(result.stdout.splitlines(), source="list-panes"))


def _expected_pane_path_for_repo(
    pane: TmuxPane,
    repo_path: str,
    *,
    explicit_session: str | None,
) -> str | None:
    pane_path = _resolve_path(pane.path)
    if explicit_session is not None and _is_code_map_sidecar_session(pane.session_name):
        request = _sidecar_request_for_pane(pane, repo_path)
        if request is None:
            return None
        return request.artifact_dir
    if pane_path == repo_path:
        return pane_path
    return None


def _is_code_map_sidecar_session(session_name: str) -> bool:
    return session_name.startswith("codex-map-")


@dataclass(frozen=True)
class SidecarRequest:
    session: str
    repo: str
    artifact_dir: str


def _sidecar_request_for_pane(pane: TmuxPane, repo_path: str) -> SidecarRequest | None:
    artifact_dir = Path(pane.path).expanduser()
    try:
        if artifact_dir.is_symlink() or not artifact_dir.is_dir():
            return None
        resolved_artifact_path = artifact_dir.resolve(strict=True)
    except OSError:
        return None
    request_file = _sidecar_registry_path(resolved_artifact_path, pane.session_name)
    if request_file is None:
        return None
    registry_fields = _read_sidecar_request_fields(request_file)
    if registry_fields is None:
        return None
    artifact_manifest = resolved_artifact_path / "SIDECAR_REQUEST.txt"
    manifest_fields = _read_sidecar_request_fields(artifact_manifest)
    if manifest_fields is None:
        return None
    registry_session = registry_fields.get("session", "")
    registry_repo_raw = registry_fields.get("repo", "")
    registry_artifact_raw = registry_fields.get("allowed_output_dir", "")
    manifest_session = manifest_fields.get("session", "")
    manifest_repo_raw = manifest_fields.get("repo", "")
    manifest_artifact_raw = manifest_fields.get("allowed_output_dir", "")
    if not registry_session or not registry_repo_raw or not registry_artifact_raw:
        return None
    if not manifest_session or not manifest_repo_raw or not manifest_artifact_raw:
        return None
    if (
        manifest_session != registry_session
        or manifest_repo_raw != registry_repo_raw
        or manifest_artifact_raw != registry_artifact_raw
    ):
        return None
    try:
        manifest_repo = _resolve_existing_repo(registry_repo_raw)
        manifest_artifact_path = Path(registry_artifact_raw).expanduser().resolve(strict=True)
    except (DiscoveryError, OSError):
        return None
    if registry_session != pane.session_name:
        return None
    if manifest_repo != repo_path:
        return None
    if manifest_artifact_path != resolved_artifact_path:
        return None
    if _path_is_relative_to(resolved_artifact_path, Path(manifest_repo)):
        return None
    return SidecarRequest(
        session=pane.session_name,
        repo=manifest_repo,
        artifact_dir=str(resolved_artifact_path),
    )


def _read_sidecar_request_fields(request_file: Path) -> dict[str, str] | None:
    try:
        if request_file.is_symlink() or not request_file.is_file() or request_file.stat().st_size > 65536:
            return None
        text = request_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    fields: dict[str, str] = {}
    for raw_line in text.splitlines():
        if not raw_line or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        if key in fields:
            return None
        fields[key] = value
    return fields


def _sidecar_registry_path(artifact_dir: Path, session_name: str) -> Path | None:
    try:
        validate_session_name(session_name)
    except DiscoveryError:
        return None
    registry_dir = artifact_dir.parent / ".agent-tmux-sidecar-registry"
    try:
        if registry_dir.is_symlink() or not registry_dir.is_dir():
            return None
    except OSError:
        return None
    return registry_dir / f"{session_name}.txt"


def _parse_pane_lines(lines: Sequence[str], *, source: str) -> list[TmuxPane]:
    panes: list[TmuxPane] = []
    for line in lines:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 10:
            raise DiscoveryError(f"failed to parse tmux {source} metadata line")
        session_name, pane_id, tty = parts[:3]
        command, pid, active, dead, created, attached = parts[-6:]
        path = "\t".join(parts[3:-6])
        if not session_name.strip() or not tty.strip() or not path.strip() or not command.strip():
            raise DiscoveryError(f"failed to parse tmux {source} metadata line")
        validate_pane_id(pane_id)
        panes.append(
            TmuxPane(
                session_name=session_name,
                pane_id=pane_id,
                tty=tty,
                path=path,
                command=command,
                pid=_parse_int(pid, source=source, field="pid"),
                provider_pid=0,
                active=_parse_bool(active, source=source, field="active"),
                dead=_parse_bool(dead, source=source, field="dead"),
                created=_parse_int(created, source=source, field="created"),
                attached=_parse_int(attached, source=source, field="attached"),
                provider_evidence="unmatched",
                process_args="",
            )
        )
    return panes


def _with_provider_evidence(pane: TmuxPane, provider: str, runner: Runner) -> TmuxPane | None:
    session_name = pane.session_name.lower()
    command = pane.command.lower()
    opposite = "claude" if provider == "codex" else "codex"

    if opposite in session_name:
        return None

    provider_pid, process_args = _provider_process(pane, provider, runner)
    if _process_args_match_provider(process_args, opposite):
        return None

    if command == provider and provider_pid:
        evidence = f"pane command is {provider}"
    elif provider_pid:
        evidence = f"pane process args match {provider}"
    else:
        return None

    return TmuxPane(
        session_name=pane.session_name,
        pane_id=pane.pane_id,
        tty=pane.tty,
        path=pane.path,
        command=pane.command,
        pid=pane.pid,
        provider_pid=provider_pid,
        active=pane.active,
        dead=pane.dead,
        created=pane.created,
        attached=pane.attached,
        provider_evidence=evidence,
        process_args=process_args,
    )


def _provider_process(pane: TmuxPane, provider: str, runner: Runner) -> tuple[int, str]:
    tty_processes = _tty_processes(pane.tty, runner)
    foreground_processes = tuple(process for process in tty_processes if process.live_foreground)
    if foreground_processes:
        for process in foreground_processes:
            identity = _process_identity(process.pid, runner)
            if identity is None:
                continue
            if _process_identity_matches_provider(identity, provider):
                return process.pid, identity.display_args
        return 0, ""

    return 0, ""


def _trusted_root_suggestion_for_pane(
    repo_path: str,
    provider: str,
    pane: TmuxPane,
    runner: Runner,
) -> TrustedRootSuggestion | None:
    foreground_processes = tuple(process for process in _tty_processes(pane.tty, runner) if process.live_foreground)
    for process in foreground_processes:
        identity = _process_identity(process.pid, runner)
        if identity is None:
            continue
        roots = _process_identity_provider_roots(identity, provider)
        if roots is None:
            continue
        provider_root, launcher_root = roots
        if not _provider_root_has_path_anchor(provider_root, provider, launcher_root, runner):
            continue
        return TrustedRootSuggestion(
            repo=repo_path,
            provider=provider,
            session_name=pane.session_name,
            pane_id=pane.pane_id,
            provider_pid=process.pid,
            provider_root=str(provider_root),
            launcher_root=str(launcher_root) if launcher_root is not None else None,
            process_args=identity.display_args,
        )
    return None


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    ppid: int
    pgid: int
    stat: str
    args: str

    @property
    def foreground(self) -> bool:
        return "+" in self.stat

    @property
    def live_foreground(self) -> bool:
        return self.foreground and not any(state in self.stat for state in ("T", "Z", "X"))


@dataclass(frozen=True)
class ProcessIdentity:
    argv: tuple[str, ...]
    exe: str
    environ: dict[str, str]

    @property
    def display_args(self) -> str:
        return shlex.join(self.argv)


def _tty_processes(tty: str, runner: Runner) -> tuple[ProcessInfo, ...]:
    if not tty:
        raise DiscoveryError("target pane has no TTY for provider process verification")
    result = runner.run(["ps", "-t", tty, "-o", "pid=,ppid=,pgid=,stat=,args="])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise DiscoveryError(f"failed to inspect target pane TTY processes: {detail}")
    processes = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 4)
        if len(parts) != 5:
            continue
        pid, ppid, pgid, stat, args = parts
        processes.append(
            ProcessInfo(
                pid=_parse_int(pid, source="TTY process", field="pid"),
                ppid=_parse_int(ppid, source="TTY process", field="ppid"),
                pgid=_parse_int(pgid, source="TTY process", field="pgid"),
                stat=stat,
                args=args,
            )
        )
    processes.sort(key=lambda process: (not process.live_foreground, process.pid))
    return tuple(processes)


def _process_identity(pid: int, runner: Runner) -> ProcessIdentity | None:
    if pid <= 0:
        return None
    cmdline = runner.run(["cat", f"/proc/{pid}/cmdline"])
    if cmdline.returncode != 0:
        return None
    argv = tuple(part for part in cmdline.stdout.split("\0") if part)
    if not argv:
        return None
    exe = runner.run(["readlink", "-f", f"/proc/{pid}/exe"])
    if exe.returncode != 0:
        return None
    exe_path = exe.stdout.strip()
    if not exe_path:
        return None
    environ = runner.run(["cat", f"/proc/{pid}/environ"])
    if environ.returncode != 0:
        return None
    return ProcessIdentity(argv=argv, exe=exe_path, environ=_parse_proc_environ(environ.stdout))


def _process_identity_matches_provider(identity: ProcessIdentity, provider: str) -> bool:
    tokens = identity.argv
    if not tokens:
        return False

    command = _basename(tokens[0])
    if command == "env":
        tokens = tuple(_strip_env_prefix(tokens[1:]))
        if not tokens:
            return False
        command = _basename(tokens[0])

    exe_command = Path(identity.exe).name.lower()
    if command in PROVIDER_EXECUTABLES[provider]:
        if exe_command in NODE_LAUNCHERS:
            return False
        if not _direct_command_matches_provider(tokens[0], provider):
            return False
        return _path_equals(identity.exe, tokens[0])

    if command in NODE_LAUNCHERS:
        if exe_command not in NODE_LAUNCHERS:
            return False
        if _node_environment_loads_code(identity.environ):
            return False
        if not _is_trusted_launcher_path(identity.exe):
            return False
        if "/" in tokens[0] and not _path_equals(identity.exe, tokens[0]):
            return False
        return _node_launch_matches_provider(tokens[1:], provider)

    return False


def _process_identity_provider_roots(identity: ProcessIdentity, provider: str) -> tuple[Path, Path | None] | None:
    tokens = identity.argv
    if not tokens:
        return None

    command = _basename(tokens[0])
    if command == "env":
        tokens = tuple(_strip_env_prefix(tokens[1:]))
        if not tokens:
            return None
        command = _basename(tokens[0])

    exe_command = Path(identity.exe).name.lower()
    if command in PROVIDER_EXECUTABLES[provider]:
        if exe_command in NODE_LAUNCHERS:
            return None
        if not _path_equals(identity.exe, tokens[0]):
            return None
        provider_root = _script_token_provider_package_root(tokens[0], provider, require_trust=False)
        if provider_root is None:
            return None
        return provider_root, None

    if command in NODE_LAUNCHERS:
        if exe_command not in NODE_LAUNCHERS:
            return None
        if _node_environment_loads_code(identity.environ):
            return None
        if "/" in tokens[0] and not _path_equals(identity.exe, tokens[0]):
            return None
        provider_root = _node_launch_provider_package_root(tokens[1:], provider, require_trust=False)
        if provider_root is None:
            return None
        return provider_root, Path(identity.exe).parent

    return None


def _process_args_match_provider(process_args: str, provider: str) -> bool:
    tokens = _command_tokens(process_args)
    if not tokens:
        return False

    command = _basename(tokens[0])
    if command == "env":
        tokens = _strip_env_prefix(tokens[1:])
        if not tokens:
            return False
        command = _basename(tokens[0])

    if command in PROVIDER_EXECUTABLES[provider]:
        return _direct_command_matches_provider(tokens[0], provider)

    if command in NODE_LAUNCHERS:
        return _node_launch_matches_provider(tokens[1:], provider)

    return False


def _command_tokens(process_args: str) -> tuple[str, ...]:
    try:
        return tuple(shlex.split(process_args))
    except ValueError:
        return tuple(process_args.split())


def _strip_env_prefix(tokens: Sequence[str]) -> list[str]:
    stripped = list(tokens)
    while stripped and ("=" in stripped[0] or stripped[0].startswith("-")):
        stripped.pop(0)
    return stripped


def _node_launch_matches_provider(tokens: Sequence[str], provider: str) -> bool:
    return _node_launch_provider_package_root(tokens, provider, require_trust=True) is not None


def _node_launch_provider_package_root(
    tokens: Sequence[str],
    provider: str,
    *,
    require_trust: bool,
) -> Path | None:
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            index += 1
            break
        if token in NODE_INLINE_CODE_OPTIONS or any(
            token.startswith(f"{option}=") for option in NODE_INLINE_CODE_OPTIONS if option.startswith("--")
        ):
            return None
        if token in NODE_CODE_LOADING_OPTIONS or any(
            token.startswith(f"{option}=") for option in NODE_CODE_LOADING_OPTIONS if option.startswith("--")
        ):
            return None
        if token in NODE_VALUE_OPTIONS:
            index += 2
            continue
        if any(token.startswith(f"{option}=") for option in NODE_VALUE_OPTIONS if option.startswith("--")):
            index += 1
            continue
        if token.startswith("-"):
            return None
        return _script_token_provider_package_root(token, provider, require_trust=require_trust)
    if index < len(tokens):
        return _script_token_provider_package_root(tokens[index], provider, require_trust=require_trust)
    return None


def _parse_proc_environ(raw: str) -> dict[str, str]:
    environ: dict[str, str] = {}
    for item in raw.split("\0"):
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        environ[key] = value
    return environ


def _node_environment_loads_code(environ: dict[str, str]) -> bool:
    node_options = environ.get("NODE_OPTIONS", "")
    if not node_options:
        return False
    return not _node_options_are_safe(node_options)


def _node_options_are_safe(value: str) -> bool:
    tokens = _command_tokens(value)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in NODE_INLINE_CODE_OPTIONS or any(
            token.startswith(f"{option}=") for option in NODE_INLINE_CODE_OPTIONS if option.startswith("--")
        ):
            return False
        if token in NODE_CODE_LOADING_OPTIONS or any(
            token.startswith(f"{option}=") for option in NODE_CODE_LOADING_OPTIONS if option.startswith("--")
        ):
            return False
        if token in NODE_VALUE_OPTIONS:
            index += 2
            continue
        if any(token.startswith(f"{option}=") for option in NODE_VALUE_OPTIONS if option.startswith("--")):
            index += 1
            continue
        if token.startswith("-"):
            return False
        return False
    return True


def _direct_command_matches_provider(token: str, provider: str) -> bool:
    if "/" not in token:
        return False
    return _script_token_is_provider_entrypoint(token, provider)


def _script_token_is_provider_entrypoint(token: str, provider: str) -> bool:
    return _script_token_provider_package_root(token, provider, require_trust=True) is not None


def _script_token_provider_package_root(token: str, provider: str, *, require_trust: bool) -> Path | None:
    package = PROVIDER_PACKAGES[provider].name
    path = Path(token).expanduser()
    if not path.exists():
        return None
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return None
    root = _provider_package_root(resolved, provider)
    if root is None:
        return None
    if require_trust and not _is_trusted_provider_root(root):
        return None
    package_json = root / "package.json"
    try:
        package_data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if package_data.get("name") != package:
        return None
    if not _package_bin_matches(package_data.get("bin"), resolved, root, provider):
        return None
    return root


def _provider_root_has_path_anchor(
    provider_root: Path,
    provider: str,
    launcher_root: Path | None,
    runner: Runner,
) -> bool:
    for command in PROVIDER_PATH_COMMANDS[provider]:
        result = runner.run(["bash", "-lc", f"command -v -- {shlex.quote(command)}"])
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            path = line.strip()
            if not path:
                continue
            anchored_root = _script_token_provider_package_root(path, provider, require_trust=False)
            if anchored_root is not None and _path_equals_path(provider_root, anchored_root):
                return True
    npm_root = _npm_global_provider_root(provider, launcher_root, runner)
    if npm_root is not None and _path_equals_path(provider_root, npm_root):
        return True
    return False


def _npm_global_provider_root(provider: str, launcher_root: Path | None, runner: Runner) -> Path | None:
    if launcher_root is None:
        return None
    npm = runner.run(["bash", "-lc", "command -v -- npm"])
    if npm.returncode != 0:
        return None
    npm_path = next((line.strip() for line in npm.stdout.splitlines() if line.strip()), "")
    if not npm_path or not _path_parent_equals(Path(npm_path), launcher_root):
        return None
    result = runner.run([npm_path, "root", "-g"])
    if result.returncode != 0:
        return None
    root_line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    if not root_line:
        return None
    components = PROVIDER_PACKAGES[provider].path_components
    if components and components[0] == "node_modules":
        components = components[1:]
    package_root = Path(root_line, *components).expanduser()
    package_json = package_root / "package.json"
    try:
        package_data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if package_data.get("name") != PROVIDER_PACKAGES[provider].name:
        return None
    return package_root


def _path_parent_equals(path: Path, root: Path) -> bool:
    try:
        return path.expanduser().absolute().parent.resolve(strict=False) == root.expanduser().resolve(strict=False)
    except OSError:
        return False


def _provider_package_root(script_path: Path, provider: str) -> Path | None:
    parts = script_path.parts
    lowered_parts = tuple(part.lower() for part in parts)
    package_parts = tuple(part.lower() for part in PROVIDER_PACKAGES[provider].path_components)
    for index in range(len(lowered_parts) - len(package_parts) + 1):
        if lowered_parts[index : index + len(package_parts)] == package_parts:
            return Path(*parts[: index + len(package_parts)])
    return None


def _is_trusted_provider_root(package_root: Path) -> bool:
    trusted_roots = _trusted_provider_roots()
    return any(_path_equals_path(package_root, trusted_root) for trusted_root in trusted_roots)


def _trusted_provider_roots() -> tuple[Path, ...]:
    return _trusted_roots_from_env(TRUSTED_PROVIDER_ROOTS_ENV)


def _is_trusted_launcher_path(exe_path: str) -> bool:
    trusted_roots = _trusted_roots_from_env(TRUSTED_LAUNCHER_ROOTS_ENV)
    return any(_path_parent_equals(Path(exe_path), trusted_root) for trusted_root in trusted_roots)


def _trusted_roots_from_env(env_name: str) -> tuple[Path, ...]:
    roots: list[Path] = []
    extra = os.environ.get(env_name, "")
    for raw in extra.split(os.pathsep):
        if raw:
            roots.append(Path(raw).expanduser())

    resolved = []
    for root in roots:
        try:
            resolved.append(root.resolve(strict=False))
        except OSError:
            continue
    return tuple(resolved)


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root)
        return True
    except ValueError:
        return False


def _path_equals(left: str, right: str) -> bool:
    try:
        return _path_equals_path(Path(left), Path(right))
    except OSError:
        return False


def _path_equals_path(left: Path, right: Path) -> bool:
    try:
        return left.expanduser().resolve(strict=True) == right.expanduser().resolve(strict=True)
    except OSError:
        return False


def _package_bin_matches(bin_field: object, script_path: Path, root: Path, provider: str) -> bool:
    candidates: list[str] = []
    if isinstance(bin_field, str):
        candidates.append(bin_field)
    elif isinstance(bin_field, dict):
        for name in PROVIDER_EXECUTABLES[provider]:
            value = bin_field.get(name)
            if isinstance(value, str):
                candidates.append(value)
    for candidate in candidates:
        try:
            if (root / candidate).resolve(strict=True) == script_path:
                return True
        except OSError:
            continue
    return False


def _basename(token: str) -> str:
    return Path(token).name.lower()


def _normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized not in {"codex", "claude"}:
        raise DiscoveryError("provider must be 'codex' or 'claude'")
    return normalized


def _resolve_existing_repo(repo: str) -> str:
    path = Path(repo).expanduser()
    if not path.exists() or not path.is_dir():
        raise DiscoveryError(f"repo path does not exist or is not a directory: {repo}")
    return str(path.resolve())


def _resolve_path(path: str) -> str:
    if not path:
        return ""
    return str(Path(path).expanduser().resolve())


def _parse_int(value: str, *, source: str, field: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise DiscoveryError(f"failed to parse tmux {source} {field}") from None


def _parse_bool(value: str, *, source: str, field: str) -> bool:
    if value == "0":
        return False
    if value == "1":
        return True
    raise DiscoveryError(f"failed to parse tmux {source} {field}")
