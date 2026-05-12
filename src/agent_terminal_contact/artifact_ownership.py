"""Installed artifact ownership lookup for AgentTerminalContact surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import filecmp
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any


DEFAULT_MANIFEST_NAME = "artifact_ownership.json"
ENV_VAR_RE = re.compile(r"\$(?P<plain>[A-Za-z_][A-Za-z0-9_]*)|\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}")


class ArtifactLookupError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArtifactManifest:
    path: Path
    source_repo: Path
    data: dict[str, Any]


def default_manifest_path() -> Path:
    return Path(__file__).resolve().parents[2] / DEFAULT_MANIFEST_NAME


def artifact_info_payload(
    query: str | None,
    *,
    all_artifacts: bool = False,
    manifest_path: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not all_artifacts and not query:
        raise ArtifactLookupError("artifact query is required unless --all is used")
    manifest = load_manifest(manifest_path)
    environment = _environment(env)
    artifacts = manifest.data.get("artifacts")
    if not isinstance(artifacts, list):
        raise ArtifactLookupError("artifact manifest must contain an artifacts list")

    reports = [
        _artifact_report(manifest, artifact, environment)
        for artifact in artifacts
        if isinstance(artifact, dict)
    ]
    matches = reports if all_artifacts else [report for report in reports if _matches_query(report, query or "", environment)]
    return {
        "status": "ok" if matches else "unknown",
        "query": query,
        "manifest_path": str(manifest.path),
        "source_repo": str(manifest.source_repo),
        "matches": matches,
    }


def load_manifest(manifest_path: str | Path | None = None) -> ArtifactManifest:
    path = Path(manifest_path).expanduser() if manifest_path is not None else default_manifest_path()
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ArtifactLookupError(f"artifact manifest is not readable: {path}") from exc
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactLookupError(f"artifact manifest is invalid JSON: {resolved}: {exc}") from exc
    if not isinstance(data, dict):
        raise ArtifactLookupError("artifact manifest root must be a JSON object")
    return ArtifactManifest(path=resolved, source_repo=resolved.parent, data=data)


def _artifact_report(
    manifest: ArtifactManifest,
    artifact: dict[str, Any],
    environment: dict[str, str],
) -> dict[str, Any]:
    artifact_id = _required_string(artifact, "id")
    kind = _required_string(artifact, "kind")
    ownership = _required_string(artifact, "ownership")
    if ownership not in {"owned", "not_owned"}:
        raise ArtifactLookupError(f"artifact {artifact_id!r} has invalid ownership: {ownership!r}")

    installed_path = _expand_path(_required_string(artifact, "installed_path"), environment)
    source_value = artifact.get("source_path")
    source_path = None
    if source_value is not None:
        if not isinstance(source_value, str) or not source_value:
            raise ArtifactLookupError(f"artifact {artifact_id!r} source_path must be a string or null")
        source_path = _source_path(manifest.source_repo, source_value)

    match = _installed_match(installed_path, source_path, ownership)
    source_repo = str(manifest.source_repo)
    report: dict[str, Any] = {
        "id": artifact_id,
        "kind": kind,
        "ownership": ownership,
        "owns_artifact": ownership == "owned",
        "installed_path": str(installed_path),
        "installed_exists": installed_path.exists() or installed_path.is_symlink(),
        "source_repo": source_repo,
        "source_path": str(source_path) if source_path is not None else None,
        "source_exists": source_path.exists() if source_path is not None else None,
        "installed_matches_source": match["matches"],
        "match_type": match["type"],
        "match_reason": match["reason"],
        "install_command": _format_command(artifact.get("install_command"), source_repo),
        "check_command": _format_command(artifact.get("check_command"), source_repo),
        "rollout_command": _format_command(manifest.data.get("rollout_command"), source_repo),
        "command_names": _string_list(artifact.get("command_names"), field="command_names", artifact_id=artifact_id),
    }
    if artifact.get("delegates_to") is not None:
        delegates_to = artifact["delegates_to"]
        if not isinstance(delegates_to, str):
            raise ArtifactLookupError(f"artifact {artifact_id!r} delegates_to must be a string")
        report["delegates_to"] = str(_expand_path(delegates_to, environment))
    if artifact.get("notes") is not None:
        notes = artifact["notes"]
        if not isinstance(notes, str):
            raise ArtifactLookupError(f"artifact {artifact_id!r} notes must be a string")
        report["notes"] = notes
    return report


def _required_string(artifact: dict[str, Any], field: str) -> str:
    value = artifact.get(field)
    if not isinstance(value, str) or not value:
        artifact_id = artifact.get("id", "<unknown>")
        raise ArtifactLookupError(f"artifact {artifact_id!r} field {field!r} must be a non-empty string")
    return value


def _string_list(value: Any, *, field: str, artifact_id: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ArtifactLookupError(f"artifact {artifact_id!r} field {field!r} must be a list of strings")
    return list(value)


def _environment(env: dict[str, str] | None) -> dict[str, str]:
    result = dict(os.environ if env is None else env)
    result.setdefault("HOME", str(Path.home()))
    result.setdefault("CODEX_HOME", str(Path(result["HOME"]) / ".codex"))
    result.setdefault("PATH", os.environ.get("PATH", ""))
    return result


def _expand_path(value: str, environment: dict[str, str]) -> Path:
    def replace(match: re.Match[str]) -> str:
        name = match.group("plain") or match.group("braced")
        return environment.get(name, "")

    expanded = ENV_VAR_RE.sub(replace, value)
    if expanded == "~" or expanded.startswith("~/"):
        expanded = environment["HOME"] + expanded[1:]
    path = Path(expanded).expanduser()
    if path.is_absolute():
        return path
    return Path.cwd() / path


def _source_path(source_repo: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve(strict=False)
    return (source_repo / path).resolve(strict=False)


def _installed_match(installed_path: Path, source_path: Path | None, ownership: str) -> dict[str, Any]:
    if ownership != "owned":
        return {"matches": None, "type": "not_owned", "reason": "artifact is explicitly not owned by this repo"}
    if source_path is None:
        return {"matches": False, "type": "missing_source_path", "reason": "owned artifact has no source path"}
    if not source_path.exists():
        return {"matches": False, "type": "source_missing", "reason": f"source path is missing: {source_path}"}
    if not (installed_path.exists() or installed_path.is_symlink()):
        return {"matches": False, "type": "installed_missing", "reason": f"installed path is missing: {installed_path}"}
    if installed_path.is_symlink():
        try:
            if installed_path.resolve(strict=True) == source_path.resolve(strict=True):
                return {"matches": True, "type": "symlink", "reason": "installed symlink resolves to source path"}
        except OSError as exc:
            return {"matches": False, "type": "broken_symlink", "reason": str(exc)}
    if installed_path.is_file() and source_path.is_file() and filecmp.cmp(installed_path, source_path, shallow=False):
        return {"matches": True, "type": "bytes", "reason": "installed file bytes match source file"}
    return {"matches": False, "type": "different", "reason": "installed artifact differs from source path"}


def _matches_query(report: dict[str, Any], query: str, environment: dict[str, str]) -> bool:
    if query == report["id"]:
        return True
    if query in report.get("command_names", []):
        resolved_command = shutil.which(query, path=environment.get("PATH", ""))
        if resolved_command is None:
            return Path(report["installed_path"]).name == query
        return _same_path(Path(resolved_command), Path(report["installed_path"]))
    if "/" in query or query.startswith(".") or query.startswith("~") or query.startswith("$"):
        return _same_path(_expand_path(query, environment), Path(report["installed_path"]))
    return False


def _same_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve(strict=False) == right.expanduser().resolve(strict=False)


def _format_command(value: Any, source_repo: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ArtifactLookupError("manifest commands must be strings")
    return value.format(source_repo=source_repo)
