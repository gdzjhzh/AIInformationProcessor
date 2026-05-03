from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import Settings


class MainlineLlmSwitchError(RuntimeError):
    pass


def _read_env_text(path: Path) -> str:
    if not path.exists():
        raise MainlineLlmSwitchError(f"env file not found: {path}")
    return path.read_text(encoding="utf-8")


def _read_env_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def _write_env_value(path: Path, key: str, value: str) -> None:
    original = _read_env_text(path)
    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines()
    replaced = False
    updated: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("#") and "=" in stripped:
            name, _old_value = stripped.split("=", 1)
            if name.strip() == key:
                updated.append(f"{key}={value}")
                replaced = True
                continue
        updated.append(line)

    if not replaced:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(f"{key}={value}")

    trailing_newline = newline if original.endswith(("\n", "\r\n")) else ""
    path.write_text(newline.join(updated) + trailing_newline, encoding="utf-8")


def _sanitize_output(value: str, limit: int = 1200) -> str:
    normalized = value.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _docker_command(settings: Settings, *args: str) -> list[str]:
    return [settings.mainline_llm_docker_command, *args]


def _compose_command(settings: Settings, *args: str) -> list[str]:
    return _docker_command(
        settings,
        "compose",
        "--env-file",
        str(settings.mainline_llm_env_path),
        "-f",
        str(settings.mainline_llm_compose_file),
        *args,
    )


def _run_command(settings: Settings, command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=settings.mainline_llm_compose_workdir,
            check=True,
            capture_output=True,
            text=True,
            timeout=settings.mainline_llm_restart_timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise MainlineLlmSwitchError(
            f"docker command not found: {settings.mainline_llm_docker_command}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MainlineLlmSwitchError(
            f"docker compose timed out after {settings.mainline_llm_restart_timeout_seconds}s"
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = _sanitize_output((exc.stderr or "") + "\n" + (exc.stdout or ""))
        raise MainlineLlmSwitchError(f"docker compose failed: {details}") from exc


def _verify_live_model(settings: Settings) -> str:
    try:
        result = _run_command(settings, _compose_command(settings, "exec", "-T", "n8n", "printenv", "LLM_MODEL"))
    except MainlineLlmSwitchError:
        return ""
    return result.stdout.strip()


def _missing_requirements(settings: Settings) -> list[str]:
    missing: list[str] = []
    if not settings.mainline_llm_env_path.exists():
        missing.append(f"env file: {settings.mainline_llm_env_path}")
    if not settings.mainline_llm_compose_file.exists():
        missing.append(f"compose file: {settings.mainline_llm_compose_file}")
    if not settings.mainline_llm_compose_workdir.exists():
        missing.append(f"compose workdir: {settings.mainline_llm_compose_workdir}")
    if shutil.which(settings.mainline_llm_docker_command) is None:
        missing.append(f"docker command: {settings.mainline_llm_docker_command}")
    docker_socket = os.getenv("DOCKER_HOST", "").strip()
    if not docker_socket and not Path("/var/run/docker.sock").exists() and os.name != "nt":
        missing.append("docker socket: /var/run/docker.sock")
    return missing


def get_mainline_llm_status(settings: Settings) -> dict[str, Any]:
    configured_model = _read_env_value(settings.mainline_llm_env_path, "LLM_MODEL")
    missing = _missing_requirements(settings)
    target_model = settings.mainline_llm_target_model
    allowed_models = list(settings.mainline_llm_allowed_models)
    return {
        "configured_model": configured_model,
        "target_model": target_model,
        "allowed_models": allowed_models,
        "env_path": str(settings.mainline_llm_env_path),
        "compose_file": str(settings.mainline_llm_compose_file),
        "compose_workdir": str(settings.mainline_llm_compose_workdir),
        "switch_available": not missing and target_model in settings.mainline_llm_allowed_models,
        "missing_requirements": missing,
    }


def switch_mainline_llm_model(settings: Settings, target_model: str | None = None) -> dict[str, Any]:
    model = (target_model or settings.mainline_llm_target_model).strip()
    if model not in settings.mainline_llm_allowed_models:
        allowed = ", ".join(settings.mainline_llm_allowed_models)
        raise MainlineLlmSwitchError(f"model is not allowed: {model}; allowed: {allowed}")

    missing = _missing_requirements(settings)
    if missing:
        raise MainlineLlmSwitchError("missing requirements: " + "; ".join(missing))

    original_text = _read_env_text(settings.mainline_llm_env_path)
    previous_model = _read_env_value(settings.mainline_llm_env_path, "LLM_MODEL")

    try:
        _write_env_value(settings.mainline_llm_env_path, "LLM_MODEL", model)
        restart_result = _run_command(
            settings,
            _compose_command(settings, "up", "-d", "--no-deps", "n8n"),
        )
    except Exception:
        settings.mainline_llm_env_path.write_text(original_text, encoding="utf-8")
        raise

    live_model = _verify_live_model(settings)
    return {
        "ok": True,
        "previous_model": previous_model,
        "configured_model": _read_env_value(settings.mainline_llm_env_path, "LLM_MODEL"),
        "live_model": live_model,
        "target_model": model,
        "env_path": str(settings.mainline_llm_env_path),
        "restart_stdout": _sanitize_output(restart_result.stdout),
        "restart_stderr": _sanitize_output(restart_result.stderr),
    }
