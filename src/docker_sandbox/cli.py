"""Command-line interface for Docker sandbox experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from .container_factory import ensure_base_images
from .models import (
    AgentImageConfiguration,
    DockerConfiguration,
    DockerImageResult,
    DockerImageStatus,
    DockerRunResult,
    HAProxyConfiguration,
    SandboxRunTarget,
)
from .profiles import SUPPORTED_PROFILE_NAMES, get_docker_profile
from .run_results import save_run_results
from .sandbox_container import run_sandbox_container
from .sandbox_plan import (
    AgentSpec,
    SandboxRunSpec,
    load_agent_spec,
    load_sandbox_run_spec,
)
from .sandbox_spec import (
    SandboxEnvironmentVariable,
    SandboxSpec,
    generate_dockerfile,
    resolve_environment_variables,
    resolve_local_environment_variable_names,
    resolve_profile,
)

_DEFAULT_BASE_DIRECTORY = Path(".docker_sandbox")
_DEFAULT_DOCKERFILE = Path("src") / "docker_sandbox" / "dockerfile" / "Dockerfile"
_DEFAULT_SANDBOX_RUN_SPEC = Path("src") / "sandbox_agent" / "sandbox_run.toml"
_DEFAULT_GUEST_USER = "sandbox"


def main(arguments: list[str] | None = None) -> int:
    """Run the Docker sandbox command-line interface."""
    parsed_arguments = _parse_arguments(arguments)
    configuration = _configuration_from_arguments(parsed_arguments)
    image_results = ensure_base_images(configuration)
    for image_result in image_results:
        _print_image_result(image_result)

    if any(
        result.status not in {DockerImageStatus.EXISTS, DockerImageStatus.CREATED}
        for result in image_results
    ):
        return 1

    run_result = run_sandbox_container(
        configuration,
        verbose=parsed_arguments.verbose,
        serialize_evidence=parsed_arguments.serialize_evidence,
    )
    save_run_results(run_result)
    print(f"Run results saved to: {run_result.run_directory}")

    if parsed_arguments.keep_container:
        print(f"Kept disposable Docker container '{run_result.container_name}'.")
    else:
        run_result.remove_container()
        print(f"Removed disposable Docker container '{run_result.container_name}'.")

    return _exit_code_from_run_result(run_result)


def _parse_arguments(arguments: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Sandbox Agent in a Docker sandbox."
    )
    parser.add_argument(
        "--base-directory",
        type=Path,
        default=_DEFAULT_BASE_DIRECTORY,
        help=(
            f"Host directory for Docker sandbox files. Default: "
            f"{_DEFAULT_BASE_DIRECTORY}"
        ),
    )
    parser.add_argument(
        "--dockerfile",
        type=Path,
        default=_DEFAULT_DOCKERFILE,
        help=f"Dockerfile used to build the image. Default: {_DEFAULT_DOCKERFILE}",
    )
    parser.add_argument(
        "--guest-user",
        default=_DEFAULT_GUEST_USER,
        help=(
            "Container user used to run Sandbox Agent. The default image creates "
            f"this user as '{_DEFAULT_GUEST_USER}'."
        ),
    )
    parser.add_argument(
        "--profile",
        choices=SUPPORTED_PROFILE_NAMES,
        default=None,
        help=(
            "Legacy Docker hardening profile to apply instead of the sandbox spec. "
            f"Supported profiles: {', '.join(SUPPORTED_PROFILE_NAMES)}"
        ),
    )
    parser.add_argument(
        "--sandbox-run-spec",
        type=Path,
        default=_DEFAULT_SANDBOX_RUN_SPEC,
        help=f"Declarative sandbox run spec. Default: {_DEFAULT_SANDBOX_RUN_SPEC}",
    )
    parser.add_argument(
        "--keep-container",
        action="store_true",
        help="Keep the disposable container after execution instead of removing it.",
    )
    parser.add_argument(
        "--test-sandbox",
        action="store_true",
        help="Run the sandbox_tester probe suite instead of Sandbox Agent.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Pass verbose progress output through to Sandbox Agent.",
    )
    parser.add_argument(
        "--serialize-evidence",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(arguments)


def _configuration_from_arguments(
    arguments: argparse.Namespace,
) -> DockerConfiguration:
    repository_root = Path.cwd().resolve()
    base_directory = arguments.base_directory.expanduser().resolve()
    if arguments.profile is not None:
        dockerfile_path = arguments.dockerfile.expanduser()
        if not dockerfile_path.is_absolute():
            dockerfile_path = repository_root / dockerfile_path
        profile = get_docker_profile(arguments.profile)
        return DockerConfiguration(
            base_directory=base_directory,
            dockerfile_path=dockerfile_path.resolve(),
            build_context=repository_root,
            guest_user=arguments.guest_user,
            profile=profile,
        )

    sandbox_run_spec_path = arguments.sandbox_run_spec.expanduser()
    if not sandbox_run_spec_path.is_absolute():
        sandbox_run_spec_path = repository_root / sandbox_run_spec_path

    sandbox_run_spec = load_sandbox_run_spec(sandbox_run_spec_path.resolve())
    agent_specs = tuple(
        load_agent_spec(agent_spec_path)
        for agent_spec_path in sandbox_run_spec.agent_spec_paths
    )
    spec = _sandbox_spec_from_run(sandbox_run_spec, agent_specs)
    profile = resolve_profile(spec)
    run_target = (
        SandboxRunTarget.TESTER if arguments.test_sandbox else SandboxRunTarget.AGENT
    )
    image_tag = spec.image_tag
    if run_target == SandboxRunTarget.TESTER:
        image_tag = f"{image_tag}-test-sandbox"
        profile = replace(
            profile,
            name=f"{profile.name}-test-sandbox",
            image_name=f"sandbox-agent/sandbox-agent:{image_tag}",
        )

    generated_dockerfile = generate_dockerfile(
        spec,
        include_probe_dependencies=run_target == SandboxRunTarget.TESTER,
    )
    dockerfile_path = base_directory / "generated" / image_tag / "Dockerfile"
    dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
    dockerfile_path.write_text(f"{generated_dockerfile.rstrip()}\n", encoding="utf-8")
    agent_image_configurations = _agent_image_configurations_from_run(
        run_spec=sandbox_run_spec,
        agent_specs=agent_specs,
        base_directory=base_directory,
        run_target=run_target,
    )

    return DockerConfiguration(
        base_directory=base_directory,
        dockerfile_path=dockerfile_path.resolve(),
        build_context=repository_root,
        guest_user=arguments.guest_user,
        profile=profile,
        generated_dockerfile=generated_dockerfile,
        resolved_spec=spec.to_dict()
        | {
            "image_name": profile.image_name,
            "ollama_image_name": spec.ollama_image_name,
            "test_sandbox": run_target == SandboxRunTarget.TESTER,
        },
        environment_variables=resolve_environment_variables(spec),
        local_environment_variable_names=resolve_local_environment_variable_names(spec),
        run_target=run_target,
        enabled_capabilities=frozenset(spec.capabilities),
        mcp_sidecar_tools=spec.mcp_sidecar_tools,
        mcp_sidecar_resources=spec.mcp_sidecar_resources,
        mcp_sidecar_container_capabilities=(
            sandbox_run_spec.mcp_sidecar.container_capabilities
        ),
        mcp_sidecar_application_capabilities=(
            sandbox_run_spec.mcp_sidecar.application_capabilities
        ),
        haproxy=spec.haproxy,
        ollama_models=spec.ollama_models,
        ollama_image_name=spec.ollama_image_name,
        sandbox_run_spec=sandbox_run_spec,
        agent_specs=agent_specs,
        agent_image_configurations=agent_image_configurations,
    )


def _sandbox_spec_from_run(
    run_spec: SandboxRunSpec,
    agent_specs: tuple[AgentSpec, ...],
) -> SandboxSpec:
    if not agent_specs:
        raise ValueError("The sandbox run must declare at least one agent.")

    capabilities = _merge_capabilities(run_spec, agent_specs)
    environment_variables = _merge_environment_variables(agent_specs)
    haproxy_ports = tuple(
        dict.fromkeys(
            (
                *run_spec.haproxy.default_ports,
                *(port for agent in agent_specs for port in agent.haproxy.ports),
            )
        )
    )
    haproxy = None
    if haproxy_ports:
        haproxy = HAProxyConfiguration(
            backend_host=run_spec.haproxy.backend_host,
            ports=haproxy_ports,
        )

    return SandboxSpec(
        schema_version=run_spec.schema_version,
        capabilities=tuple(dict.fromkeys(capabilities)),
        allowed_domains=tuple(
            dict.fromkeys(
                (
                    *run_spec.squid_proxy.default_allowed_domains,
                    *(
                        domain
                        for agent in agent_specs
                        for domain in agent.squid_proxy.allowed_domains
                    ),
                )
            )
        ),
        allowed_ip_addresses=tuple(
            dict.fromkeys(
                (
                    *run_spec.squid_proxy.default_allowed_ip_addresses,
                    *(
                        ip_address
                        for agent in agent_specs
                        for ip_address in agent.squid_proxy.allowed_ip_addresses
                    ),
                )
            )
        ),
        environment_variables=environment_variables,
        mcp_sidecar_tools=tuple(
            dict.fromkeys(
                (
                    *run_spec.mcp_sidecar.default_tools,
                    *(
                        tool
                        for agent in agent_specs
                        for tool in agent.mcp_sidecar.tools
                    ),
                )
            )
        ),
        mcp_sidecar_resources=tuple(
            dict.fromkeys(
                (
                    *run_spec.mcp_sidecar.default_resources,
                    *(
                        resource
                        for agent in agent_specs
                        for resource in agent.mcp_sidecar.resources
                    ),
                )
            )
        ),
        haproxy=haproxy,
    )


def _agent_image_configurations_from_run(
    run_spec: SandboxRunSpec,
    agent_specs: tuple[AgentSpec, ...],
    base_directory: Path,
    run_target: SandboxRunTarget,
) -> tuple[AgentImageConfiguration, ...]:
    configurations = []
    for agent_spec in agent_specs:
        spec = _agent_sandbox_spec_from_run(run_spec, agent_spec)
        image_tag = _agent_image_tag(run_spec, agent_spec, spec)
        if run_target == SandboxRunTarget.TESTER:
            image_tag = f"{image_tag}-test-sandbox"

        image_name = f"sandbox-agent/sandbox-agent:{image_tag}"
        profile = resolve_profile(spec)
        profile = replace(
            profile,
            name=f"sandbox-spec-{image_tag}",
            image_name=image_name,
        )
        generated_dockerfile = generate_dockerfile(
            spec,
            include_probe_dependencies=run_target == SandboxRunTarget.TESTER,
        )
        dockerfile_path = base_directory / "generated" / image_tag / "Dockerfile"
        dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
        dockerfile_path.write_text(
            f"{generated_dockerfile.rstrip()}\n",
            encoding="utf-8",
        )
        configurations.append(
            AgentImageConfiguration(
                agent_id=agent_spec.agent_id,
                dockerfile_path=dockerfile_path.resolve(),
                profile=profile,
                generated_dockerfile=generated_dockerfile,
                resolved_spec=spec.to_dict()
                | {
                    "image_name": profile.image_name,
                    "test_sandbox": run_target == SandboxRunTarget.TESTER,
                },
                environment_variables=resolve_environment_variables(spec),
                local_environment_variable_names=(
                    resolve_local_environment_variable_names(spec)
                ),
                enabled_capabilities=frozenset(spec.capabilities),
            )
        )

    return tuple(configurations)


def _agent_sandbox_spec_from_run(
    run_spec: SandboxRunSpec,
    agent_spec: AgentSpec,
) -> SandboxSpec:
    capabilities = agent_spec.capabilities
    if agent_spec.haproxy.ports or run_spec.haproxy.default_ports:
        capabilities = (*capabilities, "haproxy")

    return SandboxSpec(
        schema_version=run_spec.schema_version,
        capabilities=tuple(dict.fromkeys(capabilities)),
        allowed_domains=tuple(
            dict.fromkeys(
                (
                    *run_spec.squid_proxy.default_allowed_domains,
                    *agent_spec.squid_proxy.allowed_domains,
                )
            )
        ),
        allowed_ip_addresses=tuple(
            dict.fromkeys(
                (
                    *run_spec.squid_proxy.default_allowed_ip_addresses,
                    *agent_spec.squid_proxy.allowed_ip_addresses,
                )
            )
        ),
        environment_variables=tuple(
            SandboxEnvironmentVariable(name=name, value=value)
            for name, value in agent_spec.environment_variables
        ),
        mcp_sidecar_tools=tuple(
            dict.fromkeys(
                (
                    *run_spec.mcp_sidecar.default_tools,
                    *agent_spec.mcp_sidecar.tools,
                )
            )
        ),
        mcp_sidecar_resources=tuple(
            dict.fromkeys(
                (
                    *run_spec.mcp_sidecar.default_resources,
                    *agent_spec.mcp_sidecar.resources,
                )
            )
        ),
        haproxy=HAProxyConfiguration(
            backend_host=run_spec.haproxy.backend_host,
            ports=tuple(
                dict.fromkeys(
                    (*run_spec.haproxy.default_ports, *agent_spec.haproxy.ports)
                )
            ),
        )
        if run_spec.haproxy.default_ports or agent_spec.haproxy.ports
        else None,
    )


def _agent_image_tag(
    run_spec: SandboxRunSpec,
    agent_spec: AgentSpec,
    spec: SandboxSpec,
) -> str:
    digest = hashlib.sha256(
        _agent_image_normalized_json(run_spec, agent_spec, spec).encode("utf-8")
    ).hexdigest()
    return f"{run_spec.schema_version}-{digest[:16]}"


def _agent_image_normalized_json(
    run_spec: SandboxRunSpec,
    agent_spec: AgentSpec,
    spec: SandboxSpec,
) -> str:
    data = {
        "agent": {
            "application_capabilities": list(agent_spec.application_capabilities),
            "container_capabilities": list(agent_spec.container_capabilities),
            "environment_variables": [
                {"name": name, "value": value}
                for name, value in agent_spec.environment_variables
            ],
            "haproxy": {
                "ports": list(agent_spec.haproxy.ports),
            },
            "mcp_sidecar": {
                "resources": list(agent_spec.mcp_sidecar.resources),
                "tools": list(agent_spec.mcp_sidecar.tools),
            },
            "squid_proxy": {
                "allowed_domains": list(agent_spec.squid_proxy.allowed_domains),
                "allowed_ip_addresses": list(
                    agent_spec.squid_proxy.allowed_ip_addresses
                ),
            },
        },
        "run": {
            "haproxy": {
                "backend_host": run_spec.haproxy.backend_host,
                "default_ports": list(run_spec.haproxy.default_ports),
            },
            "mcp_sidecar": {
                "default_resources": list(run_spec.mcp_sidecar.default_resources),
                "default_tools": list(run_spec.mcp_sidecar.default_tools),
            },
            "network": {
                "enabled": run_spec.network.enabled,
                "internal": run_spec.network.internal,
                "subnet": run_spec.network.subnet,
            },
            "schema_version": run_spec.schema_version,
            "squid_proxy": {
                "default_allowed_domains": list(
                    run_spec.squid_proxy.default_allowed_domains
                ),
                "default_allowed_ip_addresses": list(
                    run_spec.squid_proxy.default_allowed_ip_addresses
                ),
            },
        },
    }
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _merge_capabilities(
    run_spec: SandboxRunSpec,
    agent_specs: tuple[AgentSpec, ...],
) -> tuple[str, ...]:
    capabilities = tuple(
        capability for agent in agent_specs for capability in agent.capabilities
    )
    if run_spec.haproxy.default_ports or any(
        agent.haproxy.ports for agent in agent_specs
    ):
        capabilities = (*capabilities, "haproxy")

    return tuple(dict.fromkeys(capabilities))


def _merge_environment_variables(
    agent_specs: tuple[AgentSpec, ...],
) -> tuple[SandboxEnvironmentVariable, ...]:
    values_by_name: dict[str, str] = {}
    for agent in agent_specs:
        for name, value in agent.environment_variables:
            existing_value = values_by_name.get(name)
            if existing_value is not None and existing_value != value:
                raise ValueError(
                    f"Conflicting agent environment variable declarations: {name}"
                )
            values_by_name[name] = value

    return tuple(
        SandboxEnvironmentVariable(name=name, value=value)
        for name, value in values_by_name.items()
    )


def _print_image_result(result: DockerImageResult) -> None:
    if result.status == DockerImageStatus.DOCKER_MISSING:
        print("Docker CLI was not found on PATH.")
        return

    if result.status == DockerImageStatus.DOCKERFILE_MISSING:
        print(f"Dockerfile was not found: {result.dockerfile_path}")
        return

    if result.status == DockerImageStatus.EXISTS:
        print(f"Docker sandbox base image already exists: {result.image_name}")
        return

    if result.status == DockerImageStatus.CREATED:
        print(f"Docker sandbox base image created: {result.image_name}")
        return

    print(f"Docker sandbox base image build failed: {result.image_name}")


def _exit_code_from_image_result(result: DockerImageResult) -> int:
    if result.status in {DockerImageStatus.EXISTS, DockerImageStatus.CREATED}:
        return 0

    return 1


def _exit_code_from_run_result(result: DockerRunResult) -> int:
    return result.exit_code
