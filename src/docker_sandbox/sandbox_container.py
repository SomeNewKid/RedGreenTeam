"""Run Sandbox Agent inside disposable Docker containers."""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Set
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath
from typing import IO, Any, TextIO

from .container_guard import (
    CONTAINER_MARKER_ENVIRONMENT_VARIABLE,
    CONTAINER_MARKER_VALUE,
)
from .models import (
    AgentContainerRunResult,
    AgentImageConfiguration,
    AgentSocketForward,
    BrowserDebuggingProfile,
    BrowserSurfaceProfile,
    DockerConfiguration,
    DockerRunResult,
    EnvironmentVariablePolicy,
    HAProxyConfiguration,
    NetworkDnsPolicy,
    NetworkGatewayProfile,
    SandboxRunTarget,
    SeccompProfile,
    SocketMount,
)
from .sandbox_plan import (
    ResolvedAgentPlan,
    ResolvedSandboxPlan,
    build_haproxy_acl_configuration,
    build_network_create_command,
    build_sandbox_plan,
    build_squid_acl_configuration,
    save_resolved_sandbox_plan,
)

_DOCKER_EXECUTABLE = "docker"
_REMOTE_OUTPUT_DIRECTORY = "/sandbox-output"
_REMOTE_SHARED_DIRECTORY = "/sandbox-shared"
_REMOTE_LANDLOCK_POLICY_PATH = f"{_REMOTE_OUTPUT_DIRECTORY}/landlock-policy.json"
_REMOTE_SOURCE_DIRECTORY = "/sandbox-source/src"
_SHARED_VOLUME_CAPABILITY = "shared_volume"
_SHARED_DIRECTORY_NAME = "shared"
_SHARED_DIRECTORY_ENVIRONMENT_VARIABLE = "SANDBOX_SHARED_DIR"
_CONTAINER_NAME_PREFIX = "sandbox-agent-run"
_GATEWAY_CONTAINER_NAME_PREFIX = "sandbox-agent-gateway"
_NETWORK_NAME_PREFIX = "sandbox-agent-net"
_READONLY_DENIED_SOURCE_DIRECTORY = "readonly-denied"
_SQUID_CONFIGURATION_FILE_NAME = "squid.conf"
_SECCOMP_PROFILE_FILE_NAME = "seccomp-profile.json"
_GATEWAY_START_RESULTS_FILE_NAME = "gateway-start-results.json"
_GATEWAY_LOG_FILE_NAME = "gateway-logs.json"
_MCP_SIDECAR_START_RESULTS_FILE_NAME = "mcp-sidecar-start-results.json"
_MCP_SIDECAR_LOG_FILE_NAME = "mcp-sidecar-logs.json"
_MCP_SIDECAR_STDOUT_FILE_NAME = "mcp-sidecar-stdout.txt"
_MCP_SIDECAR_STDERR_FILE_NAME = "mcp-sidecar-stderr.txt"
_MCP_SIDECAR_METADATA_FILE_NAME = "mcp-sidecar-metadata.json"
_MCP_SIDECAR_TOOL_CALLS_FILE_NAME = "mcp-sidecar-tool-calls.jsonl"
_MCP_SIDECAR_EXPOSURE_FILE_NAME = "mcp-sidecar-exposure.json"
_JINA_READER_START_RESULTS_FILE_NAME = "jina-reader-start-results.json"
_JINA_READER_LOG_FILE_NAME = "jina-reader-logs.json"
_JINA_READER_STDOUT_FILE_NAME = "jina-reader-stdout.txt"
_JINA_READER_STDERR_FILE_NAME = "jina-reader-stderr.txt"
_JINA_READER_METADATA_FILE_NAME = "jina-reader-metadata.json"
_JINA_READER_READINESS_RESULTS_FILE_NAME = "jina-reader-readiness-results.json"
_CODE_SIDECAR_START_RESULTS_FILE_NAME = "code-sidecar-start-results.json"
_CODE_SIDECAR_LOG_FILE_NAME = "code-sidecar-logs.json"
_CODE_SIDECAR_STDOUT_FILE_NAME = "code-sidecar-stdout.txt"
_CODE_SIDECAR_STDERR_FILE_NAME = "code-sidecar-stderr.txt"
_CODE_SIDECAR_METADATA_FILE_NAME = "code-sidecar-metadata.json"
_HAPROXY_CONFIGURATION_FILE_NAME = "haproxy.cfg"
_HAPROXY_SIDECAR_START_RESULTS_FILE_NAME = "haproxy-sidecar-start-results.json"
_HAPROXY_SIDECAR_LOG_FILE_NAME = "haproxy-sidecar-logs.json"
_HAPROXY_SIDECAR_STDOUT_FILE_NAME = "haproxy-sidecar-stdout.txt"
_HAPROXY_SIDECAR_STDERR_FILE_NAME = "haproxy-sidecar-stderr.txt"
_HAPROXY_SIDECAR_METADATA_FILE_NAME = "haproxy-sidecar-metadata.json"
_OLLAMA_SIDECAR_START_RESULTS_FILE_NAME = "ollama-sidecar-start-results.json"
_OLLAMA_SIDECAR_LOG_FILE_NAME = "ollama-sidecar-logs.json"
_OLLAMA_SIDECAR_STDOUT_FILE_NAME = "ollama-sidecar-stdout.txt"
_OLLAMA_SIDECAR_STDERR_FILE_NAME = "ollama-sidecar-stderr.txt"
_OLLAMA_SIDECAR_METADATA_FILE_NAME = "ollama-sidecar-metadata.json"
_OLLAMA_SIDECAR_READINESS_RESULTS_FILE_NAME = "ollama-sidecar-readiness-results.json"
_DENIED_EXECUTABLE_SOURCE_DIRECTORY = "denied-executables"
_READONLY_PERSISTENCE_SOURCE_DIRECTORY = "readonly-persistence"
_DESKTOP_AUTOMATION_ENVIRONMENT_NAMES = (
    "DBUS_SESSION_BUS_ADDRESS",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
)
_DESKTOP_AUTOMATION_EXECUTABLE_PATHS = (
    "/usr/bin/busctl",
    "/usr/bin/dbus-send",
    "/usr/bin/gdbus",
    "/usr/bin/qdbus",
    "/usr/bin/wmctrl",
    "/usr/bin/xdotool",
)
_ALLOWED_FILE_CONTENT = "This is a test file for the allowed directory."
_DENIED_FILE_CONTENT = "This is a test file for the denied directory."
_HIDDEN_ALLOWED_FILE_CONTENT = "This is a hidden file."
_HIDDEN_DENIED_FILE_CONTENT = "This is a hidden file in the denied directory."
_GIT_REMOTE_URL = "https://github.com/SomeNewKid/ScratchpadOne.git"
_LOCAL_ENVIRONMENT_VALUE = "[local]"
_SANDBOX_TESTER_ENVIRONMENT_VARIABLES = {
    "OPENAI_API_KEY": _LOCAL_ENVIRONMENT_VALUE,
}
_MCP_SIDECAR_IMAGE_NAME = "mcp-sidecar:dev"
_MCP_SIDECAR_CONTAINER_NAME_PREFIX = "mcp-sidecar"
_MCP_SIDECAR_ALIAS = "mcp-sidecar"
_MCP_SIDECAR_PORT = 8000
_MCP_SIDECAR_URL_ENVIRONMENT_VARIABLE = "MCP_SIDECAR_URL"
_MCP_SIDECAR_AUDIT_LOG_PATH_ENVIRONMENT_VARIABLE = "MCP_SIDECAR_AUDIT_LOG_PATH"
_MCP_SIDECAR_EXPOSURE_PATH_ENVIRONMENT_VARIABLE = "MCP_SIDECAR_EXPOSURE_PATH"
_MCP_SIDECAR_OUTPUT_DIRECTORY = "/mcp-sidecar-output"
_MCP_SIDECAR_CONFIG_DIRECTORY = "/mcp-sidecar-config"
_MARIADB_HOST_ENVIRONMENT_VARIABLE = "MARIADB_HOST"
_MARIADB_PORT_ENVIRONMENT_VARIABLE = "MARIADB_PORT"
_MARIADB_DATABASE_ENVIRONMENT_VARIABLE = "MARIADB_DATABASE"
_MARIADB_CREDENTIALS_ENVIRONMENT_VARIABLE = "SANDBOX_TESTER_MARIADB_CREDENTIALS"
_MARIADB_DATABASE_NAME = "agent_allowed"
_MARIADB_DEFAULT_PORT = 3306
_OPENAI_API_KEY_ENVIRONMENT_VARIABLE = "OPENAI_API_KEY"
_OPENAI_BASE_URL_ENVIRONMENT_VARIABLE = "OPENAI_BASE_URL"
_OPENAI_CAPABILITY = "openai"
_OPENAI_AGENTS_CAPABILITY = "openai_agents"
_OPENAI_PACKAGE = "openai==2.45.0"
_JINA_READER_IMAGE_NAME = "ghcr.io/jina-ai/reader:oss"
_JINA_READER_CONTAINER_NAME_PREFIX = "jina-reader"
_JINA_READER_ALIAS = "jina-reader"
_JINA_READER_PORT = 8081
_JINA_READER_URL_ENVIRONMENT_VARIABLE = "JINA_READER_URL"
_JINA_READER_READINESS_URL = "https://example.com"
_JINA_READER_READINESS_INTERVALS_SECONDS = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)
_JINA_READER_CAPABILITY = "jina_reader"
_CODE_EXECUTION_CAPABILITY = "code_execution"
_HAPROXY_CAPABILITY = "haproxy"
_OLLAMA_CAPABILITY = "ollama"
_OLLAMA_SIDECAR_CONTAINER_NAME_PREFIX = "ollama-sidecar"
_OLLAMA_SIDECAR_ALIAS = "ollama-sidecar"
_OLLAMA_SIDECAR_PORT = 11434
_OLLAMA_BASE_URL_ENVIRONMENT_VARIABLE = "OLLAMA_BASE_URL"
_OLLAMA_MODEL_ENVIRONMENT_VARIABLE = "OLLAMA_MODEL"
_OLLAMA_OPENAI_API_KEY = "ollama"
_OLLAMA_READINESS_INTERVALS_SECONDS = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)
_A2A_AGENT_PORT = 8080
_A2A_READINESS_INTERVALS_SECONDS = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)
_CODE_SIDECAR_IMAGE_NAME = "code-sidecar:dev"
_CODE_SIDECAR_CONTAINER_NAME_PREFIX = "code-sidecar"
_CODE_SIDECAR_ALIAS = "code-sidecar"
_CODE_SIDECAR_PORT = 8090
_CODE_SIDECAR_URL_ENVIRONMENT_VARIABLE = "CODE_SIDECAR_URL"
_CODE_SIDECAR_OUTPUT_DIRECTORY_ENVIRONMENT_VARIABLE = "CODE_SIDECAR_OUTPUT_DIRECTORY"
_CODE_SIDECAR_OUTPUT_DIRECTORY = "/code-sidecar-output"
_HAPROXY_IMAGE_NAME = "haproxy:latest"
_HAPROXY_SIDECAR_CONTAINER_NAME_PREFIX = "haproxy-sidecar"
_HAPROXY_SIDECAR_ALIAS = "haproxy-sidecar"
_HAPROXY_CONFIGURATION_PATH = "/usr/local/etc/haproxy/haproxy.cfg"
_OLLAMA_BASE_IMAGE_NAME = "ollama/ollama:latest"
_OLLAMA_GENERATED_DIRECTORY = "ollama-sidecar"


@dataclass(frozen=True)
class _InteractiveProcessResult:
    returncode: int
    stdout: str
    stderr: str


def run_sandbox_container(
    configuration: DockerConfiguration,
    verbose: bool = False,
    serialize_evidence: bool = False,
) -> DockerRunResult:
    """Run Sandbox Agent in a disposable Docker container."""
    timestamp = dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    run_id = f"run-{timestamp}"
    run_directory = configuration.base_directory / "runs" / run_id
    run_directory.mkdir(parents=True, exist_ok=True)
    resolved_plan = _resolve_sandbox_plan(configuration, run_id)
    if resolved_plan is not None:
        save_resolved_sandbox_plan(resolved_plan, run_directory)
        configuration = replace(configuration, resolved_sandbox_plan=resolved_plan)
    _write_configuration_artifacts(configuration, run_directory)
    container_name = _build_agent_container_name(configuration, timestamp)
    gateway_container_name = _build_gateway_container_name(configuration, timestamp)
    mcp_sidecar_container_name = _build_mcp_sidecar_container_name(
        configuration,
        timestamp,
    )
    jina_reader_container_name = _build_jina_reader_container_name(
        configuration,
        timestamp,
    )
    code_sidecar_container_name = _build_code_sidecar_container_name(
        configuration,
        timestamp,
    )
    haproxy_sidecar_container_name = _build_haproxy_sidecar_container_name(
        configuration,
        timestamp,
    )
    ollama_sidecar_container_name = _build_ollama_sidecar_container_name(
        configuration,
        timestamp,
    )
    network_name = _build_network_name(configuration, timestamp)
    remote_run_directory = _build_remote_run_directory(configuration, run_id)
    allowed_directory = _build_allowed_directory(configuration, remote_run_directory)
    denied_directory = _build_denied_directory(configuration, remote_run_directory)
    _prepare_readonly_denied_directory(configuration, run_directory)
    _prepare_readonly_persistence_directories(configuration, run_directory)
    _prepare_denied_executable_stubs(configuration, run_directory)
    _write_landlock_policy(configuration, run_directory)
    _write_seccomp_profile(configuration, run_directory)
    config_data = _build_config_data(
        remote_run_directory,
        allowed_directory,
        denied_directory,
        configuration.guest_user,
        _get_container_ssh_agent_socket(configuration),
        configuration.profile.browser_debugging,
        configuration.profile.browser_surface,
        _get_mounted_shared_directory(configuration),
    )
    _write_squid_configuration(configuration, run_directory, config_data)
    _write_mcp_sidecar_exposure(configuration, run_directory)
    _write_haproxy_configuration(configuration, run_directory)
    config_path = run_directory / "config.json"
    config_json = json.dumps(config_data, indent=2)
    config_path.write_text(f"{config_json}\n", encoding="utf-8")
    configured_environment_variables = dict(configuration.environment_variables)
    environment_variables = _resolve_environment_variables(
        configured_environment_variables,
    )
    gateway_commands, gateway_ip_address = _start_network_gateway(
        configuration,
        run_directory,
        network_name,
        gateway_container_name,
    )
    jina_reader_commands = _start_jina_reader(
        configuration,
        run_directory,
        network_name,
        jina_reader_container_name,
    )
    _wait_for_jina_reader_ready(
        configuration,
        run_directory,
        network_name,
        jina_reader_container_name,
    )
    code_sidecar_commands = _start_code_sidecar(
        configuration,
        run_directory,
        network_name,
        code_sidecar_container_name,
    )
    haproxy_sidecar_commands = _start_haproxy_sidecar(
        configuration,
        run_directory,
        network_name,
        haproxy_sidecar_container_name,
    )
    ollama_sidecar_commands = _start_ollama_sidecar(
        configuration,
        run_directory,
        network_name,
        ollama_sidecar_container_name,
    )
    _wait_for_ollama_sidecar_ready(
        configuration,
        run_directory,
        network_name,
        ollama_sidecar_container_name,
    )
    mcp_sidecar_commands = _start_mcp_sidecar(
        configuration,
        run_directory,
        network_name,
        mcp_sidecar_container_name,
    )
    completed, agent_results = _run_agent_containers(
        configuration=configuration,
        run_directory=run_directory,
        container_name=container_name,
        network_name=network_name,
        remote_run_directory=remote_run_directory,
        allowed_directory=allowed_directory,
        denied_directory=denied_directory,
        environment_variables=environment_variables,
        gateway_ip_address=gateway_ip_address,
        local_environment_variable_names=configuration.local_environment_variable_names,
        verbose=verbose,
        serialize_evidence=serialize_evidence,
    )
    _write_mcp_sidecar_logs(configuration, run_directory, mcp_sidecar_container_name)
    _write_jina_reader_logs(configuration, run_directory, jina_reader_container_name)
    _write_code_sidecar_logs(configuration, run_directory, code_sidecar_container_name)
    _write_haproxy_sidecar_logs(
        configuration,
        run_directory,
        haproxy_sidecar_container_name,
    )
    _write_ollama_sidecar_logs(
        configuration,
        run_directory,
        ollama_sidecar_container_name,
    )
    _write_gateway_logs(configuration, run_directory, gateway_container_name)
    _delete_readonly_denied_directory(configuration, run_directory)
    _delete_readonly_persistence_directory(configuration, run_directory)
    _delete_denied_executable_directory(configuration, run_directory)
    command = agent_results[0].command
    remove_command = agent_results[0].remove_command
    gateway_cleanup_commands = _build_gateway_cleanup_commands(
        configuration,
        network_name,
        gateway_container_name,
    )
    mcp_sidecar_cleanup_commands = _build_mcp_sidecar_cleanup_commands(
        configuration,
        mcp_sidecar_container_name,
    )
    jina_reader_cleanup_commands = _build_jina_reader_cleanup_commands(
        configuration,
        jina_reader_container_name,
    )
    code_sidecar_cleanup_commands = _build_code_sidecar_cleanup_commands(
        configuration,
        code_sidecar_container_name,
    )
    haproxy_sidecar_cleanup_commands = _build_haproxy_sidecar_cleanup_commands(
        configuration,
        haproxy_sidecar_container_name,
    )
    ollama_sidecar_cleanup_commands = _build_ollama_sidecar_cleanup_commands(
        configuration,
        ollama_sidecar_container_name,
    )

    return DockerRunResult(
        image_name=configuration.profile.image_name,
        profile_name=configuration.profile.name,
        container_name=container_name,
        run_directory=run_directory,
        command=command,
        remove_command=remove_command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        agent_results=agent_results,
        network_name=network_name,
        gateway_container_name=gateway_container_name,
        gateway_ip_address=gateway_ip_address,
        gateway_commands=gateway_commands,
        gateway_cleanup_commands=gateway_cleanup_commands,
        mcp_sidecar_container_name=mcp_sidecar_container_name,
        mcp_sidecar_commands=mcp_sidecar_commands,
        mcp_sidecar_cleanup_commands=mcp_sidecar_cleanup_commands,
        jina_reader_container_name=jina_reader_container_name,
        jina_reader_commands=jina_reader_commands,
        jina_reader_cleanup_commands=jina_reader_cleanup_commands,
        code_sidecar_container_name=code_sidecar_container_name,
        code_sidecar_commands=code_sidecar_commands,
        code_sidecar_cleanup_commands=code_sidecar_cleanup_commands,
        haproxy_sidecar_container_name=haproxy_sidecar_container_name,
        haproxy_sidecar_commands=haproxy_sidecar_commands,
        haproxy_sidecar_cleanup_commands=haproxy_sidecar_cleanup_commands,
        ollama_sidecar_container_name=ollama_sidecar_container_name,
        ollama_sidecar_commands=ollama_sidecar_commands,
        ollama_sidecar_cleanup_commands=ollama_sidecar_cleanup_commands,
    )


def _write_configuration_artifacts(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if configuration.generated_dockerfile is not None:
        dockerfile_text = configuration.generated_dockerfile.rstrip()
        (run_directory / "Dockerfile").write_text(
            f"{dockerfile_text}\n",
            encoding="utf-8",
        )

    if configuration.resolved_spec is not None:
        resolved_spec_json = json.dumps(configuration.resolved_spec, indent=2)
        (run_directory / "sandbox-spec.json").write_text(
            f"{resolved_spec_json}\n",
            encoding="utf-8",
        )

    resolved_profile_json = json.dumps(
        _json_safe(asdict(configuration.profile)),
        indent=2,
    )
    (run_directory / "resolved-profile.json").write_text(
        f"{resolved_profile_json}\n",
        encoding="utf-8",
    )


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _resolve_sandbox_plan(
    configuration: DockerConfiguration,
    run_id: str,
) -> ResolvedSandboxPlan | None:
    if configuration.sandbox_run_spec is None:
        return None
    if not configuration.agent_specs:
        return None

    return build_sandbox_plan(
        configuration.sandbox_run_spec,
        configuration.agent_specs,
        run_id,
    )


def _run_agent_containers(
    configuration: DockerConfiguration,
    run_directory: Path,
    container_name: str,
    network_name: str | None,
    remote_run_directory: str,
    allowed_directory: str,
    denied_directory: str,
    environment_variables: dict[str, str],
    gateway_ip_address: str | None,
    local_environment_variable_names: Set[str],
    verbose: bool,
    serialize_evidence: bool,
) -> tuple[_InteractiveProcessResult, tuple[AgentContainerRunResult, ...]]:
    plan = configuration.resolved_sandbox_plan
    if plan is None:
        command = _build_docker_run_command(
            configuration=configuration,
            run_directory=run_directory,
            container_name=container_name,
            remote_run_directory=remote_run_directory,
            network_name=network_name,
            allowed_directory=allowed_directory,
            denied_directory=denied_directory,
            environment_variables=environment_variables,
            gateway_ip_address=gateway_ip_address,
            local_environment_variable_names=local_environment_variable_names,
            verbose=verbose,
            serialize_evidence=serialize_evidence,
        )
        completed = _run_interactive_command(command)
        result = AgentContainerRunResult(
            agent_id="agent",
            container_name=container_name,
            output_directory=run_directory,
            command=command,
            remove_command=_build_docker_remove_command(container_name),
            exit_code=completed.returncode,
        )
        return completed, (result,)

    completed_results: list[_InteractiveProcessResult] = []
    agent_results: list[AgentContainerRunResult] = []
    agents_directory = run_directory / "agents"
    if plan.execution.mode == "entry_agent":
        return _run_entry_agent_containers(
            configuration=configuration,
            run_directory=run_directory,
            agents_directory=agents_directory,
            network_name=network_name,
            remote_run_directory=remote_run_directory,
            environment_variables=environment_variables,
            gateway_ip_address=gateway_ip_address,
            local_environment_variable_names=local_environment_variable_names,
            verbose=verbose,
            serialize_evidence=serialize_evidence,
        )

    for agent_plan in plan.agents:
        agent_output_directory = agents_directory / agent_plan.agent_id
        _prepare_agent_output_directory(run_directory, agent_output_directory)
        _write_agent_landlock_policy(
            configuration,
            agent_output_directory,
            agent_plan,
        )
        agent_remote_run_directory = _build_agent_remote_run_directory(
            remote_run_directory,
            agent_plan,
        )
        command = _build_docker_run_command(
            configuration=configuration,
            run_directory=run_directory,
            output_directory=agent_output_directory,
            container_name=agent_plan.container_name,
            remote_run_directory=agent_remote_run_directory,
            network_name=network_name,
            allowed_directory=_build_allowed_directory(
                configuration,
                agent_remote_run_directory,
            ),
            denied_directory=_build_denied_directory(
                configuration,
                agent_remote_run_directory,
            ),
            environment_variables=environment_variables,
            gateway_ip_address=gateway_ip_address,
            local_environment_variable_names=local_environment_variable_names,
            verbose=verbose,
            serialize_evidence=serialize_evidence,
            agent_plan=agent_plan,
        )
        completed = _run_interactive_command(command)
        completed_results.append(completed)
        agent_result = AgentContainerRunResult(
            agent_id=agent_plan.agent_id,
            container_name=agent_plan.container_name,
            output_directory=agent_output_directory,
            command=command,
            remove_command=_build_docker_remove_command(agent_plan.container_name),
            exit_code=completed.returncode,
        )
        agent_results.append(agent_result)
        _write_agent_run_artifacts(agent_output_directory, agent_result, completed)

    return _combine_agent_process_results(completed_results), tuple(agent_results)


def _run_entry_agent_containers(
    configuration: DockerConfiguration,
    run_directory: Path,
    agents_directory: Path,
    network_name: str | None,
    remote_run_directory: str,
    environment_variables: dict[str, str],
    gateway_ip_address: str | None,
    local_environment_variable_names: Set[str],
    verbose: bool,
    serialize_evidence: bool,
) -> tuple[_InteractiveProcessResult, tuple[AgentContainerRunResult, ...]]:
    plan = configuration.resolved_sandbox_plan
    if plan is None or plan.execution.entry_agent is None:
        raise RuntimeError("entry_agent execution requires a resolved sandbox plan.")

    agent_by_id = {agent.agent_id: agent for agent in plan.agents}
    entry_agent = agent_by_id[plan.execution.entry_agent]
    supporting_agents = tuple(
        agent for agent in plan.agents if agent.agent_id != entry_agent.agent_id
    )
    supporting_results = [
        _start_supporting_a2a_agent(
            configuration=configuration,
            run_directory=run_directory,
            agents_directory=agents_directory,
            network_name=network_name,
            remote_run_directory=remote_run_directory,
            environment_variables=environment_variables,
            gateway_ip_address=gateway_ip_address,
            local_environment_variable_names=local_environment_variable_names,
            agent_plan=agent_plan,
        )
        for agent_plan in supporting_agents
    ]
    failed_supporting_results = [
        result for result in supporting_results if result.exit_code != 0
    ]
    if failed_supporting_results:
        completed = _InteractiveProcessResult(
            returncode=failed_supporting_results[0].exit_code,
            stdout="",
            stderr="Supporting A2A agent failed to start.",
        )
        return completed, tuple(supporting_results)

    completed, entry_result = _run_entry_agent_container(
        configuration=configuration,
        run_directory=run_directory,
        agents_directory=agents_directory,
        network_name=network_name,
        remote_run_directory=remote_run_directory,
        environment_variables=environment_variables,
        gateway_ip_address=gateway_ip_address,
        local_environment_variable_names=local_environment_variable_names,
        verbose=verbose,
        serialize_evidence=serialize_evidence,
        agent_plan=entry_agent,
    )
    _write_supporting_a2a_agent_logs(supporting_results)
    return completed, (*supporting_results, entry_result)


def _start_supporting_a2a_agent(
    configuration: DockerConfiguration,
    run_directory: Path,
    agents_directory: Path,
    network_name: str | None,
    remote_run_directory: str,
    environment_variables: dict[str, str],
    gateway_ip_address: str | None,
    local_environment_variable_names: Set[str],
    agent_plan: ResolvedAgentPlan,
) -> AgentContainerRunResult:
    agent_output_directory = agents_directory / agent_plan.agent_id
    _prepare_agent_output_directory(run_directory, agent_output_directory)
    _write_agent_landlock_policy(configuration, agent_output_directory, agent_plan)
    agent_remote_run_directory = _build_agent_remote_run_directory(
        remote_run_directory,
        agent_plan,
    )
    network_alias = _build_agent_network_alias(agent_plan)
    bind_host = agent_plan.ip_address or "127.0.0.1"
    command = _build_docker_run_command(
        configuration=configuration,
        run_directory=run_directory,
        output_directory=agent_output_directory,
        container_name=agent_plan.container_name,
        remote_run_directory=agent_remote_run_directory,
        network_name=network_name,
        allowed_directory=_build_allowed_directory(
            configuration, agent_remote_run_directory
        ),
        denied_directory=_build_denied_directory(
            configuration, agent_remote_run_directory
        ),
        environment_variables=environment_variables,
        gateway_ip_address=gateway_ip_address,
        local_environment_variable_names=local_environment_variable_names,
        agent_plan=agent_plan,
        detached=True,
        network_alias=network_alias,
        module_arguments=(
            "--serve",
            "--host",
            bind_host,
            "--port",
            str(_A2A_AGENT_PORT),
            "--public-base-url",
            f"http://{network_alias}:{_A2A_AGENT_PORT}",
        ),
    )
    completed = _run_captured_command(command)
    if completed.returncode == 0:
        readiness = _wait_for_a2a_agent_ready(agent_plan.container_name, bind_host)
        if readiness.returncode != 0:
            completed = readiness

    agent_result = AgentContainerRunResult(
        agent_id=agent_plan.agent_id,
        container_name=agent_plan.container_name,
        output_directory=agent_output_directory,
        command=command,
        remove_command=_build_docker_remove_command(agent_plan.container_name),
        exit_code=completed.returncode,
    )
    _write_agent_run_artifacts(agent_output_directory, agent_result, completed)
    return agent_result


def _run_entry_agent_container(
    configuration: DockerConfiguration,
    run_directory: Path,
    agents_directory: Path,
    network_name: str | None,
    remote_run_directory: str,
    environment_variables: dict[str, str],
    gateway_ip_address: str | None,
    local_environment_variable_names: Set[str],
    verbose: bool,
    serialize_evidence: bool,
    agent_plan: ResolvedAgentPlan,
) -> tuple[_InteractiveProcessResult, AgentContainerRunResult]:
    agent_output_directory = agents_directory / agent_plan.agent_id
    _prepare_agent_output_directory(run_directory, agent_output_directory)
    _write_agent_landlock_policy(configuration, agent_output_directory, agent_plan)
    agent_remote_run_directory = _build_agent_remote_run_directory(
        remote_run_directory,
        agent_plan,
    )
    command = _build_docker_run_command(
        configuration=configuration,
        run_directory=run_directory,
        output_directory=agent_output_directory,
        container_name=agent_plan.container_name,
        remote_run_directory=agent_remote_run_directory,
        network_name=network_name,
        allowed_directory=_build_allowed_directory(
            configuration, agent_remote_run_directory
        ),
        denied_directory=_build_denied_directory(
            configuration, agent_remote_run_directory
        ),
        environment_variables=environment_variables,
        gateway_ip_address=gateway_ip_address,
        local_environment_variable_names=local_environment_variable_names,
        verbose=verbose,
        serialize_evidence=serialize_evidence,
        agent_plan=agent_plan,
        network_alias=_build_agent_network_alias(agent_plan),
    )
    completed = _run_interactive_command(command)
    agent_result = AgentContainerRunResult(
        agent_id=agent_plan.agent_id,
        container_name=agent_plan.container_name,
        output_directory=agent_output_directory,
        command=command,
        remove_command=_build_docker_remove_command(agent_plan.container_name),
        exit_code=completed.returncode,
    )
    _write_agent_run_artifacts(agent_output_directory, agent_result, completed)
    return completed, agent_result


def _write_supporting_a2a_agent_logs(
    agent_results: list[AgentContainerRunResult],
) -> None:
    for agent_result in agent_results:
        completed = subprocess.run(
            [_DOCKER_EXECUTABLE, "logs", agent_result.container_name],
            check=False,
            capture_output=True,
            text=True,
        )
        log_result = _InteractiveProcessResult(
            returncode=agent_result.exit_code,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        _write_agent_run_artifacts(
            agent_result.output_directory,
            agent_result,
            log_result,
        )


def _wait_for_a2a_agent_ready(
    container_name: str,
    bind_host: str,
) -> _InteractiveProcessResult:
    command = [
        _DOCKER_EXECUTABLE,
        "exec",
        container_name,
        "python",
        "-c",
        (
            "import urllib.request; "
            "opener = urllib.request.build_opener(urllib.request.ProxyHandler({})); "
            "opener.open("
            f"{json.dumps(f'http://{bind_host}:8080/health')}, "
            "timeout=2).read()"
        ),
    ]
    completed = _InteractiveProcessResult(returncode=1, stdout="", stderr="")
    for delay in _A2A_READINESS_INTERVALS_SECONDS:
        if delay:
            time.sleep(delay)
        completed = _run_captured_command(command)
        if completed.returncode == 0:
            return completed

    return completed


def _run_captured_command(command: list[str]) -> _InteractiveProcessResult:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    return _InteractiveProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _prepare_agent_output_directory(
    run_directory: Path,
    agent_output_directory: Path,
) -> None:
    agent_output_directory.mkdir(parents=True, exist_ok=True)
    for file_name in ("config.json", _SECCOMP_PROFILE_FILE_NAME):
        source_path = run_directory / file_name
        if source_path.exists():
            shutil.copyfile(source_path, agent_output_directory / file_name)
    landlock_policy_path = run_directory / "landlock-policy.json"
    if landlock_policy_path.exists():
        shutil.copyfile(
            landlock_policy_path,
            agent_output_directory / "landlock-policy.json",
        )


def _write_agent_landlock_policy(
    configuration: DockerConfiguration,
    agent_output_directory: Path,
    agent_plan: ResolvedAgentPlan,
) -> None:
    agent_configuration = _agent_container_configuration(configuration, agent_plan)
    _write_landlock_policy(agent_configuration, agent_output_directory)


def _build_agent_remote_run_directory(
    remote_run_directory: str,
    agent_plan: ResolvedAgentPlan,
) -> str:
    remote_root = remote_run_directory.rstrip("/")
    return f"{remote_root}/agents/{agent_plan.agent_id}"


def _build_agent_network_alias(agent_plan: ResolvedAgentPlan) -> str:
    alias = []
    for character in agent_plan.agent_id.lower():
        if character.isalnum():
            alias.append(character)
            continue
        alias.append("-")

    return "-".join(part for part in "".join(alias).split("-") if part)


def _write_agent_run_artifacts(
    output_directory: Path,
    agent_result: AgentContainerRunResult,
    completed: _InteractiveProcessResult,
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (output_directory / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    metadata = {
        "agent_id": agent_result.agent_id,
        "container_name": agent_result.container_name,
        "command": agent_result.command,
        "remove_command": agent_result.remove_command,
        "exit_code": agent_result.exit_code,
    }
    metadata_text = json.dumps(metadata, indent=2)
    (output_directory / "run-metadata.json").write_text(
        f"{metadata_text}\n",
        encoding="utf-8",
    )


def _combine_agent_process_results(
    completed_results: list[_InteractiveProcessResult],
) -> _InteractiveProcessResult:
    returncode = 0
    for completed in completed_results:
        if completed.returncode != 0:
            returncode = completed.returncode
            break

    stdout = "".join(completed.stdout for completed in completed_results)
    stderr = "".join(completed.stderr for completed in completed_results)
    return _InteractiveProcessResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _build_agent_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str:
    plan = configuration.resolved_sandbox_plan
    if plan is not None and plan.agents:
        return plan.agents[0].container_name

    return f"{_CONTAINER_NAME_PREFIX}-{timestamp}"


def _build_remote_run_directory(
    configuration: DockerConfiguration,
    run_id: str,
) -> str:
    remote_root = configuration.profile.remote_run_root.rstrip("/")
    return f"{remote_root}/{run_id}"


def _build_gateway_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    plan = configuration.resolved_sandbox_plan
    if plan is not None:
        return plan.squid_proxy.container_name

    if configuration.profile.network_gateway is None:
        return None

    return f"{_GATEWAY_CONTAINER_NAME_PREFIX}-{timestamp}"


def _build_mcp_sidecar_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    plan = configuration.resolved_sandbox_plan
    if plan is not None:
        return plan.mcp_sidecar.container_name

    if not _should_start_mcp_sidecar(configuration):
        return None

    return f"{_MCP_SIDECAR_CONTAINER_NAME_PREFIX}-{timestamp}"


def _build_jina_reader_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    if not _should_start_jina_reader(configuration):
        return None

    return f"{_JINA_READER_CONTAINER_NAME_PREFIX}-{timestamp}"


def _build_code_sidecar_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    if not _should_start_code_sidecar(configuration):
        return None

    return f"{_CODE_SIDECAR_CONTAINER_NAME_PREFIX}-{timestamp}"


def _build_haproxy_sidecar_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    plan = configuration.resolved_sandbox_plan
    if plan is not None:
        return plan.haproxy.container_name

    if not _should_start_haproxy_sidecar(configuration):
        return None

    return f"{_HAPROXY_SIDECAR_CONTAINER_NAME_PREFIX}-{timestamp}"


def _build_ollama_sidecar_container_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    if not _should_start_ollama_sidecar(configuration):
        return None

    return f"{_OLLAMA_SIDECAR_CONTAINER_NAME_PREFIX}-{timestamp}"


def _build_network_name(
    configuration: DockerConfiguration,
    timestamp: str,
) -> str | None:
    plan = configuration.resolved_sandbox_plan
    if plan is not None:
        return plan.network_name

    if configuration.profile.network_gateway is None:
        return None

    return f"{_NETWORK_NAME_PREFIX}-{timestamp}"


def _build_allowed_directory(
    configuration: DockerConfiguration,
    remote_run_directory: str,
) -> str:
    return _format_directory_template(
        configuration.profile.allowed_directory_template,
        remote_run_directory,
    )


def _build_denied_directory(
    configuration: DockerConfiguration,
    remote_run_directory: str,
) -> str:
    return _format_directory_template(
        configuration.profile.denied_directory_template,
        remote_run_directory,
    )


def _format_directory_template(template: str, remote_run_directory: str) -> str:
    return template.format(remote_run_directory=remote_run_directory)


def _prepare_readonly_denied_directory(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if configuration.profile.readonly_denied_mount_target is None:
        return

    denied_child_directory = (
        run_directory / _READONLY_DENIED_SOURCE_DIRECTORY / "denied"
    )
    denied_child_directory.mkdir(parents=True, exist_ok=True)
    denied_file = denied_child_directory / "denied.txt"
    denied_file.write_text(_DENIED_FILE_CONTENT, encoding="utf-8")
    hidden_file = denied_child_directory / ".hidden"
    hidden_file.write_text(_HIDDEN_DENIED_FILE_CONTENT, encoding="utf-8")


def _prepare_readonly_persistence_directories(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    for target in configuration.profile.readonly_persistence_directories:
        _validate_container_directory(target)
        source_directory = _build_readonly_persistence_source_directory(
            run_directory,
            target,
        )
        source_directory.mkdir(parents=True, exist_ok=True)


def _prepare_denied_executable_stubs(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    denied_targets = _get_denied_executable_targets(configuration)
    if not denied_targets:
        return

    stub_directory = run_directory / _DENIED_EXECUTABLE_SOURCE_DIRECTORY
    stub_directory.mkdir(parents=True, exist_ok=True)
    for target_path in denied_targets:
        stub_path = stub_directory / _build_denied_executable_stub_name(target_path)
        stub_path.write_text(
            _build_denied_executable_stub_text(PurePosixPath(target_path).name),
            encoding="utf-8",
        )
        stub_path.chmod(0o755)


def _build_denied_executable_stub_text(executable_name: str) -> str:
    return (
        "#!/bin/sh\n"
        f"echo {shlex.quote(executable_name)}: denied by sandbox profile >&2\n"
        "exit 127\n"
    )


def _validate_executable_name(executable_name: str) -> None:
    if not executable_name or "/" in executable_name or "\\" in executable_name:
        raise ValueError(f"Invalid executable name: {executable_name!r}")


def _validate_executable_path(executable_path: str) -> None:
    path = PurePosixPath(executable_path)
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ValueError(f"Invalid executable path: {executable_path!r}")


def _validate_container_directory(directory: str) -> None:
    path = PurePosixPath(directory)
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ValueError(f"Invalid container directory: {directory!r}")


def _build_denied_executable_stub_name(target_path: str) -> str:
    _validate_executable_path(target_path)
    return target_path.strip("/").replace("/", "__")


def _build_readonly_persistence_source_directory(
    run_directory: Path,
    target: str,
) -> Path:
    return (
        run_directory
        / _READONLY_PERSISTENCE_SOURCE_DIRECTORY
        / target.strip("/").replace("/", "__")
    )


def _get_denied_executable_targets(
    configuration: DockerConfiguration,
) -> tuple[str, ...]:
    targets = []

    for executable_name in configuration.profile.denied_executables:
        _validate_executable_name(executable_name)
        targets.append(f"/usr/bin/{executable_name}")

    for executable_path in configuration.profile.denied_executable_paths:
        _validate_executable_path(executable_path)
        targets.append(executable_path)

    if configuration.profile.remove_desktop_automation_tools:
        targets = [
            target
            for target in targets
            if target not in _DESKTOP_AUTOMATION_EXECUTABLE_PATHS
        ]

    return tuple(dict.fromkeys(targets))


def _write_landlock_policy(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if not configuration.profile.landlock_rules:
        return

    policy = {
        "rules": [
            {
                "path": rule.path,
                "access": rule.access,
            }
            for rule in configuration.profile.landlock_rules
        ],
    }
    policy_text = json.dumps(policy, indent=2)
    policy_path = run_directory / "landlock-policy.json"
    policy_path.write_text(f"{policy_text}\n", encoding="utf-8")


def _write_seccomp_profile(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    seccomp_profile = configuration.profile.seccomp_profile
    if seccomp_profile is None:
        return

    profile_data = _build_seccomp_profile_data(seccomp_profile)
    profile_text = json.dumps(profile_data, indent=2)
    profile_path = run_directory / _SECCOMP_PROFILE_FILE_NAME
    profile_path.write_text(f"{profile_text}\n", encoding="utf-8")


def _build_seccomp_profile_data(seccomp_profile: SeccompProfile) -> dict[str, object]:
    return {
        "defaultAction": seccomp_profile.default_action,
        "syscalls": [
            {
                "names": list(seccomp_profile.denied_syscalls),
                "action": seccomp_profile.action,
            },
        ],
    }


def _write_squid_configuration(
    configuration: DockerConfiguration,
    run_directory: Path,
    config_data: Mapping[str, object],
) -> None:
    plan = configuration.resolved_sandbox_plan
    if plan is not None:
        if not plan.squid_proxy.enabled:
            return

        squid_config_path = run_directory / _SQUID_CONFIGURATION_FILE_NAME
        squid_config = build_squid_acl_configuration(plan)
        squid_config_path.write_text(squid_config, encoding="utf-8")
        return

    gateway = configuration.profile.network_gateway
    if gateway is None:
        return

    allowed_domains = _build_allowed_gateway_domains(
        gateway.allowed_domains, config_data
    )
    allowed_ip_addresses = _build_allowed_gateway_ip_addresses(
        gateway.allowed_ip_addresses
    )
    squid_config = _build_squid_configuration_text(
        allowed_domains,
        gateway.proxy_port,
        allowed_ip_addresses,
    )
    squid_config_path = run_directory / _SQUID_CONFIGURATION_FILE_NAME
    squid_config_path.write_text(squid_config, encoding="utf-8")


def _build_allowed_gateway_domains(
    configured_domains: tuple[str, ...],
    config_data: Mapping[str, object],
) -> tuple[str, ...]:
    _ = config_data
    domains = list(configured_domains)
    normalized_domains = tuple(
        dict.fromkeys(_normalize_gateway_domain(domain) for domain in domains)
    )
    return _remove_redundant_gateway_domain_suffixes(normalized_domains)


def _normalize_gateway_domain(domain: str) -> str:
    stripped_domain = domain.strip().lower()
    if stripped_domain.startswith("*."):
        return f".{stripped_domain[2:]}"

    return stripped_domain


def _remove_redundant_gateway_domain_suffixes(
    domains: tuple[str, ...],
) -> tuple[str, ...]:
    exact_domains = {domain for domain in domains if not domain.startswith(".")}
    filtered_domains = []
    for domain in domains:
        if domain.startswith(".") and domain[1:] in exact_domains:
            continue

        filtered_domains.append(domain)

    return tuple(filtered_domains)


def _build_allowed_gateway_ip_addresses(
    configured_ip_addresses: tuple[str, ...],
) -> tuple[str, ...]:
    ip_addresses = []
    for ip_address in configured_ip_addresses:
        normalized_ip_address = _normalize_gateway_ip_address(ip_address)
        ip_addresses.append(normalized_ip_address)

    return tuple(dict.fromkeys(ip_addresses))


def _normalize_gateway_ip_address(ip_address: str) -> str:
    normalized_ip_address = ip_address.strip().strip("[]")
    network = ipaddress.ip_network(normalized_ip_address, strict=False)
    return str(network)


def _build_squid_configuration_text(
    allowed_domains: tuple[str, ...],
    proxy_port: int,
    allowed_ip_addresses: tuple[str, ...] = (),
) -> str:
    domains = " ".join(allowed_domains)
    lines = [
        f"http_port {proxy_port}",
        "acl SSL_ports port 443",
        "acl Safe_ports port 80",
        "acl Safe_ports port 443",
        "acl CONNECT method CONNECT",
        f"acl allowed_sites dstdomain {domains}",
        r"acl ipv4_literal_url url_regex -i "
        r"^[a-z][a-z0-9+.-]*://[0-9]+(\.[0-9]+){3}([:/]|$)",
        r"acl ipv4_literal_connect url_regex -i ^[0-9]+(\.[0-9]+){3}:",
        r"acl ipv6_literal_url url_regex -i "
        r"^[a-z][a-z0-9+.-]*://\[[0-9a-f:.]+\]([:/]|$)",
        r"acl ipv6_literal_connect url_regex -i ^\[[0-9a-f:.]+\]:",
        "http_access deny !Safe_ports",
        "http_access deny CONNECT !SSL_ports",
    ]
    if allowed_ip_addresses:
        ip_addresses = " ".join(allowed_ip_addresses)
        lines.extend(
            [
                f"acl allowed_ip_addresses dst {ip_addresses}",
                "http_access allow allowed_ip_addresses",
            ]
        )

    lines.extend(
        [
            "http_access deny ipv4_literal_url",
            "http_access deny ipv4_literal_connect",
            "http_access deny ipv6_literal_url",
            "http_access deny ipv6_literal_connect",
            "http_access allow allowed_sites",
            "http_access deny all",
            "access_log none",
            "cache_log /tmp/squid-cache.log",
            "",
        ]
    )
    return "\n".join(lines)


def _start_network_gateway(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    gateway_container_name: str | None,
) -> tuple[list[list[str]] | None, str | None]:
    gateway = configuration.profile.network_gateway
    if gateway is None:
        return None, None

    if network_name is None or gateway_container_name is None:
        raise RuntimeError(
            "Network gateway profile requires network and container names."
        )

    commands = _build_gateway_start_commands(
        gateway.image_name,
        gateway_container_name,
        network_name,
        run_directory / _SQUID_CONFIGURATION_FILE_NAME,
        configuration,
    )
    results = []
    for command in commands:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        results.append(_build_gateway_command_result(command, completed))

    gateway_ip_address = _inspect_gateway_ip_address(
        gateway_container_name, network_name
    )
    results.append(
        {
            "command": _build_gateway_inspect_command(
                gateway_container_name,
                network_name,
            ),
            "gateway_ip_address": gateway_ip_address,
        }
    )
    _write_gateway_start_results(run_directory, results)

    return commands, gateway_ip_address


def _build_gateway_command_result(
    command: list[str],
    completed: subprocess.CompletedProcess[str],
) -> dict[str, object]:
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _inspect_gateway_ip_address(
    gateway_container_name: str,
    network_name: str,
) -> str | None:
    command = _build_gateway_inspect_command(gateway_container_name, network_name)
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None

    ip_address = completed.stdout.strip()
    if not ip_address or ip_address == "<no value>":
        return None

    return ip_address


def _build_gateway_inspect_command(
    gateway_container_name: str,
    network_name: str,
) -> list[str]:
    template = "{{(index (index .NetworkSettings.Networks "
    template += f"{json.dumps(network_name)}"
    template += ') "IPAddress")}}'
    return [
        _DOCKER_EXECUTABLE,
        "inspect",
        "--format",
        template,
        gateway_container_name,
    ]


def _write_gateway_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    results_path = run_directory / _GATEWAY_START_RESULTS_FILE_NAME
    results_text = json.dumps(results, indent=2)
    results_path.write_text(f"{results_text}\n", encoding="utf-8")


def _write_gateway_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    gateway_container_name: str | None,
) -> None:
    if configuration.profile.network_gateway is None:
        return

    if gateway_container_name is None:
        return

    completed = subprocess.run(
        [_DOCKER_EXECUTABLE, "logs", gateway_container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    log_data = {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    log_text = json.dumps(log_data, indent=2)
    log_path = run_directory / _GATEWAY_LOG_FILE_NAME
    log_path.write_text(f"{log_text}\n", encoding="utf-8")


def _start_mcp_sidecar(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    mcp_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    if not _should_start_mcp_sidecar(configuration):
        return None

    if network_name is None or mcp_sidecar_container_name is None:
        raise RuntimeError("MCP sidecar requires an internal network.")

    inspect_command = _build_mcp_sidecar_image_inspect_command()
    build_command = _build_mcp_sidecar_image_build_command(configuration)
    run_command = _build_mcp_sidecar_run_command(
        configuration,
        run_directory,
        network_name,
        mcp_sidecar_container_name,
    )
    commands = []
    results = []

    inspect_result = _run_recorded_docker_command(inspect_command)
    commands.append(inspect_command)
    results.append(inspect_result)

    build_result = _run_recorded_docker_command(build_command)
    commands.append(build_command)
    results.append(build_result)

    run_result = _run_recorded_docker_command(run_command)
    commands.append(run_command)
    results.append(run_result)

    _write_mcp_sidecar_start_results(run_directory, results)
    return commands


def _run_recorded_docker_command(command: list[str]) -> dict[str, object]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return _build_gateway_command_result(command, completed)


def _build_mcp_sidecar_image_inspect_command() -> list[str]:
    return [
        _DOCKER_EXECUTABLE,
        "image",
        "inspect",
        _MCP_SIDECAR_IMAGE_NAME,
    ]


def _build_mcp_sidecar_image_build_command(
    configuration: DockerConfiguration,
) -> list[str]:
    dockerfile_path = (
        configuration.build_context
        / "src"
        / "mcp_sidecar"
        / "dockerfile"
        / "Dockerfile"
    )
    command = [
        _DOCKER_EXECUTABLE,
        "build",
        "--file",
        str(dockerfile_path),
        "--tag",
        _MCP_SIDECAR_IMAGE_NAME,
    ]
    extra_packages = _build_mcp_sidecar_extra_python_packages(configuration)
    if extra_packages:
        command.extend(
            [
                "--build-arg",
                f"MCP_SIDECAR_EXTRA_PACKAGES={extra_packages}",
            ]
        )
    command.append(str(configuration.build_context))
    return command


def _build_mcp_sidecar_run_command(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str,
    mcp_sidecar_container_name: str,
) -> list[str]:
    proxy_url = "http://egress-gateway:3128"
    source_mount = _build_mcp_sidecar_source_mount(configuration)
    output_mount = _build_mcp_sidecar_output_mount(run_directory)
    exposure_mount = _build_mcp_sidecar_exposure_mount(run_directory)
    audit_log_path = (
        f"{_MCP_SIDECAR_OUTPUT_DIRECTORY}/{_MCP_SIDECAR_TOOL_CALLS_FILE_NAME}"
    )
    exposure_path = f"{_MCP_SIDECAR_CONFIG_DIRECTORY}/{_MCP_SIDECAR_EXPOSURE_FILE_NAME}"
    command = [
        _DOCKER_EXECUTABLE,
        "run",
        "--detach",
        "--name",
        mcp_sidecar_container_name,
        "--network",
        network_name,
        "--network-alias",
        _MCP_SIDECAR_ALIAS,
    ]
    plan = configuration.resolved_sandbox_plan
    if plan is not None and plan.mcp_sidecar.ip_address is not None:
        command.extend(["--ip", plan.mcp_sidecar.ip_address])

    command.extend(
        [
            "--env",
            f"HTTP_PROXY={proxy_url}",
            "--env",
            f"HTTPS_PROXY={proxy_url}",
            "--env",
            f"NO_PROXY={_build_mcp_sidecar_no_proxy(configuration)}",
            "--env",
            (
                f"{_JINA_READER_URL_ENVIRONMENT_VARIABLE}="
                f"http://{_JINA_READER_ALIAS}:{_JINA_READER_PORT}"
            ),
            "--env",
            (
                f"{_CODE_SIDECAR_URL_ENVIRONMENT_VARIABLE}="
                f"http://{_CODE_SIDECAR_ALIAS}:{_CODE_SIDECAR_PORT}"
            ),
            "--env",
            f"{_MCP_SIDECAR_AUDIT_LOG_PATH_ENVIRONMENT_VARIABLE}={audit_log_path}",
            "--env",
            f"{_MCP_SIDECAR_EXPOSURE_PATH_ENVIRONMENT_VARIABLE}={exposure_path}",
        ]
    )
    command.extend(_build_mcp_sidecar_openai_environment_options(configuration))
    command.extend(_build_mcp_sidecar_database_environment_options(configuration))
    command.extend(
        [
            "--mount",
            source_mount,
            "--mount",
            output_mount,
            "--mount",
            exposure_mount,
            _MCP_SIDECAR_IMAGE_NAME,
            "python",
            "-m",
            "mcp_sidecar",
            "--host",
            "0.0.0.0",
            "--port",
            str(_MCP_SIDECAR_PORT),
        ]
    )
    return command


def _build_mcp_sidecar_extra_python_packages(
    configuration: DockerConfiguration,
) -> str:
    packages = []
    if _mcp_sidecar_has_openai_capability(configuration):
        packages.append(_OPENAI_PACKAGE)

    return " ".join(packages)


def _build_mcp_sidecar_openai_environment_options(
    configuration: DockerConfiguration,
) -> list[str]:
    if not _mcp_sidecar_has_openai_capability(configuration):
        return []

    return ["--env", _OPENAI_API_KEY_ENVIRONMENT_VARIABLE]


def _mcp_sidecar_has_openai_capability(configuration: DockerConfiguration) -> bool:
    return bool(
        {
            _OPENAI_CAPABILITY,
            _OPENAI_AGENTS_CAPABILITY,
        }.intersection(_mcp_sidecar_capabilities(configuration))
    )


def _mcp_sidecar_capabilities(configuration: DockerConfiguration) -> tuple[str, ...]:
    plan = configuration.resolved_sandbox_plan
    if plan is not None:
        return plan.mcp_sidecar.capabilities

    return tuple(
        dict.fromkeys(
            (
                *configuration.mcp_sidecar_container_capabilities,
                *configuration.mcp_sidecar_application_capabilities,
            )
        )
    )


def _build_mcp_sidecar_no_proxy(configuration: DockerConfiguration) -> str:
    hosts = [
        "localhost",
        "127.0.0.1",
        _MCP_SIDECAR_ALIAS,
        _JINA_READER_ALIAS,
        _CODE_SIDECAR_ALIAS,
    ]
    if _should_start_haproxy_sidecar(configuration):
        hosts.append(_HAPROXY_SIDECAR_ALIAS)

    return ",".join(hosts)


def _build_mcp_sidecar_database_environment_options(
    configuration: DockerConfiguration,
) -> list[str]:
    if not _should_start_haproxy_sidecar(configuration):
        return []

    haproxy = _get_haproxy_configuration(configuration)
    port = _resolve_mariadb_proxy_port(haproxy.ports)
    return [
        "--env",
        f"{_MARIADB_HOST_ENVIRONMENT_VARIABLE}={_HAPROXY_SIDECAR_ALIAS}",
        "--env",
        f"{_MARIADB_PORT_ENVIRONMENT_VARIABLE}={port}",
        "--env",
        f"{_MARIADB_DATABASE_ENVIRONMENT_VARIABLE}={_MARIADB_DATABASE_NAME}",
        "--env",
        _MARIADB_CREDENTIALS_ENVIRONMENT_VARIABLE,
    ]


def _resolve_mariadb_proxy_port(ports: tuple[int, ...]) -> int:
    if _MARIADB_DEFAULT_PORT in ports:
        return _MARIADB_DEFAULT_PORT

    return ports[0]


def _build_mcp_sidecar_source_mount(configuration: DockerConfiguration) -> str:
    source_directory = configuration.build_context / "src" / "mcp_sidecar"
    return (
        f"type=bind,source={source_directory},"
        "target=/opt/mcp-sidecar/mcp_sidecar,readonly"
    )


def _build_mcp_sidecar_output_mount(run_directory: Path) -> str:
    return f"type=bind,source={run_directory},target={_MCP_SIDECAR_OUTPUT_DIRECTORY}"


def _build_mcp_sidecar_exposure_mount(run_directory: Path) -> str:
    source_path = run_directory / _MCP_SIDECAR_EXPOSURE_FILE_NAME
    return (
        f"type=bind,source={source_path},"
        f"target={_MCP_SIDECAR_CONFIG_DIRECTORY}/{_MCP_SIDECAR_EXPOSURE_FILE_NAME},"
        "readonly"
    )


def _write_mcp_sidecar_exposure(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    plan = configuration.resolved_sandbox_plan
    if plan is not None:
        exposure = {
            "tools": list(plan.mcp_sidecar.tools),
            "resources": list(plan.mcp_sidecar.resources),
        }
        exposure_text = json.dumps(exposure, indent=2)
        exposure_path = run_directory / _MCP_SIDECAR_EXPOSURE_FILE_NAME
        exposure_path.write_text(f"{exposure_text}\n", encoding="utf-8")
        return

    exposure = {
        "tools": list(configuration.mcp_sidecar_tools),
        "resources": list(configuration.mcp_sidecar_resources),
    }
    exposure_text = json.dumps(exposure, indent=2)
    exposure_path = run_directory / _MCP_SIDECAR_EXPOSURE_FILE_NAME
    exposure_path.write_text(f"{exposure_text}\n", encoding="utf-8")


def _write_mcp_sidecar_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    results_path = run_directory / _MCP_SIDECAR_START_RESULTS_FILE_NAME
    results_text = json.dumps(results, indent=2)
    results_path.write_text(f"{results_text}\n", encoding="utf-8")


def _write_mcp_sidecar_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    mcp_sidecar_container_name: str | None,
) -> None:
    if not _should_start_mcp_sidecar(configuration):
        return

    if mcp_sidecar_container_name is None:
        return

    completed = subprocess.run(
        [_DOCKER_EXECUTABLE, "logs", mcp_sidecar_container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    (run_directory / _MCP_SIDECAR_STDOUT_FILE_NAME).write_text(
        completed.stdout,
        encoding="utf-8",
    )
    (run_directory / _MCP_SIDECAR_STDERR_FILE_NAME).write_text(
        completed.stderr,
        encoding="utf-8",
    )
    metadata = {
        "container_name": mcp_sidecar_container_name,
        "image_name": _MCP_SIDECAR_IMAGE_NAME,
        "log_command": completed.args,
        "log_returncode": completed.returncode,
    }
    metadata_text = json.dumps(metadata, indent=2)
    metadata_path = run_directory / _MCP_SIDECAR_METADATA_FILE_NAME
    metadata_path.write_text(f"{metadata_text}\n", encoding="utf-8")
    log_data = {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    log_text = json.dumps(log_data, indent=2)
    log_path = run_directory / _MCP_SIDECAR_LOG_FILE_NAME
    log_path.write_text(f"{log_text}\n", encoding="utf-8")


def _start_code_sidecar(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    code_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    if not _should_start_code_sidecar(configuration):
        return None

    if network_name is None or code_sidecar_container_name is None:
        raise RuntimeError("Code sidecar requires an internal network.")

    inspect_command = _build_code_sidecar_image_inspect_command()
    build_command = _build_code_sidecar_image_build_command(configuration)
    run_command = _build_code_sidecar_run_command(
        configuration,
        run_directory,
        network_name,
        code_sidecar_container_name,
    )
    commands = []
    results = []

    inspect_result = _run_recorded_docker_command(inspect_command)
    commands.append(inspect_command)
    results.append(inspect_result)

    if inspect_result["returncode"] != 0:
        build_result = _run_recorded_docker_command(build_command)
        commands.append(build_command)
        results.append(build_result)

    run_result = _run_recorded_docker_command(run_command)
    commands.append(run_command)
    results.append(run_result)

    _write_code_sidecar_start_results(run_directory, results)
    return commands


def _build_code_sidecar_image_inspect_command() -> list[str]:
    return [
        _DOCKER_EXECUTABLE,
        "image",
        "inspect",
        _CODE_SIDECAR_IMAGE_NAME,
    ]


def _build_code_sidecar_image_build_command(
    configuration: DockerConfiguration,
) -> list[str]:
    dockerfile_path = (
        configuration.build_context
        / "src"
        / "code_sidecar"
        / "dockerfile"
        / "Dockerfile"
    )
    return [
        _DOCKER_EXECUTABLE,
        "build",
        "--file",
        str(dockerfile_path),
        "--tag",
        _CODE_SIDECAR_IMAGE_NAME,
        str(configuration.build_context),
    ]


def _build_ollama_sidecar_image_inspect_command(
    configuration: DockerConfiguration,
) -> list[str]:
    return [
        _DOCKER_EXECUTABLE,
        "image",
        "inspect",
        _get_ollama_sidecar_image_name(configuration),
    ]


def _build_ollama_sidecar_image_build_command(
    configuration: DockerConfiguration,
) -> list[str]:
    dockerfile_path = _write_ollama_sidecar_dockerfile(configuration)
    return [
        _DOCKER_EXECUTABLE,
        "build",
        "--file",
        str(dockerfile_path),
        "--tag",
        _get_ollama_sidecar_image_name(configuration),
        str(configuration.build_context),
    ]


def _write_ollama_sidecar_dockerfile(configuration: DockerConfiguration) -> Path:
    image_name = _get_ollama_sidecar_image_name(configuration)
    image_tag = image_name.rsplit(":", 1)[-1]
    dockerfile_path = (
        configuration.base_directory
        / "generated"
        / _OLLAMA_GENERATED_DIRECTORY
        / image_tag
        / "Dockerfile"
    )
    dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
    dockerfile = _generate_ollama_sidecar_dockerfile(configuration.ollama_models)
    dockerfile_path.write_text(f"{dockerfile.rstrip()}\n", encoding="utf-8")
    return dockerfile_path


def _generate_ollama_sidecar_dockerfile(models: tuple[str, ...]) -> str:
    if not models:
        raise ValueError("Ollama sidecar Dockerfile requires at least one model.")

    pull_commands = _build_ollama_model_pull_commands(models)
    return f"""FROM {_OLLAMA_BASE_IMAGE_NAME}

ENV OLLAMA_HOST=0.0.0.0:11434
EXPOSE 11434

RUN ollama serve > /tmp/ollama-build.log 2>&1 & \\
    server_pid=$!; \\
    for attempt in 1 2 3 4 5 6 7 8 9 10; do \\
        if ollama list >/dev/null 2>&1; then \\
            break; \\
        fi; \\
        sleep 1; \\
    done; \\
    ollama list >/dev/null; \\
{pull_commands} \\
    kill "$server_pid"; \\
    wait "$server_pid" || true
"""


def _build_ollama_model_pull_commands(models: tuple[str, ...]) -> str:
    lines = []
    for model in models:
        lines.append(f"    ollama pull {shlex.quote(model)};")

    return " \\\n".join(lines)


def _get_ollama_sidecar_image_name(configuration: DockerConfiguration) -> str:
    if _OLLAMA_CAPABILITY not in configuration.enabled_capabilities:
        raise ValueError("Ollama sidecar image requires the ollama capability.")
    if configuration.ollama_image_name is None:
        raise ValueError("Ollama sidecar image name is not configured.")
    if not configuration.ollama_models:
        raise ValueError("Ollama sidecar image requires at least one model.")

    return configuration.ollama_image_name


def _start_ollama_sidecar(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    ollama_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    if not _should_start_ollama_sidecar(configuration):
        return None

    if network_name is None or ollama_sidecar_container_name is None:
        raise RuntimeError("Ollama sidecar requires an internal network.")

    inspect_command = _build_ollama_sidecar_image_inspect_command(configuration)
    build_command = _build_ollama_sidecar_image_build_command(configuration)
    run_command = _build_ollama_sidecar_run_command(
        configuration,
        network_name,
        ollama_sidecar_container_name,
    )
    commands = []
    results = []

    inspect_result = _run_recorded_docker_command(inspect_command)
    commands.append(inspect_command)
    results.append(inspect_result)

    if inspect_result["returncode"] != 0:
        build_result = _run_recorded_docker_command(build_command)
        commands.append(build_command)
        results.append(build_result)

    run_result = _run_recorded_docker_command(run_command)
    commands.append(run_command)
    results.append(run_result)

    _write_ollama_sidecar_start_results(run_directory, results)
    return commands


def _build_ollama_sidecar_run_command(
    configuration: DockerConfiguration,
    network_name: str,
    ollama_sidecar_container_name: str,
) -> list[str]:
    return [
        _DOCKER_EXECUTABLE,
        "run",
        "--detach",
        "--init",
        "--name",
        ollama_sidecar_container_name,
        "--network",
        network_name,
        "--network-alias",
        _OLLAMA_SIDECAR_ALIAS,
        "--env",
        f"OLLAMA_HOST=0.0.0.0:{_OLLAMA_SIDECAR_PORT}",
        _get_ollama_sidecar_image_name(configuration),
    ]


def _write_ollama_sidecar_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    results_path = run_directory / _OLLAMA_SIDECAR_START_RESULTS_FILE_NAME
    results_text = json.dumps(results, indent=2)
    results_path.write_text(f"{results_text}\n", encoding="utf-8")


def _write_ollama_sidecar_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    ollama_sidecar_container_name: str | None,
) -> None:
    if not _should_start_ollama_sidecar(configuration):
        return

    if ollama_sidecar_container_name is None:
        return

    completed = subprocess.run(
        [_DOCKER_EXECUTABLE, "logs", ollama_sidecar_container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    (run_directory / _OLLAMA_SIDECAR_STDOUT_FILE_NAME).write_text(
        completed.stdout,
        encoding="utf-8",
    )
    (run_directory / _OLLAMA_SIDECAR_STDERR_FILE_NAME).write_text(
        completed.stderr,
        encoding="utf-8",
    )
    metadata = {
        "container_name": ollama_sidecar_container_name,
        "image_name": _get_ollama_sidecar_image_name(configuration),
        "models": list(configuration.ollama_models),
        "log_command": completed.args,
        "log_returncode": completed.returncode,
    }
    metadata_text = json.dumps(metadata, indent=2)
    metadata_path = run_directory / _OLLAMA_SIDECAR_METADATA_FILE_NAME
    metadata_path.write_text(f"{metadata_text}\n", encoding="utf-8")
    log_data = {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    log_text = json.dumps(log_data, indent=2)
    log_path = run_directory / _OLLAMA_SIDECAR_LOG_FILE_NAME
    log_path.write_text(f"{log_text}\n", encoding="utf-8")


def _wait_for_ollama_sidecar_ready(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    ollama_sidecar_container_name: str | None,
    intervals_seconds: tuple[float, ...] = _OLLAMA_READINESS_INTERVALS_SECONDS,
) -> None:
    if not _should_start_ollama_sidecar(configuration):
        return

    if network_name is None or ollama_sidecar_container_name is None:
        raise RuntimeError(
            "Ollama sidecar readiness check requires an internal network."
        )

    phases = [
        _run_ollama_sidecar_readiness_phase(
            configuration,
            network_name,
            "tcp",
            _build_ollama_sidecar_tcp_probe_script(),
            intervals_seconds,
        ),
        _run_ollama_sidecar_readiness_phase(
            configuration,
            network_name,
            "models",
            _build_ollama_sidecar_models_probe_script(configuration.ollama_models),
            intervals_seconds,
        ),
    ]
    ready = all(bool(phase["success"]) for phase in phases)
    result = {
        "container_name": ollama_sidecar_container_name,
        "ollama_url": f"http://{_OLLAMA_SIDECAR_ALIAS}:{_OLLAMA_SIDECAR_PORT}",
        "models": list(configuration.ollama_models),
        "ready": ready,
        "phases": phases,
    }
    _write_ollama_sidecar_readiness_results(run_directory, result)
    if not ready:
        raise RuntimeError("Ollama sidecar did not become ready.")


def _run_ollama_sidecar_readiness_phase(
    configuration: DockerConfiguration,
    network_name: str,
    phase_name: str,
    script: str,
    intervals_seconds: tuple[float, ...],
) -> dict[str, object]:
    attempts = []
    for attempt_index, interval_seconds in enumerate(intervals_seconds, start=1):
        if interval_seconds > 0:
            time.sleep(interval_seconds)

        command = _build_ollama_sidecar_probe_command(
            configuration,
            network_name,
            script,
        )
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        success = completed.returncode == 0
        attempts.append(
            {
                "attempt": attempt_index,
                "wait_seconds": interval_seconds,
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "success": success,
            }
        )
        if success:
            break

    return {
        "name": phase_name,
        "success": bool(attempts and attempts[-1]["success"]),
        "attempts": attempts,
    }


def _build_ollama_sidecar_probe_command(
    configuration: DockerConfiguration,
    network_name: str,
    script: str,
) -> list[str]:
    return [
        _DOCKER_EXECUTABLE,
        "run",
        "--rm",
        "--network",
        network_name,
        configuration.profile.image_name,
        "python",
        "-c",
        script,
    ]


def _build_ollama_sidecar_tcp_probe_script() -> str:
    return (
        "import socket\n"
        f"with socket.create_connection(('{_OLLAMA_SIDECAR_ALIAS}', "
        f"{_OLLAMA_SIDECAR_PORT}), timeout=5):\n"
        "    print('ready')\n"
    )


def _build_ollama_sidecar_models_probe_script(models: tuple[str, ...]) -> str:
    url = f"http://{_OLLAMA_SIDECAR_ALIAS}:{_OLLAMA_SIDECAR_PORT}/api/tags"
    return (
        "import json\n"
        "from urllib.request import urlopen\n"
        f"expected_models = {list(models)!r}\n"
        f"with urlopen({url!r}, timeout=30) as response:\n"
        "    status = response.status\n"
        "    body = response.read()\n"
        "if status < 200 or status >= 300:\n"
        "    raise SystemExit(status)\n"
        "data = json.loads(body.decode('utf-8'))\n"
        "available_models = {\n"
        "    model.get('name') or model.get('model')\n"
        "    for model in data.get('models', [])\n"
        "    if isinstance(model, dict)\n"
        "}\n"
        "missing_models = [\n"
        "    model for model in expected_models if model not in available_models\n"
        "]\n"
        "if missing_models:\n"
        "    print(json.dumps({'missing_models': missing_models}, sort_keys=True))\n"
        "    raise SystemExit(1)\n"
        "print(json.dumps({'models': sorted(available_models)}, sort_keys=True))\n"
    )


def _write_ollama_sidecar_readiness_results(
    run_directory: Path,
    result: dict[str, object],
) -> None:
    results_path = run_directory / _OLLAMA_SIDECAR_READINESS_RESULTS_FILE_NAME
    results_text = json.dumps(result, indent=2)
    results_path.write_text(f"{results_text}\n", encoding="utf-8")


def _build_code_sidecar_run_command(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str,
    code_sidecar_container_name: str,
) -> list[str]:
    source_mount = _build_code_sidecar_source_mount(configuration)
    output_mount = _build_code_sidecar_output_mount(run_directory)
    return [
        _DOCKER_EXECUTABLE,
        "run",
        "--detach",
        "--init",
        "--read-only",
        "--name",
        code_sidecar_container_name,
        "--network",
        network_name,
        "--network-alias",
        _CODE_SIDECAR_ALIAS,
        "--pids-limit",
        "32",
        "--memory",
        "128m",
        "--memory-swap",
        "128m",
        "--cpus",
        "0.5",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--security-opt",
        f"seccomp={run_directory / _SECCOMP_PROFILE_FILE_NAME}",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=16m",
        "--env",
        f"{_CODE_SIDECAR_OUTPUT_DIRECTORY_ENVIRONMENT_VARIABLE}="
        f"{_CODE_SIDECAR_OUTPUT_DIRECTORY}",
        "--mount",
        source_mount,
        "--mount",
        output_mount,
        _CODE_SIDECAR_IMAGE_NAME,
        "python",
        "-m",
        "code_sidecar",
        "--host",
        "0.0.0.0",
        "--port",
        str(_CODE_SIDECAR_PORT),
    ]


def _build_code_sidecar_source_mount(configuration: DockerConfiguration) -> str:
    source_directory = configuration.build_context / "src" / "code_sidecar"
    return (
        f"type=bind,source={source_directory},"
        "target=/opt/code-sidecar/code_sidecar,readonly"
    )


def _build_code_sidecar_output_mount(run_directory: Path) -> str:
    return f"type=bind,source={run_directory},target={_CODE_SIDECAR_OUTPUT_DIRECTORY}"


def _write_code_sidecar_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    results_path = run_directory / _CODE_SIDECAR_START_RESULTS_FILE_NAME
    results_text = json.dumps(results, indent=2)
    results_path.write_text(f"{results_text}\n", encoding="utf-8")


def _write_code_sidecar_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    code_sidecar_container_name: str | None,
) -> None:
    if not _should_start_code_sidecar(configuration):
        return

    if code_sidecar_container_name is None:
        return

    completed = subprocess.run(
        [_DOCKER_EXECUTABLE, "logs", code_sidecar_container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    (run_directory / _CODE_SIDECAR_STDOUT_FILE_NAME).write_text(
        completed.stdout,
        encoding="utf-8",
    )
    (run_directory / _CODE_SIDECAR_STDERR_FILE_NAME).write_text(
        completed.stderr,
        encoding="utf-8",
    )
    metadata = {
        "container_name": code_sidecar_container_name,
        "image_name": _CODE_SIDECAR_IMAGE_NAME,
        "log_command": completed.args,
        "log_returncode": completed.returncode,
    }
    metadata_text = json.dumps(metadata, indent=2)
    metadata_path = run_directory / _CODE_SIDECAR_METADATA_FILE_NAME
    metadata_path.write_text(f"{metadata_text}\n", encoding="utf-8")
    log_data = {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    log_text = json.dumps(log_data, indent=2)
    log_path = run_directory / _CODE_SIDECAR_LOG_FILE_NAME
    log_path.write_text(f"{log_text}\n", encoding="utf-8")


def _write_haproxy_configuration(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    plan = configuration.resolved_sandbox_plan
    if plan is not None:
        if not plan.haproxy.enabled:
            return

        config_path = run_directory / _HAPROXY_CONFIGURATION_FILE_NAME
        config_text = build_haproxy_acl_configuration(plan)
        config_path.write_text(f"{config_text.rstrip()}\n", encoding="utf-8")
        return

    if not _should_start_haproxy_sidecar(configuration):
        return

    haproxy = _get_haproxy_configuration(configuration)
    config_path = run_directory / _HAPROXY_CONFIGURATION_FILE_NAME
    config_text = _generate_haproxy_configuration(
        haproxy.backend_host,
        haproxy.ports,
    )
    config_path.write_text(f"{config_text.rstrip()}\n", encoding="utf-8")


def _generate_haproxy_configuration(backend_host: str, ports: tuple[int, ...]) -> str:
    port_sections = []
    for port in ports:
        port_sections.append(
            "\n".join(
                [
                    f"frontend tcp_{port}",
                    f"    bind *:{port}",
                    f"    default_backend backend_{port}",
                    "",
                    f"backend backend_{port}",
                    f"    server host {backend_host}:{port}",
                ]
            )
        )

    return "\n\n".join(
        [
            "global",
            "    log stdout format raw local0",
            "    maxconn 256",
            "",
            "defaults",
            "    mode tcp",
            "    log global",
            "    timeout connect 5s",
            "    timeout client 1m",
            "    timeout server 1m",
            "",
            *port_sections,
        ]
    )


def _get_haproxy_configuration(
    configuration: DockerConfiguration,
) -> HAProxyConfiguration:
    if _HAPROXY_CAPABILITY not in configuration.enabled_capabilities:
        raise ValueError("HAProxy sidecar requires the haproxy capability.")
    if configuration.haproxy is None:
        raise ValueError("HAProxy sidecar configuration is not configured.")
    if not configuration.haproxy.ports:
        raise ValueError("HAProxy sidecar requires at least one port.")

    return configuration.haproxy


def _start_haproxy_sidecar(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    haproxy_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    if not _should_start_haproxy_sidecar(configuration):
        return None

    if network_name is None or haproxy_sidecar_container_name is None:
        raise RuntimeError("HAProxy sidecar requires an internal network.")

    run_command = _build_haproxy_sidecar_run_command(
        run_directory,
        haproxy_sidecar_container_name,
    )
    network_connect_command = _build_haproxy_sidecar_network_connect_command(
        network_name,
        haproxy_sidecar_container_name,
        configuration,
    )
    result = _run_recorded_docker_command(run_command)
    network_connect_result = _run_recorded_docker_command(network_connect_command)
    _write_haproxy_sidecar_start_results(
        run_directory,
        [result, network_connect_result],
    )
    return [run_command, network_connect_command]


def _build_haproxy_sidecar_run_command(
    run_directory: Path,
    haproxy_sidecar_container_name: str,
) -> list[str]:
    config_path = run_directory / _HAPROXY_CONFIGURATION_FILE_NAME
    return [
        _DOCKER_EXECUTABLE,
        "run",
        "--detach",
        "--name",
        haproxy_sidecar_container_name,
        "--network",
        "bridge",
        "--add-host",
        "host.docker.internal:host-gateway",
        "--mount",
        (
            f"type=bind,source={config_path},"
            f"target={_HAPROXY_CONFIGURATION_PATH},readonly"
        ),
        _HAPROXY_IMAGE_NAME,
    ]


def _build_haproxy_sidecar_network_connect_command(
    network_name: str,
    haproxy_sidecar_container_name: str,
    configuration: DockerConfiguration | None = None,
) -> list[str]:
    command = [
        _DOCKER_EXECUTABLE,
        "network",
        "connect",
        "--alias",
        _HAPROXY_SIDECAR_ALIAS,
    ]
    plan = None if configuration is None else configuration.resolved_sandbox_plan
    if plan is not None and plan.haproxy.ip_address is not None:
        command.extend(["--ip", plan.haproxy.ip_address])

    command.extend([network_name, haproxy_sidecar_container_name])
    return command


def _write_haproxy_sidecar_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    results_path = run_directory / _HAPROXY_SIDECAR_START_RESULTS_FILE_NAME
    results_text = json.dumps(results, indent=2)
    results_path.write_text(f"{results_text}\n", encoding="utf-8")


def _write_haproxy_sidecar_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    haproxy_sidecar_container_name: str | None,
) -> None:
    if not _should_start_haproxy_sidecar(configuration):
        return

    if haproxy_sidecar_container_name is None:
        return

    completed = subprocess.run(
        [_DOCKER_EXECUTABLE, "logs", haproxy_sidecar_container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    (run_directory / _HAPROXY_SIDECAR_STDOUT_FILE_NAME).write_text(
        completed.stdout,
        encoding="utf-8",
    )
    (run_directory / _HAPROXY_SIDECAR_STDERR_FILE_NAME).write_text(
        completed.stderr,
        encoding="utf-8",
    )
    haproxy = _get_haproxy_configuration(configuration)
    metadata = {
        "container_name": haproxy_sidecar_container_name,
        "image_name": _HAPROXY_IMAGE_NAME,
        "backend_host": haproxy.backend_host,
        "ports": list(haproxy.ports),
        "log_command": completed.args,
        "log_returncode": completed.returncode,
    }
    metadata_text = json.dumps(metadata, indent=2)
    metadata_path = run_directory / _HAPROXY_SIDECAR_METADATA_FILE_NAME
    metadata_path.write_text(f"{metadata_text}\n", encoding="utf-8")
    log_data = {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    log_text = json.dumps(log_data, indent=2)
    log_path = run_directory / _HAPROXY_SIDECAR_LOG_FILE_NAME
    log_path.write_text(f"{log_text}\n", encoding="utf-8")


def _start_jina_reader(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    jina_reader_container_name: str | None,
) -> list[list[str]] | None:
    if not _should_start_jina_reader(configuration):
        return None

    if network_name is None or jina_reader_container_name is None:
        raise RuntimeError("Jina Reader requires an internal network.")

    run_command = _build_jina_reader_run_command(
        network_name,
        jina_reader_container_name,
    )
    result = _run_recorded_docker_command(run_command)
    _write_jina_reader_start_results(run_directory, [result])
    return [run_command]


def _build_jina_reader_run_command(
    network_name: str,
    jina_reader_container_name: str,
) -> list[str]:
    proxy_url = "http://egress-gateway:3128"
    no_proxy = ",".join(
        (
            "localhost",
            "127.0.0.1",
            _JINA_READER_ALIAS,
            _MCP_SIDECAR_ALIAS,
        )
    )
    return [
        _DOCKER_EXECUTABLE,
        "run",
        "--detach",
        "--name",
        jina_reader_container_name,
        "--network",
        network_name,
        "--network-alias",
        _JINA_READER_ALIAS,
        "--env",
        f"HTTP_PROXY={proxy_url}",
        "--env",
        f"HTTPS_PROXY={proxy_url}",
        "--env",
        f"NO_PROXY={no_proxy}",
        _JINA_READER_IMAGE_NAME,
    ]


def _wait_for_jina_reader_ready(
    configuration: DockerConfiguration,
    run_directory: Path,
    network_name: str | None,
    jina_reader_container_name: str | None,
    intervals_seconds: tuple[float, ...] = _JINA_READER_READINESS_INTERVALS_SECONDS,
) -> None:
    if not _should_start_jina_reader(configuration):
        return

    if network_name is None or jina_reader_container_name is None:
        raise RuntimeError("Jina Reader readiness check requires an internal network.")

    phases = [
        _run_jina_reader_readiness_phase(
            configuration,
            network_name,
            "tcp",
            _build_jina_reader_tcp_probe_script(),
            intervals_seconds,
        ),
        _run_jina_reader_readiness_phase(
            configuration,
            network_name,
            "fetch",
            _build_jina_reader_fetch_probe_script(),
            intervals_seconds,
        ),
    ]
    ready = all(bool(phase["success"]) for phase in phases)
    result = {
        "container_name": jina_reader_container_name,
        "reader_url": f"http://{_JINA_READER_ALIAS}:{_JINA_READER_PORT}",
        "fetch_url": _JINA_READER_READINESS_URL,
        "ready": ready,
        "phases": phases,
    }
    _write_jina_reader_readiness_results(run_directory, result)
    if not ready:
        raise RuntimeError("Jina Reader did not become ready.")


def _run_jina_reader_readiness_phase(
    configuration: DockerConfiguration,
    network_name: str,
    phase_name: str,
    script: str,
    intervals_seconds: tuple[float, ...],
) -> dict[str, object]:
    attempts = []
    for attempt_index, interval_seconds in enumerate(intervals_seconds, start=1):
        if interval_seconds > 0:
            time.sleep(interval_seconds)

        command = _build_jina_reader_probe_command(
            configuration,
            network_name,
            script,
        )
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        success = completed.returncode == 0
        attempts.append(
            {
                "attempt": attempt_index,
                "wait_seconds": interval_seconds,
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "success": success,
            }
        )
        if success:
            break

    return {
        "name": phase_name,
        "success": bool(attempts and attempts[-1]["success"]),
        "attempts": attempts,
    }


def _build_jina_reader_probe_command(
    configuration: DockerConfiguration,
    network_name: str,
    script: str,
) -> list[str]:
    return [
        _DOCKER_EXECUTABLE,
        "run",
        "--rm",
        "--network",
        network_name,
        configuration.profile.image_name,
        "python",
        "-c",
        script,
    ]


def _build_jina_reader_tcp_probe_script() -> str:
    return (
        "import socket\n"
        f"with socket.create_connection(('{_JINA_READER_ALIAS}', "
        f"{_JINA_READER_PORT}), timeout=5):\n"
        "    print('ready')\n"
    )


def _build_jina_reader_fetch_probe_script() -> str:
    reader_url = (
        f"http://{_JINA_READER_ALIAS}:{_JINA_READER_PORT}/{_JINA_READER_READINESS_URL}"
    )
    return (
        "from urllib.request import urlopen\n"
        f"with urlopen({reader_url!r}, timeout=60) as response:\n"
        "    status = response.status\n"
        "    body = response.read(200)\n"
        "if status < 200 or status >= 300:\n"
        "    raise SystemExit(status)\n"
        "print(body.decode('utf-8', errors='replace'))\n"
    )


def _write_jina_reader_readiness_results(
    run_directory: Path,
    result: dict[str, object],
) -> None:
    results_path = run_directory / _JINA_READER_READINESS_RESULTS_FILE_NAME
    results_text = json.dumps(result, indent=2)
    results_path.write_text(f"{results_text}\n", encoding="utf-8")


def _write_jina_reader_start_results(
    run_directory: Path,
    results: list[dict[str, object]],
) -> None:
    results_path = run_directory / _JINA_READER_START_RESULTS_FILE_NAME
    results_text = json.dumps(results, indent=2)
    results_path.write_text(f"{results_text}\n", encoding="utf-8")


def _write_jina_reader_logs(
    configuration: DockerConfiguration,
    run_directory: Path,
    jina_reader_container_name: str | None,
) -> None:
    if not _should_start_jina_reader(configuration):
        return

    if jina_reader_container_name is None:
        return

    completed = subprocess.run(
        [_DOCKER_EXECUTABLE, "logs", jina_reader_container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    (run_directory / _JINA_READER_STDOUT_FILE_NAME).write_text(
        completed.stdout,
        encoding="utf-8",
    )
    (run_directory / _JINA_READER_STDERR_FILE_NAME).write_text(
        completed.stderr,
        encoding="utf-8",
    )
    metadata = {
        "container_name": jina_reader_container_name,
        "image_name": _JINA_READER_IMAGE_NAME,
        "log_command": completed.args,
        "log_returncode": completed.returncode,
    }
    metadata_text = json.dumps(metadata, indent=2)
    metadata_path = run_directory / _JINA_READER_METADATA_FILE_NAME
    metadata_path.write_text(f"{metadata_text}\n", encoding="utf-8")
    log_data = {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    log_text = json.dumps(log_data, indent=2)
    log_path = run_directory / _JINA_READER_LOG_FILE_NAME
    log_path.write_text(f"{log_text}\n", encoding="utf-8")


def _build_gateway_start_commands(
    gateway_image_name: str,
    gateway_container_name: str,
    network_name: str,
    squid_config_path: Path,
    configuration: DockerConfiguration | None = None,
) -> list[list[str]]:
    plan = None if configuration is None else configuration.resolved_sandbox_plan
    network_create_command = (
        None if plan is None else build_network_create_command(plan)
    )
    if network_create_command is None:
        network_create_command = [
            _DOCKER_EXECUTABLE,
            "network",
            "create",
            "--internal",
            network_name,
        ]
    network_connect_command = [
        _DOCKER_EXECUTABLE,
        "network",
        "connect",
        "--alias",
        "egress-gateway",
    ]
    if plan is not None and plan.squid_proxy.ip_address is not None:
        network_connect_command.extend(["--ip", plan.squid_proxy.ip_address])
    network_connect_command.extend([network_name, gateway_container_name])

    return [
        network_create_command,
        [
            _DOCKER_EXECUTABLE,
            "run",
            "--detach",
            "--name",
            gateway_container_name,
            "--network",
            "bridge",
            "--mount",
            (
                f"type=bind,source={squid_config_path},"
                "target=/etc/squid/squid.conf,readonly"
            ),
            gateway_image_name,
        ],
        network_connect_command,
        [
            _DOCKER_EXECUTABLE,
            "exec",
            gateway_container_name,
            "/bin/sh",
            "-c",
            (
                "for attempt in 1 2 3 4 5; do "
                "squid -k check -f /etc/squid/squid.conf >/dev/null 2>&1 "
                "&& exit 0; "
                "sleep 1; "
                "done; "
                "squid -k check -f /etc/squid/squid.conf"
            ),
        ],
    ]


def _build_gateway_cleanup_commands(
    configuration: DockerConfiguration,
    network_name: str | None,
    gateway_container_name: str | None,
) -> list[list[str]] | None:
    if configuration.profile.network_gateway is None:
        return None

    if network_name is None or gateway_container_name is None:
        return None

    return [
        [_DOCKER_EXECUTABLE, "rm", "--force", gateway_container_name],
        [_DOCKER_EXECUTABLE, "network", "rm", network_name],
    ]


def _build_mcp_sidecar_cleanup_commands(
    configuration: DockerConfiguration,
    mcp_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    if not _should_start_mcp_sidecar(configuration):
        return None

    if mcp_sidecar_container_name is None:
        return None

    return [[_DOCKER_EXECUTABLE, "rm", "--force", mcp_sidecar_container_name]]


def _build_jina_reader_cleanup_commands(
    configuration: DockerConfiguration,
    jina_reader_container_name: str | None,
) -> list[list[str]] | None:
    if not _should_start_jina_reader(configuration):
        return None

    if jina_reader_container_name is None:
        return None

    return [[_DOCKER_EXECUTABLE, "rm", "--force", jina_reader_container_name]]


def _build_code_sidecar_cleanup_commands(
    configuration: DockerConfiguration,
    code_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    if not _should_start_code_sidecar(configuration):
        return None

    if code_sidecar_container_name is None:
        return None

    return [[_DOCKER_EXECUTABLE, "rm", "--force", code_sidecar_container_name]]


def _build_haproxy_sidecar_cleanup_commands(
    configuration: DockerConfiguration,
    haproxy_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    if not _should_start_haproxy_sidecar(configuration):
        return None

    if haproxy_sidecar_container_name is None:
        return None

    return [[_DOCKER_EXECUTABLE, "rm", "--force", haproxy_sidecar_container_name]]


def _build_ollama_sidecar_cleanup_commands(
    configuration: DockerConfiguration,
    ollama_sidecar_container_name: str | None,
) -> list[list[str]] | None:
    if not _should_start_ollama_sidecar(configuration):
        return None

    if ollama_sidecar_container_name is None:
        return None

    return [[_DOCKER_EXECUTABLE, "rm", "--force", ollama_sidecar_container_name]]


def _should_start_mcp_sidecar(configuration: DockerConfiguration) -> bool:
    plan = configuration.resolved_sandbox_plan
    if plan is not None:
        return (
            configuration.run_target == SandboxRunTarget.AGENT
            and plan.mcp_sidecar.enabled
        )

    return (
        configuration.run_target == SandboxRunTarget.AGENT
        and configuration.profile.network_gateway is not None
    )


def _should_start_jina_reader(configuration: DockerConfiguration) -> bool:
    return (
        configuration.run_target == SandboxRunTarget.AGENT
        and configuration.profile.network_gateway is not None
        and _JINA_READER_CAPABILITY in configuration.enabled_capabilities
    )


def _should_start_code_sidecar(configuration: DockerConfiguration) -> bool:
    return (
        configuration.run_target == SandboxRunTarget.AGENT
        and configuration.profile.network_gateway is not None
        and _CODE_EXECUTION_CAPABILITY in configuration.enabled_capabilities
    )


def _should_start_haproxy_sidecar(configuration: DockerConfiguration) -> bool:
    plan = configuration.resolved_sandbox_plan
    if plan is not None:
        return (
            configuration.run_target == SandboxRunTarget.AGENT and plan.haproxy.enabled
        )

    return (
        configuration.run_target == SandboxRunTarget.AGENT
        and configuration.profile.network_gateway is not None
        and _HAPROXY_CAPABILITY in configuration.enabled_capabilities
    )


def _should_start_ollama_sidecar(configuration: DockerConfiguration) -> bool:
    return (
        configuration.run_target == SandboxRunTarget.AGENT
        and configuration.profile.network_gateway is not None
        and _OLLAMA_CAPABILITY in configuration.enabled_capabilities
    )


def _delete_readonly_denied_directory(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if configuration.profile.readonly_denied_mount_target is None:
        return

    denied_source_directory = run_directory / _READONLY_DENIED_SOURCE_DIRECTORY
    resolved_run_directory = run_directory.resolve()
    resolved_denied_source_directory = denied_source_directory.resolve()

    if resolved_run_directory not in resolved_denied_source_directory.parents:
        raise RuntimeError(
            "Refusing to remove readonly denied fixture outside the run "
            f"directory: {resolved_denied_source_directory}"
        )

    shutil.rmtree(denied_source_directory, ignore_errors=True)


def _delete_readonly_persistence_directory(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if not configuration.profile.readonly_persistence_directories:
        return

    persistence_source_directory = (
        run_directory / _READONLY_PERSISTENCE_SOURCE_DIRECTORY
    )
    resolved_run_directory = run_directory.resolve()
    resolved_persistence_source_directory = persistence_source_directory.resolve()

    if resolved_run_directory not in resolved_persistence_source_directory.parents:
        raise RuntimeError(
            "Refusing to remove readonly persistence fixture outside the run "
            f"directory: {resolved_persistence_source_directory}"
        )

    shutil.rmtree(persistence_source_directory, ignore_errors=True)


def _delete_denied_executable_directory(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> None:
    if not _get_denied_executable_targets(configuration):
        return

    stub_directory = run_directory / _DENIED_EXECUTABLE_SOURCE_DIRECTORY
    resolved_run_directory = run_directory.resolve()
    resolved_stub_directory = stub_directory.resolve()

    if resolved_run_directory not in resolved_stub_directory.parents:
        raise RuntimeError(
            "Refusing to remove denied executable stubs outside the run "
            f"directory: {resolved_stub_directory}"
        )

    shutil.rmtree(stub_directory, ignore_errors=True)


def _build_config_data(
    remote_run_directory: str,
    allowed_directory: str,
    denied_directory: str,
    guest_user: str,
    ssh_agent_socket: str | None = None,
    browser_debugging: BrowserDebuggingProfile | None = None,
    browser_surface: BrowserSurfaceProfile | None = None,
    mounted_shared_directory: str | None = None,
) -> dict[str, object]:
    return {
        "working_directory": remote_run_directory,
        "allowed_directory": allowed_directory,
        "denied_directory": denied_directory,
        "runtime_user_directory": f"/home/{guest_user}",
        "runtime_temp_directory": "/tmp",
        "mounted_shared_directory": mounted_shared_directory,
        "operating_system": "Linux",
        "allowed_domain": "example.com",
        "denied_domain": "example.net",
        "allowed_local_address": None,
        "denied_local_address": None,
        "allowed_localnet_address": None,
        "denied_localnet_address": None,
        "allowed_intranet_target": None,
        "denied_intranet_target": "192.168.86.28",
        "allowed_database_address": None,
        "denied_database_address": None,
        "container_runtime_socket": None,
        "local_dev_server_url": None,
        "local_model_server_url": None,
        "metadata_endpoint_url": None,
        "dns_exfiltration_domain": "c2FuZGJveC10ZXN0ZXI.example.com",
        "http_exfiltration_domain": "example.com",
        "http_exfiltration_header": "exfiltration=example",
        "websocket_exfiltration_url": "wss://echo.websocket.org",
        "smtp_exfiltration_url": None,
        "ssh_agent_socket": ssh_agent_socket,
        "browser_debugging_url": _get_browser_debugging_url(browser_debugging),
        "browser_executable": _get_browser_executable(browser_debugging),
        "existing_browser_profile": _get_existing_browser_profile(browser_debugging),
        "browser_chromium_arguments": _get_browser_chromium_arguments(browser_surface),
        "allowed_git_repository": None,
        "denied_git_repository": None,
        "git_remote_url": _GIT_REMOTE_URL,
        "allow_camera_capture": _get_allow_camera_capture(browser_surface),
        "allow_microphone_capture": _get_allow_microphone_capture(browser_surface),
        "output_directory": _REMOTE_OUTPUT_DIRECTORY,
    }


def _build_config_json(
    remote_run_directory: str,
    allowed_directory: str,
    denied_directory: str,
    guest_user: str,
    ssh_agent_socket: str | None = None,
    browser_debugging: BrowserDebuggingProfile | None = None,
    browser_surface: BrowserSurfaceProfile | None = None,
) -> str:
    config = _build_config_data(
        remote_run_directory,
        allowed_directory,
        denied_directory,
        guest_user,
        ssh_agent_socket,
        browser_debugging,
        browser_surface,
    )
    return f"{json.dumps(config, indent=2)}\n"


def _get_browser_debugging_url(
    browser_debugging: BrowserDebuggingProfile | None,
) -> str | None:
    if browser_debugging is None:
        return None

    return browser_debugging.debugging_url


def _get_browser_executable(
    browser_debugging: BrowserDebuggingProfile | None,
) -> str | None:
    if browser_debugging is None:
        return None

    return browser_debugging.browser_executable


def _get_existing_browser_profile(
    browser_debugging: BrowserDebuggingProfile | None,
) -> str | None:
    if browser_debugging is None:
        return None

    return browser_debugging.existing_browser_profile


def _get_browser_chromium_arguments(
    browser_surface: BrowserSurfaceProfile | None,
) -> list[str]:
    if browser_surface is None:
        return []

    return list(browser_surface.chromium_arguments)


def _get_mounted_shared_directory(configuration: DockerConfiguration) -> str | None:
    if _SHARED_VOLUME_CAPABILITY not in configuration.enabled_capabilities:
        return None

    return _REMOTE_SHARED_DIRECTORY


def _get_allow_camera_capture(
    browser_surface: BrowserSurfaceProfile | None,
) -> bool:
    if browser_surface is None:
        return True

    return browser_surface.allow_camera_capture


def _get_allow_microphone_capture(
    browser_surface: BrowserSurfaceProfile | None,
) -> bool:
    if browser_surface is None:
        return True

    return browser_surface.allow_microphone_capture


def _build_docker_run_command(
    configuration: DockerConfiguration,
    run_directory: Path,
    container_name: str,
    remote_run_directory: str,
    output_directory: Path | None = None,
    network_name: str | None = None,
    allowed_directory: str | None = None,
    denied_directory: str | None = None,
    environment_variables: dict[str, str] | None = None,
    gateway_ip_address: str | None = None,
    local_environment_variable_names: Set[str] | None = None,
    verbose: bool = False,
    serialize_evidence: bool = False,
    agent_plan: ResolvedAgentPlan | None = None,
    detached: bool = False,
    network_alias: str | None = None,
    module_arguments: tuple[str, ...] = (),
) -> list[str]:
    container_configuration = _agent_container_configuration(
        configuration,
        agent_plan,
    )
    effective_environment_variables = _agent_environment_variables(
        container_configuration,
        agent_plan,
        environment_variables,
    )
    effective_local_environment_variable_names = (
        _agent_local_environment_variable_names(
            container_configuration,
            agent_plan,
            local_environment_variable_names,
        )
    )
    output_mount_source = (
        run_directory if output_directory is None else output_directory
    )
    mount = f"type=bind,source={output_mount_source},target={_REMOTE_OUTPUT_DIRECTORY}"
    source_mount = _build_source_mount(container_configuration)
    command = [
        _DOCKER_EXECUTABLE,
        "run",
        "--name",
        container_name,
        "--init",
    ]
    if detached:
        command.append("--detach")
    else:
        command.append("--interactive")
    command.extend(_build_ipc_options(container_configuration))
    command.extend(_build_security_options(container_configuration, run_directory))
    command.extend(
        [
            "--mount",
            mount,
            "--mount",
            source_mount,
            "--user",
            container_configuration.guest_user,
        ]
    )
    command.extend(
        _build_shared_volume_mount_options(container_configuration, run_directory)
    )
    if network_name is not None:
        command.extend(["--network", network_name])
        if network_alias is not None:
            command.extend(["--network-alias", network_alias])
        effective_agent_plan = _get_effective_agent_plan(
            container_configuration,
            agent_plan,
        )
        if (
            effective_agent_plan is not None
            and effective_agent_plan.ip_address is not None
        ):
            command.extend(["--ip", effective_agent_plan.ip_address])
    command.extend(
        _build_dns_policy_options(container_configuration, gateway_ip_address)
    )
    command.extend(container_configuration.profile.container_run_options)
    command.extend(
        _build_readonly_denied_mount_options(container_configuration, run_directory)
    )
    command.extend(
        _build_readonly_persistence_mount_options(
            container_configuration,
            run_directory,
        )
    )
    command.extend(_build_socket_mount_options(container_configuration))
    command.extend(_build_agent_socket_mount_options(container_configuration))
    command.extend(
        _build_denied_executable_mount_options(
            container_configuration,
            run_directory,
        )
    )
    command.extend(
        _build_environment_options(
            _build_container_environment(
                container_configuration,
                effective_environment_variables,
                gateway_ip_address,
                agent_plan=agent_plan,
            ),
            _build_effective_local_environment_variable_names(
                container_configuration,
                effective_local_environment_variable_names,
            ),
        )
    )
    command.extend(
        [
            container_configuration.profile.image_name,
            "/bin/sh",
            "-c",
            _build_container_script(
                run_target=container_configuration.run_target,
                remote_run_directory=remote_run_directory,
                allowed_directory=(
                    allowed_directory
                    if allowed_directory is not None
                    else _build_allowed_directory(
                        container_configuration,
                        remote_run_directory,
                    )
                ),
                denied_directory=(
                    denied_directory
                    if denied_directory is not None
                    else _build_denied_directory(
                        container_configuration,
                        remote_run_directory,
                    )
                ),
                create_denied_fixture=(
                    container_configuration.profile.readonly_denied_mount_target is None
                ),
                verbose=verbose,
                serialize_evidence=serialize_evidence,
                landlock_policy_path=(
                    _REMOTE_LANDLOCK_POLICY_PATH
                    if container_configuration.profile.landlock_rules
                    else None
                ),
                agent_module=(
                    agent_plan.module if agent_plan is not None else "sandbox_agent"
                ),
                module_arguments=module_arguments,
            ),
        ]
    )
    return command


def _agent_container_configuration(
    configuration: DockerConfiguration,
    agent_plan: ResolvedAgentPlan | None,
) -> DockerConfiguration:
    image_configuration = _agent_image_configuration(configuration, agent_plan)
    if image_configuration is None:
        return configuration

    return replace(
        configuration,
        dockerfile_path=image_configuration.dockerfile_path,
        profile=image_configuration.profile,
        generated_dockerfile=image_configuration.generated_dockerfile,
        resolved_spec=image_configuration.resolved_spec,
        environment_variables=image_configuration.environment_variables,
        local_environment_variable_names=(
            image_configuration.local_environment_variable_names
        ),
        enabled_capabilities=image_configuration.enabled_capabilities,
    )


def _agent_image_configuration(
    configuration: DockerConfiguration,
    agent_plan: ResolvedAgentPlan | None,
) -> AgentImageConfiguration | None:
    if agent_plan is None:
        return None

    for image_configuration in configuration.agent_image_configurations:
        if image_configuration.agent_id == agent_plan.agent_id:
            return image_configuration

    return None


def _agent_environment_variables(
    configuration: DockerConfiguration,
    agent_plan: ResolvedAgentPlan | None,
    environment_variables: dict[str, str] | None,
) -> dict[str, str]:
    if agent_plan is None:
        return environment_variables or {}
    if not configuration.agent_image_configurations:
        return environment_variables or {}

    return dict(configuration.environment_variables)


def _agent_local_environment_variable_names(
    configuration: DockerConfiguration,
    agent_plan: ResolvedAgentPlan | None,
    local_environment_variable_names: Set[str] | None,
) -> Set[str]:
    if agent_plan is None:
        return local_environment_variable_names or frozenset()
    if not configuration.agent_image_configurations:
        return local_environment_variable_names or frozenset()

    return configuration.local_environment_variable_names


def _build_ipc_options(configuration: DockerConfiguration) -> list[str]:
    options = []
    if configuration.profile.ipc_mode is not None:
        options.append(f"--ipc={configuration.profile.ipc_mode}")

    if configuration.profile.shm_size is not None:
        options.extend(["--shm-size", configuration.profile.shm_size])

    return options


def _build_security_options(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> list[str]:
    options = []
    if configuration.profile.cgroupns_mode is not None:
        options.append(f"--cgroupns={configuration.profile.cgroupns_mode}")

    if configuration.profile.pids_limit is not None:
        options.extend(["--pids-limit", str(configuration.profile.pids_limit)])

    if configuration.profile.memory is not None:
        options.extend(["--memory", configuration.profile.memory])

    if configuration.profile.memory_swap is not None:
        options.extend(["--memory-swap", configuration.profile.memory_swap])

    if configuration.profile.cpus is not None:
        options.extend(["--cpus", configuration.profile.cpus])

    for ulimit in configuration.profile.ulimits:
        options.extend(
            [
                "--ulimit",
                f"{ulimit.name}={ulimit.soft}:{ulimit.hard}",
            ]
        )

    for sysctl in configuration.profile.sysctls:
        options.extend(["--sysctl", f"{sysctl.name}={sysctl.value}"])

    for capability in configuration.profile.cap_drop:
        options.append(f"--cap-drop={capability}")

    for capability in configuration.profile.cap_add:
        options.append(f"--cap-add={capability}")

    for security_option in configuration.profile.security_options:
        options.extend(["--security-opt", security_option])

    if configuration.profile.seccomp_profile is not None:
        seccomp_path = run_directory / _SECCOMP_PROFILE_FILE_NAME
        options.extend(["--security-opt", f"seccomp={seccomp_path}"])

    return options


def _build_dns_policy_options(
    configuration: DockerConfiguration,
    gateway_ip_address: str | None,
) -> list[str]:
    dns_policy = configuration.profile.network_dns_policy
    if dns_policy is None:
        return []

    options: list[str] = []
    dns_address = _get_dns_policy_address(dns_policy, gateway_ip_address)
    options.extend(["--dns", dns_address])
    for dns_option in dns_policy.dns_options:
        options.extend(["--dns-option", dns_option])

    for hostname in dns_policy.blocked_hostnames:
        options.extend(
            [
                "--add-host",
                f"{hostname}:{dns_policy.blocked_hostname_address}",
            ]
        )

    return options


def _get_dns_policy_address(
    dns_policy: NetworkDnsPolicy,
    gateway_ip_address: str | None,
) -> str:
    if dns_policy.use_gateway_as_dns and gateway_ip_address is not None:
        return gateway_ip_address

    return dns_policy.fallback_dns_address


def _build_source_mount(configuration: DockerConfiguration) -> str:
    source_directory = configuration.build_context / "src"
    return (
        f"type=bind,source={source_directory},"
        f"target={_REMOTE_SOURCE_DIRECTORY},readonly"
    )


def _build_shared_volume_mount_options(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> list[str]:
    if _SHARED_VOLUME_CAPABILITY not in configuration.enabled_capabilities:
        return []

    shared_directory = run_directory / _SHARED_DIRECTORY_NAME
    shared_directory.mkdir(parents=True, exist_ok=True)
    mount = f"type=bind,source={shared_directory},target={_REMOTE_SHARED_DIRECTORY}"
    return ["--mount", mount]


def _build_container_environment(
    configuration: DockerConfiguration,
    environment_variables: Mapping[str, str],
    gateway_ip_address: str | None = None,
    agent_plan: ResolvedAgentPlan | None = None,
) -> dict[str, str]:
    container_environment = dict(environment_variables)
    container_environment["PYTHONPATH"] = _REMOTE_SOURCE_DIRECTORY
    container_environment["PYTHONUNBUFFERED"] = "1"
    container_environment[CONTAINER_MARKER_ENVIRONMENT_VARIABLE] = (
        CONTAINER_MARKER_VALUE
    )
    if _SHARED_VOLUME_CAPABILITY in configuration.enabled_capabilities:
        container_environment[_SHARED_DIRECTORY_ENVIRONMENT_VARIABLE] = (
            _REMOTE_SHARED_DIRECTORY
        )
    ssh_agent_socket = _get_container_ssh_agent_socket(configuration)
    if ssh_agent_socket is not None:
        container_environment["SSH_AUTH_SOCK"] = ssh_agent_socket

    gpg_home = _get_container_gpg_home(configuration)
    if gpg_home is not None:
        container_environment["GNUPGHOME"] = gpg_home

    _apply_environment_policies(
        container_environment,
        configuration.profile.environment,
    )
    _apply_desktop_automation_policy(
        container_environment,
        configuration.profile.allow_desktop_automation_channel,
    )
    gateway = configuration.profile.network_gateway
    if gateway is not None:
        proxy_host = gateway_ip_address or gateway.proxy_host
        proxy_url = f"http://{proxy_host}:{gateway.proxy_port}"
        no_proxy_hosts = _build_agent_no_proxy_hosts(configuration, gateway)
        no_proxy = ",".join(dict.fromkeys(no_proxy_hosts))
        container_environment["HTTP_PROXY"] = proxy_url
        container_environment["HTTPS_PROXY"] = proxy_url
        container_environment["NO_PROXY"] = no_proxy
        container_environment["http_proxy"] = proxy_url
        container_environment["https_proxy"] = proxy_url
        container_environment["no_proxy"] = no_proxy
    if _should_start_mcp_sidecar(configuration):
        mcp_sidecar_url = f"http://{_MCP_SIDECAR_ALIAS}:{_MCP_SIDECAR_PORT}/mcp"
        container_environment[_MCP_SIDECAR_URL_ENVIRONMENT_VARIABLE] = mcp_sidecar_url
    if _should_start_ollama_sidecar(configuration):
        ollama_base_url = f"http://{_OLLAMA_SIDECAR_ALIAS}:{_OLLAMA_SIDECAR_PORT}"
        container_environment[_OLLAMA_BASE_URL_ENVIRONMENT_VARIABLE] = ollama_base_url
        container_environment[_OLLAMA_MODEL_ENVIRONMENT_VARIABLE] = (
            configuration.ollama_models[0]
        )
        container_environment[_OPENAI_BASE_URL_ENVIRONMENT_VARIABLE] = (
            f"{ollama_base_url}/v1"
        )
        container_environment[_OPENAI_API_KEY_ENVIRONMENT_VARIABLE] = (
            _OLLAMA_OPENAI_API_KEY
        )
    _apply_plan_agent_environment(
        configuration,
        container_environment,
        agent_plan=agent_plan,
    )
    _remove_agent_database_environment(container_environment)
    return container_environment


def _get_primary_agent_plan(
    configuration: DockerConfiguration,
) -> ResolvedAgentPlan | None:
    plan = configuration.resolved_sandbox_plan
    if plan is None or not plan.agents:
        return None

    return plan.agents[0]


def _get_effective_agent_plan(
    configuration: DockerConfiguration,
    agent_plan: ResolvedAgentPlan | None,
) -> ResolvedAgentPlan | None:
    if agent_plan is not None:
        return agent_plan

    return _get_primary_agent_plan(configuration)


def _apply_plan_agent_environment(
    configuration: DockerConfiguration,
    environment: dict[str, str],
    agent_plan: ResolvedAgentPlan | None = None,
) -> None:
    agent_plan = _get_effective_agent_plan(configuration, agent_plan)
    if agent_plan is None:
        return

    if agent_plan.mcp_sidecar_url is not None:
        environment[_MCP_SIDECAR_URL_ENVIRONMENT_VARIABLE] = agent_plan.mcp_sidecar_url
    if agent_plan.http_proxy is not None:
        environment["HTTP_PROXY"] = agent_plan.http_proxy
        environment["http_proxy"] = agent_plan.http_proxy
    if agent_plan.https_proxy is not None:
        environment["HTTPS_PROXY"] = agent_plan.https_proxy
        environment["https_proxy"] = agent_plan.https_proxy
    if agent_plan.no_proxy:
        no_proxy = ",".join(agent_plan.no_proxy)
        environment["NO_PROXY"] = no_proxy
        environment["no_proxy"] = no_proxy


def _remove_agent_database_environment(environment: dict[str, str]) -> None:
    for name in (
        _MARIADB_HOST_ENVIRONMENT_VARIABLE,
        _MARIADB_PORT_ENVIRONMENT_VARIABLE,
        _MARIADB_DATABASE_ENVIRONMENT_VARIABLE,
        _MARIADB_CREDENTIALS_ENVIRONMENT_VARIABLE,
    ):
        environment.pop(name, None)


def _build_agent_no_proxy_hosts(
    configuration: DockerConfiguration,
    gateway: NetworkGatewayProfile,
) -> tuple[str, ...]:
    hosts = ["localhost", "127.0.0.1", *gateway.no_proxy_hosts]
    if _should_start_mcp_sidecar(configuration):
        hosts.append(_MCP_SIDECAR_ALIAS)
    if _should_start_ollama_sidecar(configuration):
        hosts.append(_OLLAMA_SIDECAR_ALIAS)

    return tuple(hosts)


def _build_effective_local_environment_variable_names(
    configuration: DockerConfiguration,
    local_environment_variable_names: Set[str],
) -> Set[str]:
    names = set(local_environment_variable_names)
    if _should_start_ollama_sidecar(configuration):
        names.discard(_OPENAI_API_KEY_ENVIRONMENT_VARIABLE)
    names.difference_update(
        {
            _MARIADB_HOST_ENVIRONMENT_VARIABLE,
            _MARIADB_PORT_ENVIRONMENT_VARIABLE,
            _MARIADB_DATABASE_ENVIRONMENT_VARIABLE,
            _MARIADB_CREDENTIALS_ENVIRONMENT_VARIABLE,
        }
    )

    return names


def _apply_environment_policies(
    environment: dict[str, str],
    policies: tuple[EnvironmentVariablePolicy, ...],
) -> None:
    for policy in policies:
        if policy.value is None:
            environment.pop(policy.name, None)
            continue

        environment[policy.name] = policy.value


def _apply_desktop_automation_policy(
    environment: dict[str, str],
    allow_desktop_automation_channel: bool,
) -> None:
    if allow_desktop_automation_channel:
        return

    for name in _DESKTOP_AUTOMATION_ENVIRONMENT_NAMES:
        environment.pop(name, None)


def _build_readonly_denied_mount_options(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> list[str]:
    target = configuration.profile.readonly_denied_mount_target
    if target is None:
        return []

    source = run_directory / _READONLY_DENIED_SOURCE_DIRECTORY
    mount = f"type=bind,source={source},target={target},readonly"
    return [
        "--mount",
        mount,
    ]


def _build_readonly_persistence_mount_options(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> list[str]:
    options = []
    for target in configuration.profile.readonly_persistence_directories:
        _validate_container_directory(target)
        source = _build_readonly_persistence_source_directory(run_directory, target)
        mount = f"type=bind,source={source},target={target},readonly"
        options.extend(
            [
                "--mount",
                mount,
            ]
        )

    return options


def _build_socket_mount_options(configuration: DockerConfiguration) -> list[str]:
    options = []
    for socket_mount in configuration.profile.socket_mounts:
        options.extend(
            [
                "--mount",
                _build_socket_mount_option(socket_mount),
            ]
        )

    return options


def _build_agent_socket_mount_options(configuration: DockerConfiguration) -> list[str]:
    options = []
    for agent_socket in _get_agent_socket_forwards(configuration):
        options.extend(
            [
                "--mount",
                _build_agent_socket_mount_option(agent_socket),
            ]
        )

    return options


def _get_agent_socket_forwards(
    configuration: DockerConfiguration,
) -> tuple[AgentSocketForward, ...]:
    forwards = []
    if configuration.profile.ssh_agent_socket is not None:
        forwards.append(configuration.profile.ssh_agent_socket)

    if configuration.profile.gpg_agent_socket is not None:
        forwards.append(configuration.profile.gpg_agent_socket)

    return tuple(forwards)


def _build_agent_socket_mount_option(agent_socket: AgentSocketForward) -> str:
    return (
        f"type=bind,source={agent_socket.source_path},target={agent_socket.target_path}"
    )


def _build_denied_executable_mount_options(
    configuration: DockerConfiguration,
    run_directory: Path,
) -> list[str]:
    options = []
    for target_path in _get_denied_executable_targets(configuration):
        source_path = (
            run_directory
            / _DENIED_EXECUTABLE_SOURCE_DIRECTORY
            / _build_denied_executable_stub_name(target_path)
        )
        options.extend(
            [
                "--mount",
                f"type=bind,source={source_path},target={target_path},readonly",
            ]
        )

    return options


def _build_socket_mount_option(socket_mount: SocketMount) -> str:
    mount = (
        f"type=bind,source={socket_mount.source_path},target={socket_mount.target_path}"
    )
    if socket_mount.readonly:
        mount = f"{mount},readonly"

    return mount


def _get_container_ssh_agent_socket(
    configuration: DockerConfiguration,
) -> str | None:
    ssh_agent_socket = configuration.profile.ssh_agent_socket
    if ssh_agent_socket is None:
        return None

    return ssh_agent_socket.target_path


def _get_container_gpg_home(configuration: DockerConfiguration) -> str | None:
    gpg_agent_socket = configuration.profile.gpg_agent_socket
    if gpg_agent_socket is None:
        return None

    return str(PurePosixPath(gpg_agent_socket.target_path).parent)


def _build_container_script(
    run_target: SandboxRunTarget,
    remote_run_directory: str,
    allowed_directory: str | None = None,
    denied_directory: str | None = None,
    create_denied_fixture: bool = True,
    verbose: bool = False,
    serialize_evidence: bool = False,
    landlock_policy_path: str | None = None,
    agent_module: str = "sandbox_agent",
    module_arguments: tuple[str, ...] = (),
) -> str:
    if allowed_directory is None:
        allowed_directory = f"{remote_run_directory}/allowed"
    if denied_directory is None:
        denied_directory = f"{remote_run_directory}/denied"

    allowed_child_directory = f"{allowed_directory}/allowed"
    denied_child_directory = f"{denied_directory}/denied"
    arguments = _build_sandbox_command_arguments(
        run_target,
        landlock_policy_path,
        agent_module=agent_module,
        module_arguments=module_arguments,
    )
    if verbose:
        arguments.append("--verbose")
    if serialize_evidence:
        arguments.append("--serialize-evidence")

    lines = [
        "set -eu",
        'if [ -n "${HOME:-}" ]; then mkdir -p "$HOME"; fi',
        'if [ -n "${XDG_CACHE_HOME:-}" ]; then mkdir -p "$XDG_CACHE_HOME"; fi',
        'if [ -n "${XDG_CONFIG_HOME:-}" ]; then mkdir -p "$XDG_CONFIG_HOME"; fi',
        (
            'if [ -n "${GNUPGHOME:-}" ]; then '
            'mkdir -p "$GNUPGHOME"; '
            'chmod 700 "$GNUPGHOME"; '
            "fi"
        ),
        (
            'if [ -n "${XDG_RUNTIME_DIR:-}" ]; then '
            'mkdir -p "$XDG_RUNTIME_DIR"; '
            'chmod 700 "$XDG_RUNTIME_DIR"; '
            "fi"
        ),
        f"mkdir -p {shlex.quote(allowed_child_directory)}",
        _build_write_text_command(
            f"{allowed_child_directory}/allowed.txt",
            _ALLOWED_FILE_CONTENT,
        ),
        _build_write_text_command(
            f"{allowed_child_directory}/.hidden",
            _HIDDEN_ALLOWED_FILE_CONTENT,
        ),
        " ".join(shlex.quote(argument) for argument in arguments),
    ]
    if create_denied_fixture:
        lines.insert(-1, f"mkdir -p {shlex.quote(denied_child_directory)}")
        lines.insert(
            -1,
            _build_write_text_command(
                f"{denied_child_directory}/denied.txt",
                _DENIED_FILE_CONTENT,
            ),
        )
        lines.insert(
            -1,
            _build_write_text_command(
                f"{denied_child_directory}/.hidden",
                _HIDDEN_DENIED_FILE_CONTENT,
            ),
        )
    return "\n".join(lines)


def _build_sandbox_command_arguments(
    run_target: SandboxRunTarget,
    landlock_policy_path: str | None,
    agent_module: str = "sandbox_agent",
    module_arguments: tuple[str, ...] = (),
) -> list[str]:
    if landlock_policy_path is None:
        if run_target == SandboxRunTarget.TESTER:
            return [
                "python",
                "-m",
                "sandbox_tester",
                "--config",
                f"{_REMOTE_OUTPUT_DIRECTORY}/config.json",
            ]

        return [
            "python",
            "-m",
            agent_module,
            *module_arguments,
        ]

    arguments = [
        "python",
        "-m",
        "docker_sandbox.landlock_runner",
        "--config",
        f"{_REMOTE_OUTPUT_DIRECTORY}/config.json",
        "--policy",
        landlock_policy_path,
        "--target",
        run_target.value,
        "--module",
        agent_module,
    ]
    for module_argument in module_arguments:
        arguments.append(f"--module-arg={module_argument}")

    return arguments


def _build_write_text_command(path: str, content: str) -> str:
    quoted_content = shlex.quote(content)
    quoted_path = shlex.quote(path)
    return f"printf '%s' {quoted_content} > {quoted_path}"


def _build_docker_remove_command(container_name: str) -> list[str]:
    return [
        _DOCKER_EXECUTABLE,
        "rm",
        "--force",
        container_name,
    ]


def _resolve_environment_variables(
    configured_variables: Mapping[str, str],
    host_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source_environment = os.environ if host_environment is None else host_environment
    environment_variables: dict[str, str] = {}

    for name, value in configured_variables.items():
        if value == _LOCAL_ENVIRONMENT_VALUE:
            local_value = source_environment.get(name)
            if local_value is not None:
                environment_variables[name] = local_value
            continue

        environment_variables[name] = value

    return environment_variables


def _get_local_environment_variable_names(
    configured_variables: Mapping[str, str],
) -> set[str]:
    return {
        name
        for name, value in configured_variables.items()
        if value == _LOCAL_ENVIRONMENT_VALUE
    }


def _build_environment_options(
    environment_variables: Mapping[str, str],
    local_environment_variable_names: Set[str],
) -> list[str]:
    options: list[str] = []

    for name, value in sorted(environment_variables.items()):
        if name in local_environment_variable_names:
            options.extend(["--env", name])
            continue

        options.extend(["--env", f"{name}={value}"])

    return options


def _run_interactive_command(command: list[str]) -> _InteractiveProcessResult:
    process = subprocess.Popen(
        command,
        stdin=None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    stdout_thread = _start_stream_thread(process.stdout, sys.stdout, stdout_chunks)
    stderr_thread = _start_stream_thread(process.stderr, sys.stderr, stderr_chunks)
    returncode = process.wait()
    stdout_thread.join()
    stderr_thread.join()

    return _InteractiveProcessResult(
        returncode=returncode,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
    )


def _start_stream_thread(
    source: IO[Any] | None,
    destination: TextIO,
    chunks: list[str],
) -> threading.Thread:
    thread = threading.Thread(
        target=_stream_text,
        args=(source, destination, chunks),
        daemon=True,
    )
    thread.start()
    return thread


def _stream_text(
    source: IO[Any] | None,
    destination: TextIO,
    chunks: list[str],
) -> None:
    if source is None:
        return

    while True:
        chunk = source.read(1)
        if chunk == "":
            return

        chunks.append(chunk)
        destination.write(chunk)
        destination.flush()
