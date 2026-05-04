from __future__ import annotations

import http.client
import json
import os
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .config import Settings


class MainlineLlmSwitchError(RuntimeError):
    pass


class UnixSocketHttpConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: Path):
        super().__init__("localhost")
        self.socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(self.socket_path))
        self.sock = sock


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


def _docker_request(
    settings: Settings,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    expected_statuses: tuple[int, ...] = (200, 201, 204, 304),
) -> Any:
    if os.name == "nt":
        raise MainlineLlmSwitchError("docker socket switch is only supported from Linux containers")

    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    connection = UnixSocketHttpConnection(settings.mainline_llm_docker_socket_path)
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        response_body = response.read().decode("utf-8", errors="replace")
    finally:
        connection.close()

    if response.status not in expected_statuses:
        detail = _sanitize_output(response_body)
        raise MainlineLlmSwitchError(f"Docker API {method} {path} failed: HTTP {response.status} {detail}")

    if not response_body.strip():
        return None
    try:
        return json.loads(response_body)
    except json.JSONDecodeError:
        return response_body


def _container_path(identifier: str) -> str:
    return quote(identifier, safe="")


def _query_value(value: str) -> str:
    return quote(value, safe="")


def _replace_env(env: list[str], key: str, value: str) -> list[str]:
    prefix = f"{key}="
    replaced = False
    updated: list[str] = []
    for item in env:
        if item.startswith(prefix):
            updated.append(f"{prefix}{value}")
            replaced = True
        else:
            updated.append(item)
    if not replaced:
        updated.append(f"{prefix}{value}")
    return updated


def _build_host_config(inspect_payload: dict[str, Any]) -> dict[str, Any]:
    host_config = inspect_payload.get("HostConfig") or {}
    keys = [
        "AutoRemove",
        "Binds",
        "CapAdd",
        "CapDrop",
        "Dns",
        "DnsOptions",
        "DnsSearch",
        "ExtraHosts",
        "GroupAdd",
        "Init",
        "IpcMode",
        "LogConfig",
        "Memory",
        "MemorySwap",
        "NetworkMode",
        "PortBindings",
        "Privileged",
        "ReadonlyRootfs",
        "RestartPolicy",
        "SecurityOpt",
        "ShmSize",
        "Ulimits",
        "UsernsMode",
    ]
    return {key: host_config[key] for key in keys if key in host_config and host_config[key] not in (None, [], {})}


def _build_networking_config(inspect_payload: dict[str, Any]) -> dict[str, Any]:
    networks = ((inspect_payload.get("NetworkSettings") or {}).get("Networks") or {})
    endpoints: dict[str, dict[str, Any]] = {}
    for network_name, network_data in networks.items():
        endpoint: dict[str, Any] = {}
        aliases = network_data.get("Aliases")
        if aliases:
            endpoint["Aliases"] = aliases
        endpoints[network_name] = endpoint
    return {"EndpointsConfig": endpoints} if endpoints else {}


def _build_container_create_payload(
    inspect_payload: dict[str, Any],
    settings: Settings,
    model: str,
) -> dict[str, Any]:
    config = inspect_payload.get("Config") or {}
    env = _replace_env(list(config.get("Env") or []), "LLM_MODEL", model)
    env = _replace_env(env, "LLM_REASONING_EFFORT", settings.mainline_llm_reasoning_effort)
    env = _replace_env(env, "LLM_THINKING_TYPE", settings.mainline_llm_thinking_type)
    payload: dict[str, Any] = {
        "Image": config.get("Image"),
        "Env": env,
        "Labels": config.get("Labels") or {},
        "HostConfig": _build_host_config(inspect_payload),
    }

    for key in [
        "AttachStderr",
        "AttachStdin",
        "AttachStdout",
        "Cmd",
        "Domainname",
        "Entrypoint",
        "ExposedPorts",
        "Hostname",
        "OpenStdin",
        "StdinOnce",
        "Tty",
        "User",
        "WorkingDir",
    ]:
        if key in config and config[key] is not None:
            payload[key] = config[key]

    networking_config = _build_networking_config(inspect_payload)
    if networking_config:
        payload["NetworkingConfig"] = networking_config
    return payload


def _container_live_env_values(
    settings: Settings,
    container_name: str,
    keys: tuple[str, ...],
) -> dict[str, str]:
    inspect_payload = _docker_request(
        settings,
        "GET",
        f"/containers/{_container_path(container_name)}/json",
    )
    env = (inspect_payload.get("Config") or {}).get("Env") or []
    return {key: _read_env_from_list(env, key) for key in keys}


def _container_live_model(settings: Settings, container_name: str) -> str:
    return _container_live_env_values(settings, container_name, ("LLM_MODEL",))["LLM_MODEL"]


def _wait_container_running(settings: Settings, container_name: str, timeout_seconds: int = 15) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        inspect_payload = _docker_request(
            settings,
            "GET",
            f"/containers/{_container_path(container_name)}/json",
        )
        last_state = inspect_payload.get("State") or {}
        if last_state.get("Running") and not last_state.get("Restarting"):
            return
        time.sleep(0.75)

    status = last_state.get("Status") or "unknown"
    error = last_state.get("Error") or ""
    raise MainlineLlmSwitchError(f"container did not stay running: {status} {error}".strip())


def _read_env_from_list(env: list[str], key: str) -> str:
    prefix = f"{key}="
    for item in env:
        if item.startswith(prefix):
            return item[len(prefix) :]
    return ""


def _remove_container_if_exists(settings: Settings, container_id: str) -> None:
    try:
        _docker_request(
            settings,
            "DELETE",
            f"/containers/{_container_path(container_id)}?v=true&force=true",
            expected_statuses=(204, 404),
        )
    except MainlineLlmSwitchError:
        pass


def _rollback_container(
    settings: Settings,
    *,
    old_id: str,
    old_name: str,
    backup_name: str,
    new_id: str | None,
) -> None:
    if new_id:
        _remove_container_if_exists(settings, new_id)
    try:
        _docker_request(
            settings,
            "POST",
            f"/containers/{_container_path(backup_name)}/rename?name={_query_value(old_name)}",
            expected_statuses=(204,),
        )
        _docker_request(
            settings,
            "POST",
            f"/containers/{_container_path(old_id)}/start",
            expected_statuses=(204, 304),
        )
    except MainlineLlmSwitchError:
        pass


def _recreate_container_with_model(settings: Settings, model: str) -> str:
    container_name = settings.mainline_llm_container_name
    old_payload = _docker_request(
        settings,
        "GET",
        f"/containers/{_container_path(container_name)}/json",
    )
    old_id = old_payload["Id"]
    old_name = str(old_payload.get("Name") or f"/{container_name}").lstrip("/")
    backup_name = f"{old_name}-previous-{int(time.time())}"
    new_id: str | None = None

    try:
        _docker_request(
            settings,
            "POST",
            f"/containers/{_container_path(old_id)}/stop?t=30",
            expected_statuses=(204, 304),
        )
        _docker_request(
            settings,
            "POST",
            f"/containers/{_container_path(old_id)}/rename?name={_query_value(backup_name)}",
            expected_statuses=(204,),
        )
        create_payload = _build_container_create_payload(old_payload, settings, model)
        create_result = _docker_request(
            settings,
            "POST",
            f"/containers/create?name={_query_value(container_name)}",
            body=create_payload,
            expected_statuses=(201,),
        )
        new_id = create_result["Id"]
        _docker_request(
            settings,
            "POST",
            f"/containers/{_container_path(new_id)}/start",
            expected_statuses=(204, 304),
        )
        _wait_container_running(settings, container_name)
    except Exception:
        _rollback_container(
            settings,
            old_id=old_id,
            old_name=old_name,
            backup_name=backup_name,
            new_id=new_id,
        )
        raise

    live_model = _container_live_model(settings, container_name)
    _remove_container_if_exists(settings, backup_name)
    return live_model


def _missing_requirements(settings: Settings) -> list[str]:
    missing: list[str] = []
    if not settings.mainline_llm_env_path.exists():
        missing.append(f"env file: {settings.mainline_llm_env_path}")
    if os.name == "nt":
        missing.append("docker socket switch requires Linux container runtime")
    elif not settings.mainline_llm_docker_socket_path.exists():
        missing.append(f"docker socket: {settings.mainline_llm_docker_socket_path}")
    return missing


def get_mainline_llm_status(settings: Settings) -> dict[str, Any]:
    configured_model = _read_env_value(settings.mainline_llm_env_path, "LLM_MODEL")
    configured_reasoning_effort = (
        _read_env_value(settings.mainline_llm_env_path, "LLM_REASONING_EFFORT")
        or settings.mainline_llm_reasoning_effort
    )
    configured_thinking_type = (
        _read_env_value(settings.mainline_llm_env_path, "LLM_THINKING_TYPE")
        or settings.mainline_llm_thinking_type
    )
    missing = _missing_requirements(settings)
    live_model = ""
    live_reasoning_effort = ""
    live_thinking_type = ""
    live_model_error = ""
    if not missing:
        try:
            live_env = _container_live_env_values(
                settings,
                settings.mainline_llm_container_name,
                ("LLM_MODEL", "LLM_REASONING_EFFORT", "LLM_THINKING_TYPE"),
            )
            live_model = live_env["LLM_MODEL"]
            live_reasoning_effort = live_env["LLM_REASONING_EFFORT"]
            live_thinking_type = live_env["LLM_THINKING_TYPE"]
        except MainlineLlmSwitchError as exc:
            live_model_error = str(exc)
    target_model = settings.mainline_llm_target_model
    allowed_models = list(settings.mainline_llm_allowed_models)
    return {
        "configured_model": configured_model,
        "live_model": live_model,
        "configured_reasoning_effort": configured_reasoning_effort,
        "live_reasoning_effort": live_reasoning_effort,
        "configured_thinking_type": configured_thinking_type,
        "live_thinking_type": live_thinking_type,
        "live_model_error": live_model_error,
        "target_model": target_model,
        "allowed_models": allowed_models,
        "env_path": str(settings.mainline_llm_env_path),
        "container_name": settings.mainline_llm_container_name,
        "docker_socket_path": str(settings.mainline_llm_docker_socket_path),
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
        _write_env_value(
            settings.mainline_llm_env_path,
            "LLM_REASONING_EFFORT",
            settings.mainline_llm_reasoning_effort,
        )
        _write_env_value(
            settings.mainline_llm_env_path,
            "LLM_THINKING_TYPE",
            settings.mainline_llm_thinking_type,
        )
        live_model = _recreate_container_with_model(settings, model)
    except Exception:
        settings.mainline_llm_env_path.write_text(original_text, encoding="utf-8")
        raise

    return {
        "ok": True,
        "previous_model": previous_model,
        "configured_model": _read_env_value(settings.mainline_llm_env_path, "LLM_MODEL"),
        "live_model": live_model,
        "configured_reasoning_effort": _read_env_value(
            settings.mainline_llm_env_path,
            "LLM_REASONING_EFFORT",
        ),
        "configured_thinking_type": _read_env_value(
            settings.mainline_llm_env_path,
            "LLM_THINKING_TYPE",
        ),
        "target_model": model,
        "env_path": str(settings.mainline_llm_env_path),
        "container_name": settings.mainline_llm_container_name,
    }
