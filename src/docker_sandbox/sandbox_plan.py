"""Multi-agent sandbox specification and resolved runtime plan models."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TypeVar, cast

_T = TypeVar("_T")
_DOCKER_EXECUTABLE = "docker"
_SUPPORTED_RUN_SCHEMA_VERSION = 1
_SUPPORTED_AGENT_SCHEMA_VERSION = 1
_SUPPORTED_RUN_KEYS = {
    "schema_version",
    "agents",
    "network",
    "execution",
    "squid_proxy",
    "haproxy",
    "mcp_sidecar",
}
_SUPPORTED_AGENT_KEYS = {
    "schema_version",
    "agent_id",
    "module",
    "container_capabilities",
    "application_capabilities",
    "environment_variables",
    "squid_proxy",
    "haproxy",
    "mcp_sidecar",
}
_AGENT_SQUID_PROXY_KEYS = {
    "allowed_domains",
    "allowed_ip_addresses",
}
_AGENT_HAPROXY_KEYS = {
    "ports",
}
_AGENT_MCP_SIDECAR_KEYS = {
    "tools",
    "resources",
}
_SUPPORTED_CONTAINER_CAPABILITIES = {
    "network",
    "playwright_chromium",
    "shared_volume",
    "shell_access",
}
_SUPPORTED_APPLICATION_CAPABILITIES = {
    "a2a",
    "anthropic_claude",
    "anthropic_python",
    "crewai",
    "google_adk",
    "ibm_beeai",
    "image_artifacts",
    "langchain",
    "langgraph",
    "mcp_client",
    "microsoft_agent",
    "openai",
    "openai_agents",
    "otto_agent",
}
_NETWORK_KEYS = {
    "enabled",
    "internal",
    "subnet",
}
_EXECUTION_KEYS = {
    "entry_agent",
    "mode",
    "order",
}
_SUPPORTED_EXECUTION_MODES = {
    "entry_agent",
    "sequential",
    "parallel",
}
_SQUID_PROXY_KEYS = {
    "default_allowed_domains",
    "default_allowed_ip_addresses",
}
_HAPROXY_KEYS = {
    "backend_host",
    "default_ports",
}
_MCP_SIDECAR_KEYS = {
    "default_tools",
    "default_resources",
    "container_capabilities",
    "application_capabilities",
}
_IMAGE_REPOSITORY = "sandbox-agent"
_AGENT_CONTAINER_NAME_PREFIX = "sandbox-agent"
_NETWORK_NAME_PREFIX = "sandbox-agent-net"
_SQUID_CONTAINER_NAME_PREFIX = "squid-proxy"
_HAPROXY_CONTAINER_NAME_PREFIX = "haproxy-sidecar"
_MCP_SIDECAR_CONTAINER_NAME_PREFIX = "mcp-sidecar"
_SQUID_ALIAS = "egress-gateway"
_SQUID_PORT = 3128
_HAPROXY_ALIAS = "haproxy-sidecar"
_MCP_SIDECAR_ALIAS = "mcp-sidecar"
_MCP_SIDECAR_PORT = 8000
_MCP_SIDECAR_PATH = "/mcp"
_GENERATE_IMAGE_TOOL_NAME = "generate_image"
_PLAN_ARTIFACT_FILE_NAME = "resolved-sandbox-plan.json"
_DEFAULT_SUBNET = "172.28.0.0/24"
_SERVICE_IP_OFFSETS = {
    "squid": 2,
    "mcp": 3,
    "haproxy": 4,
}
_AGENT_IP_START_OFFSET = 11
_HASH_LENGTH = 16
_OPENAI_PROVIDER_DOMAIN = ".openai.com"
_ANTHROPIC_PROVIDER_DOMAIN = ".anthropic.com"
_OPENAI_FAMILY_CAPABILITIES = {
    "crewai",
    "google_adk",
    "ibm_beeai",
    "langchain",
    "langgraph",
    "microsoft_agent",
    "openai",
    "openai_agents",
    "otto_agent",
}
_ANTHROPIC_FAMILY_CAPABILITIES = {
    "anthropic_claude",
    "anthropic_python",
}


@dataclass(frozen=True)
class SquidProxySpec:
    """Run-level default Squid proxy allowlist settings."""

    default_allowed_domains: tuple[str, ...] = ()
    default_allowed_ip_addresses: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentSquidProxySpec:
    """Agent-level Squid proxy allowlist settings."""

    allowed_domains: tuple[str, ...] = ()
    allowed_ip_addresses: tuple[str, ...] = ()


@dataclass(frozen=True)
class HAProxySpec:
    """Run-level default HAProxy forwarding settings."""

    backend_host: str = "host.docker.internal"
    default_ports: tuple[int, ...] = ()


@dataclass(frozen=True)
class AgentHAProxySpec:
    """Agent-level HAProxy forwarding requirements."""

    ports: tuple[int, ...] = ()


@dataclass(frozen=True)
class McpSidecarSpec:
    """Run-level default MCP sidecar exposure settings."""

    default_tools: tuple[str, ...] = ()
    default_resources: tuple[str, ...] = ()
    container_capabilities: tuple[str, ...] = ()
    application_capabilities: tuple[str, ...] = ()

    @property
    def capabilities(self) -> tuple[str, ...]:
        """Return all declared sidecar capabilities in stable declaration order."""
        return _deduplicate(
            (*self.container_capabilities, *self.application_capabilities)
        )


@dataclass(frozen=True)
class AgentMcpSidecarSpec:
    """Agent-level MCP sidecar exposure requirements."""

    tools: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()


@dataclass(frozen=True)
class NetworkSpec:
    """Run-level Docker network settings."""

    enabled: bool = True
    internal: bool = True
    subnet: str | None = None


@dataclass(frozen=True)
class ExecutionSpec:
    """Run-level agent execution settings."""

    mode: str = "sequential"
    order: tuple[str, ...] = ()
    entry_agent: str | None = None


@dataclass(frozen=True)
class AgentSpec:
    """Declared requirements for one sandbox agent."""

    agent_id: str
    module: str
    container_capabilities: tuple[str, ...] = ()
    application_capabilities: tuple[str, ...] = ()
    environment_variables: tuple[tuple[str, str], ...] = ()
    squid_proxy: AgentSquidProxySpec = AgentSquidProxySpec()
    haproxy: AgentHAProxySpec = AgentHAProxySpec()
    mcp_sidecar: AgentMcpSidecarSpec = AgentMcpSidecarSpec()

    @property
    def capabilities(self) -> tuple[str, ...]:
        """Return all declared agent capabilities in stable declaration order."""
        return _deduplicate(
            (*self.container_capabilities, *self.application_capabilities)
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation of the agent specification."""
        return cast(dict[str, object], _json_safe(asdict(self)))


@dataclass(frozen=True)
class SandboxRunSpec:
    """Declared requirements for one multi-agent sandbox run."""

    schema_version: int
    agent_spec_paths: tuple[Path, ...]
    network: NetworkSpec = NetworkSpec()
    execution: ExecutionSpec = ExecutionSpec()
    squid_proxy: SquidProxySpec = SquidProxySpec()
    haproxy: HAProxySpec = HAProxySpec()
    mcp_sidecar: McpSidecarSpec = McpSidecarSpec()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation of the run specification."""
        return cast(dict[str, object], _json_safe(asdict(self)))


@dataclass(frozen=True)
class ResolvedAgentPlan:
    """Resolved runtime plan for one sandbox agent container."""

    agent_id: str
    module: str
    image_name: str
    container_name: str
    ip_address: str | None
    profile_name: str = ""
    command: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    environment_variables: tuple[tuple[str, str], ...] = ()
    mcp_sidecar_url: str | None = None
    http_proxy: str | None = None
    https_proxy: str | None = None
    no_proxy: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = ()
    allowed_ip_addresses: tuple[str, ...] = ()
    haproxy_ports: tuple[int, ...] = ()
    mcp_tools: tuple[str, ...] = ()
    mcp_resources: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedSquidPlan:
    """Resolved Squid proxy ACL plan for all agents in a run."""

    enabled: bool
    container_name: str | None = None
    ip_address: str | None = None
    default_allowed_domains: tuple[str, ...] = ()
    default_allowed_ip_addresses: tuple[str, ...] = ()

    def allowed_domains_for(self, agent: ResolvedAgentPlan) -> tuple[str, ...]:
        """Return default plus agent-specific domain allowlist entries."""
        return _deduplicate((*self.default_allowed_domains, *agent.allowed_domains))

    def allowed_ip_addresses_for(self, agent: ResolvedAgentPlan) -> tuple[str, ...]:
        """Return default plus agent-specific IP allowlist entries."""
        return _deduplicate(
            (*self.default_allowed_ip_addresses, *agent.allowed_ip_addresses)
        )


@dataclass(frozen=True)
class ResolvedHAProxyPlan:
    """Resolved HAProxy source-IP ACL plan for all agents in a run."""

    enabled: bool
    backend_host: str = "host.docker.internal"
    container_name: str | None = None
    ip_address: str | None = None
    default_ports: tuple[int, ...] = ()

    def ports_for(self, agent: ResolvedAgentPlan) -> tuple[int, ...]:
        """Return default plus agent-specific HAProxy ports."""
        return _deduplicate((*self.default_ports, *agent.haproxy_ports))


@dataclass(frozen=True)
class ResolvedMcpSidecarPlan:
    """Resolved shared MCP sidecar exposure plan for all agents in a run."""

    enabled: bool
    container_name: str | None = None
    ip_address: str | None = None
    default_tools: tuple[str, ...] = ()
    default_resources: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    container_capabilities: tuple[str, ...] = ()
    application_capabilities: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = ()
    allowed_ip_addresses: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedSandboxPlan:
    """Resolved runtime plan consumed by Docker orchestration."""

    run_id: str
    network_name: str | None
    subnet: str | None
    agents: tuple[ResolvedAgentPlan, ...]
    squid_proxy: ResolvedSquidPlan
    haproxy: ResolvedHAProxyPlan
    mcp_sidecar: ResolvedMcpSidecarPlan
    execution: ExecutionSpec = ExecutionSpec()
    network_internal: bool = True

    def agent_ids(self) -> tuple[str, ...]:
        """Return all planned agent ids in execution order."""
        return tuple(agent.agent_id for agent in self.agents)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation of the resolved plan."""
        return cast(dict[str, object], _json_safe(asdict(self)))

    def to_json(self) -> str:
        """Return a stable JSON representation of the resolved plan."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def load_sandbox_plan(path: Path, run_id: str) -> ResolvedSandboxPlan:
    """Load run and agent specs and return the resolved sandbox plan."""
    run_spec = load_sandbox_run_spec(path)
    agent_specs = tuple(
        load_agent_spec(agent_spec_path)
        for agent_spec_path in run_spec.agent_spec_paths
    )
    return build_sandbox_plan(run_spec, agent_specs, run_id)


def build_sandbox_plan(
    run_spec: SandboxRunSpec,
    agent_specs: tuple[AgentSpec, ...],
    run_id: str,
) -> ResolvedSandboxPlan:
    """Resolve run and agent declarations into a Docker orchestration plan."""
    if not agent_specs:
        raise ValueError("At least one agent spec is required.")

    _validate_unique_agent_ids(agent_specs)
    execution = _resolve_execution_spec(run_spec.execution, agent_specs)
    ordered_agent_specs = _order_agent_specs(agent_specs, execution.order)
    _validate_run_network_requirements(run_spec, ordered_agent_specs)
    _validate_mcp_sidecar_network_requirement(run_spec, ordered_agent_specs)

    normalized_run_id = _normalize_docker_identifier(run_id)
    network_name = None
    subnet = None
    ip_allocator = None
    if run_spec.network.enabled:
        network_name = f"{_NETWORK_NAME_PREFIX}-{normalized_run_id}"
        subnet = run_spec.network.subnet or _DEFAULT_SUBNET
        ip_allocator = _IpAllocator(subnet)

    squid_ip_address = _allocate_service_ip(ip_allocator, "squid")
    mcp_ip_address = _allocate_service_ip(ip_allocator, "mcp")
    haproxy_ip_address = _allocate_service_ip(ip_allocator, "haproxy")
    mcp_sidecar = build_mcp_sidecar_plan(
        run_spec.mcp_sidecar,
        ordered_agent_specs,
        container_name=_container_name(_MCP_SIDECAR_CONTAINER_NAME_PREFIX, run_id),
        ip_address=mcp_ip_address,
    )
    haproxy = _build_haproxy_plan(
        run_spec,
        ordered_agent_specs,
        run_id,
        haproxy_ip_address,
    )
    squid_proxy = _build_squid_plan(
        run_spec,
        ordered_agent_specs,
        run_id,
        squid_ip_address,
    )
    agents = tuple(
        _build_resolved_agent_plan(
            run_spec,
            agent_spec,
            index,
            run_id,
            ip_allocator,
            mcp_sidecar,
            squid_proxy,
            haproxy,
        )
        for index, agent_spec in enumerate(ordered_agent_specs)
    )

    return ResolvedSandboxPlan(
        run_id=run_id,
        network_name=network_name,
        subnet=subnet,
        agents=agents,
        squid_proxy=squid_proxy,
        haproxy=haproxy,
        mcp_sidecar=mcp_sidecar,
        execution=execution,
        network_internal=run_spec.network.internal,
    )


def save_resolved_sandbox_plan(
    plan: ResolvedSandboxPlan,
    run_directory: Path,
) -> Path:
    """Persist the resolved sandbox plan as a run artifact."""
    run_directory.mkdir(parents=True, exist_ok=True)
    plan_path = run_directory / _PLAN_ARTIFACT_FILE_NAME
    plan_path.write_text(f"{plan.to_json()}\n", encoding="utf-8")
    return plan_path


def build_network_create_command(plan: ResolvedSandboxPlan) -> list[str] | None:
    """Return the Docker command that creates the planned network."""
    if plan.network_name is None:
        return None

    command = [_DOCKER_EXECUTABLE, "network", "create"]
    if plan.network_internal:
        command.append("--internal")
    if plan.subnet is not None:
        command.extend(["--subnet", plan.subnet])

    command.append(plan.network_name)
    return command


def build_container_network_options(
    plan: ResolvedSandboxPlan,
    ip_address: str | None,
    network_alias: str | None = None,
) -> list[str]:
    """Return Docker run network options for a planned container."""
    if plan.network_name is None:
        return []

    options = ["--network", plan.network_name]
    if network_alias is not None:
        options.extend(["--network-alias", network_alias])
    if ip_address is not None:
        options.extend(["--ip", ip_address])

    return options


def build_squid_acl_configuration(plan: ResolvedSandboxPlan) -> str:
    """Build Squid config with default and per-agent source-IP ACLs."""
    if not plan.squid_proxy.enabled:
        return ""

    lines = [
        f"http_port {_SQUID_PORT}",
        "acl SSL_ports port 443",
        "acl Safe_ports port 80",
        "acl Safe_ports port 443",
        "acl CONNECT method CONNECT",
        r"acl ipv4_literal_url url_regex -i "
        r"^[a-z][a-z0-9+.-]*://[0-9]+(\.[0-9]+){3}([:/]|$)",
        r"acl ipv4_literal_connect url_regex -i ^[0-9]+(\.[0-9]+){3}:",
        r"acl ipv6_literal_url url_regex -i "
        r"^[a-z][a-z0-9+.-]*://\[[0-9a-f:.]+\]([:/]|$)",
        r"acl ipv6_literal_connect url_regex -i ^\[[0-9a-f:.]+\]:",
        "http_access deny !Safe_ports",
        "http_access deny CONNECT !SSL_ports",
        "http_access deny ipv4_literal_url",
        "http_access deny ipv4_literal_connect",
        "http_access deny ipv6_literal_url",
        "http_access deny ipv6_literal_connect",
    ]
    agent_source_acl_name = _build_agent_source_acls(lines, plan.agents)
    mcp_sidecar_source_acl_name = _build_mcp_sidecar_source_acl(lines, plan)
    _append_squid_default_acl_rules(lines, plan, agent_source_acl_name)
    _append_squid_mcp_sidecar_acl_rules(lines, plan, mcp_sidecar_source_acl_name)
    _append_squid_agent_acl_rules(lines, plan)
    lines.extend(
        [
            "http_access deny all",
            "access_log none",
            "cache_log /tmp/squid-cache.log",
            "",
        ]
    )
    return "\n".join(lines)


def build_haproxy_acl_configuration(plan: ResolvedSandboxPlan) -> str:
    """Build HAProxy config with default and per-agent source-IP ACLs."""
    if not plan.haproxy.enabled:
        return ""

    lines = [
        "global",
        "    log stdout format raw local0",
        "",
        "defaults",
        "    log global",
        "    mode tcp",
        "    timeout connect 5s",
        "    timeout client 30s",
        "    timeout server 30s",
        "",
    ]
    all_ports = _deduplicate(
        (
            *plan.haproxy.default_ports,
            *(port for agent in plan.agents for port in agent.haproxy_ports),
        )
    )
    for port in all_ports:
        _append_haproxy_port_acl(lines, plan, port)

    return "\n".join(lines)


class _IpAllocator:
    def __init__(self, subnet: str) -> None:
        self._network = ipaddress.ip_network(subnet, strict=False)
        self._addresses = tuple(self._network.hosts())

    def address_at_offset(self, offset: int) -> str:
        if offset < 1 or offset > len(self._addresses):
            raise ValueError(
                f"Subnet {self._network} does not have enough usable IP addresses."
            )

        return str(self._addresses[offset - 1])


def _validate_unique_agent_ids(agent_specs: tuple[AgentSpec, ...]) -> None:
    agent_ids = tuple(agent.agent_id for agent in agent_specs)
    duplicates = _find_duplicates(agent_ids)
    if duplicates:
        names = ", ".join(duplicates)
        raise ValueError(f"Duplicate agent_id: {names}")


def _build_agent_source_acls(
    lines: list[str],
    agents: tuple[ResolvedAgentPlan, ...],
) -> str | None:
    acl_names = []
    source_ips = []
    for agent in agents:
        if agent.ip_address is None:
            continue

        acl_name = _agent_acl_name(agent.agent_id)
        lines.append(f"acl {acl_name} src {agent.ip_address}")
        acl_names.append(acl_name)
        source_ips.append(agent.ip_address)

    if not source_ips:
        return None

    lines.append(f"acl planned_agents src {' '.join(source_ips)}")
    return "planned_agents"


def _build_mcp_sidecar_source_acl(
    lines: list[str],
    plan: ResolvedSandboxPlan,
) -> str | None:
    if not plan.mcp_sidecar.enabled or plan.mcp_sidecar.ip_address is None:
        return None

    lines.append(f"acl mcp_sidecar src {plan.mcp_sidecar.ip_address}")
    return "mcp_sidecar"


def _append_squid_default_acl_rules(
    lines: list[str],
    plan: ResolvedSandboxPlan,
    agent_source_acl_name: str | None,
) -> None:
    if agent_source_acl_name is None:
        return

    if plan.squid_proxy.default_allowed_domains:
        domains = " ".join(plan.squid_proxy.default_allowed_domains)
        lines.append(f"acl default_allowed_sites dstdomain {domains}")
        lines.append(f"http_access allow {agent_source_acl_name} default_allowed_sites")
    if plan.squid_proxy.default_allowed_ip_addresses:
        ip_addresses = " ".join(plan.squid_proxy.default_allowed_ip_addresses)
        lines.append(f"acl default_allowed_ip_addresses dst {ip_addresses}")
        lines.append(
            f"http_access allow {agent_source_acl_name} default_allowed_ip_addresses"
        )


def _append_squid_mcp_sidecar_acl_rules(
    lines: list[str],
    plan: ResolvedSandboxPlan,
    source_acl_name: str | None,
) -> None:
    if source_acl_name is None:
        return

    domains = _deduplicate(
        (*plan.squid_proxy.default_allowed_domains, *plan.mcp_sidecar.allowed_domains)
    )
    if domains:
        acl_name = f"{source_acl_name}_allowed_sites"
        lines.append(f"acl {acl_name} dstdomain {' '.join(domains)}")
        lines.append(f"http_access allow {source_acl_name} {acl_name}")

    ip_addresses = _deduplicate(
        (
            *plan.squid_proxy.default_allowed_ip_addresses,
            *plan.mcp_sidecar.allowed_ip_addresses,
        )
    )
    if ip_addresses:
        acl_name = f"{source_acl_name}_allowed_ip_addresses"
        lines.append(f"acl {acl_name} dst {' '.join(ip_addresses)}")
        lines.append(f"http_access allow {source_acl_name} {acl_name}")


def _append_squid_agent_acl_rules(
    lines: list[str],
    plan: ResolvedSandboxPlan,
) -> None:
    for agent in plan.agents:
        if agent.ip_address is None:
            continue

        source_acl = _agent_acl_name(agent.agent_id)
        if agent.allowed_domains:
            acl_name = f"{source_acl}_allowed_sites"
            domains = " ".join(agent.allowed_domains)
            lines.append(f"acl {acl_name} dstdomain {domains}")
            lines.append(f"http_access allow {source_acl} {acl_name}")
        if agent.allowed_ip_addresses:
            acl_name = f"{source_acl}_allowed_ip_addresses"
            ip_addresses = " ".join(agent.allowed_ip_addresses)
            lines.append(f"acl {acl_name} dst {ip_addresses}")
            lines.append(f"http_access allow {source_acl} {acl_name}")


def _append_haproxy_port_acl(
    lines: list[str],
    plan: ResolvedSandboxPlan,
    port: int,
) -> None:
    default_agents = tuple(
        agent for agent in plan.agents if agent.ip_address is not None
    )
    specific_agents = tuple(
        agent
        for agent in plan.agents
        if agent.ip_address is not None and port in agent.haproxy_ports
    )
    allowed_agents = specific_agents
    if port in plan.haproxy.default_ports:
        allowed_agents = default_agents
    allow_mcp_sidecar = (
        plan.mcp_sidecar.enabled and plan.mcp_sidecar.ip_address is not None
    )

    lines.extend(
        [
            f"frontend tcp_{port}",
            f"    bind *:{port}",
            "    mode tcp",
        ]
    )
    for agent in allowed_agents:
        lines.append(
            f"    acl {_agent_acl_name(agent.agent_id)} src {agent.ip_address}"
        )
    if allow_mcp_sidecar:
        lines.append(f"    acl mcp_sidecar src {plan.mcp_sidecar.ip_address}")

    for agent in allowed_agents:
        lines.append(
            f"    tcp-request connection accept if {_agent_acl_name(agent.agent_id)}"
        )
    if allow_mcp_sidecar:
        lines.append("    tcp-request connection accept if mcp_sidecar")
    lines.extend(
        [
            "    tcp-request connection reject",
            f"    default_backend tcp_{port}_backend",
            "",
            f"backend tcp_{port}_backend",
            "    mode tcp",
            f"    server host_service {plan.haproxy.backend_host}:{port}",
            "",
        ]
    )


def _agent_acl_name(agent_id: str) -> str:
    return f"agent_{_normalize_acl_identifier(agent_id)}"


def _normalize_acl_identifier(value: str) -> str:
    normalized = []
    for character in value.strip().lower():
        if character.isalnum():
            normalized.append(character)
            continue

        normalized.append("_")

    result = "_".join(part for part in "".join(normalized).split("_") if part)
    if not result:
        raise ValueError("ACL identifiers must contain letters or numbers.")

    return result


def _join_acl_names(acl_names: tuple[str, ...]) -> str:
    return " ".join(_deduplicate(acl_names))


def _resolve_execution_spec(
    execution: ExecutionSpec,
    agent_specs: tuple[AgentSpec, ...],
) -> ExecutionSpec:
    order = execution.order
    if execution.order:
        _validate_execution_order(execution.order, agent_specs)
    else:
        order = tuple(agent.agent_id for agent in agent_specs)

    entry_agent = _resolve_entry_agent(execution, order)

    return ExecutionSpec(
        mode=execution.mode,
        order=order,
        entry_agent=entry_agent,
    )


def _resolve_entry_agent(
    execution: ExecutionSpec,
    order: tuple[str, ...],
) -> str | None:
    if execution.mode != "entry_agent":
        if execution.entry_agent is not None:
            raise ValueError("entry_agent requires execution mode 'entry_agent'.")
        return None

    entry_agent = execution.entry_agent or (order[0] if order else None)
    if entry_agent not in order:
        raise ValueError(f"Unknown entry agent_id: {entry_agent}")

    return entry_agent


def _validate_execution_order(
    order: tuple[str, ...],
    agent_specs: tuple[AgentSpec, ...],
) -> None:
    agent_ids = tuple(agent.agent_id for agent in agent_specs)
    duplicates = _find_duplicates(order)
    if duplicates:
        names = ", ".join(duplicates)
        raise ValueError(f"Duplicate execution order agent_id: {names}")

    missing_ids = set(agent_ids) - set(order)
    unknown_ids = set(order) - set(agent_ids)
    if missing_ids:
        names = ", ".join(sorted(missing_ids))
        raise ValueError(f"Execution order is missing agent_id: {names}")
    if unknown_ids:
        names = ", ".join(sorted(unknown_ids))
        raise ValueError(f"Execution order includes unknown agent_id: {names}")


def _order_agent_specs(
    agent_specs: tuple[AgentSpec, ...],
    order: tuple[str, ...],
) -> tuple[AgentSpec, ...]:
    by_agent_id = {agent.agent_id: agent for agent in agent_specs}
    return tuple(by_agent_id[agent_id] for agent_id in order)


def _validate_run_network_requirements(
    run_spec: SandboxRunSpec,
    agent_specs: tuple[AgentSpec, ...],
) -> None:
    if run_spec.network.enabled:
        return

    network_agent_ids = [
        agent.agent_id
        for agent in agent_specs
        if "network" in agent.container_capabilities
    ]
    if network_agent_ids:
        names = ", ".join(network_agent_ids)
        raise ValueError(f"Network is disabled but required by agent: {names}")
    if "network" in run_spec.mcp_sidecar.container_capabilities:
        raise ValueError("Network is disabled but required by MCP sidecar.")

    if run_spec.squid_proxy.default_allowed_domains:
        raise ValueError("Squid proxy defaults require the network to be enabled.")
    if run_spec.squid_proxy.default_allowed_ip_addresses:
        raise ValueError("Squid proxy defaults require the network to be enabled.")
    if run_spec.haproxy.default_ports:
        raise ValueError("HAProxy default ports require the network to be enabled.")


def _allocate_service_ip(allocator: _IpAllocator | None, service: str) -> str | None:
    if allocator is None:
        return None

    return allocator.address_at_offset(_SERVICE_IP_OFFSETS[service])


def _build_squid_plan(
    run_spec: SandboxRunSpec,
    agent_specs: tuple[AgentSpec, ...],
    run_id: str,
    ip_address: str | None,
) -> ResolvedSquidPlan:
    needs_network = (
        any("network" in agent.container_capabilities for agent in agent_specs)
        or "network" in run_spec.mcp_sidecar.container_capabilities
    )
    enabled = run_spec.network.enabled and needs_network
    return ResolvedSquidPlan(
        enabled=enabled,
        container_name=_container_name(_SQUID_CONTAINER_NAME_PREFIX, run_id)
        if enabled
        else None,
        ip_address=ip_address if enabled else None,
        default_allowed_domains=run_spec.squid_proxy.default_allowed_domains,
        default_allowed_ip_addresses=run_spec.squid_proxy.default_allowed_ip_addresses,
    )


def _build_haproxy_plan(
    run_spec: SandboxRunSpec,
    agent_specs: tuple[AgentSpec, ...],
    run_id: str,
    ip_address: str | None,
) -> ResolvedHAProxyPlan:
    all_agent_ports = tuple(
        port for agent in agent_specs for port in agent.haproxy.ports
    )
    enabled = run_spec.network.enabled and bool(
        run_spec.haproxy.default_ports or all_agent_ports
    )
    return ResolvedHAProxyPlan(
        enabled=enabled,
        backend_host=run_spec.haproxy.backend_host,
        container_name=_container_name(_HAPROXY_CONTAINER_NAME_PREFIX, run_id)
        if enabled
        else None,
        ip_address=ip_address if enabled else None,
        default_ports=run_spec.haproxy.default_ports,
    )


def _build_resolved_agent_plan(
    run_spec: SandboxRunSpec,
    spec: AgentSpec,
    index: int,
    run_id: str,
    ip_allocator: _IpAllocator | None,
    mcp_sidecar: ResolvedMcpSidecarPlan,
    squid_proxy: ResolvedSquidPlan,
    haproxy: ResolvedHAProxyPlan,
) -> ResolvedAgentPlan:
    agent_index = _AGENT_IP_START_OFFSET + index
    ip_address = (
        ip_allocator.address_at_offset(agent_index)
        if ip_allocator is not None
        else None
    )
    proxy_url = None
    if squid_proxy.enabled and "network" in spec.container_capabilities:
        proxy_url = f"http://{_SQUID_ALIAS}:{_SQUID_PORT}"

    return ResolvedAgentPlan(
        agent_id=spec.agent_id,
        module=spec.module,
        image_name=_build_agent_image_name(run_spec, spec),
        container_name=_container_name(
            _AGENT_CONTAINER_NAME_PREFIX,
            run_id,
            spec.agent_id,
        ),
        ip_address=ip_address,
        profile_name=_build_agent_profile_name(run_spec, spec),
        command=("python", "-m", spec.module),
        capabilities=spec.capabilities,
        environment_variables=spec.environment_variables,
        mcp_sidecar_url=_build_mcp_sidecar_url(mcp_sidecar, spec),
        http_proxy=proxy_url,
        https_proxy=proxy_url,
        no_proxy=_build_agent_no_proxy(mcp_sidecar, haproxy),
        allowed_domains=_build_agent_allowed_domains(spec),
        allowed_ip_addresses=spec.squid_proxy.allowed_ip_addresses,
        haproxy_ports=spec.haproxy.ports,
        mcp_tools=spec.mcp_sidecar.tools,
        mcp_resources=spec.mcp_sidecar.resources,
    )


def _build_mcp_sidecar_url(
    mcp_sidecar: ResolvedMcpSidecarPlan,
    agent: AgentSpec,
) -> str | None:
    if not mcp_sidecar.enabled:
        return None
    if "mcp_client" not in agent.application_capabilities:
        return None

    return f"http://{_MCP_SIDECAR_ALIAS}:{_MCP_SIDECAR_PORT}{_MCP_SIDECAR_PATH}"


def _build_agent_no_proxy(
    mcp_sidecar: ResolvedMcpSidecarPlan,
    haproxy: ResolvedHAProxyPlan,
) -> tuple[str, ...]:
    hosts = ["localhost", "127.0.0.1"]
    if mcp_sidecar.enabled:
        hosts.append(_MCP_SIDECAR_ALIAS)
    if haproxy.enabled:
        hosts.append(_HAPROXY_ALIAS)

    return tuple(hosts)


def _build_agent_allowed_domains(spec: AgentSpec) -> tuple[str, ...]:
    domains = list(spec.squid_proxy.allowed_domains)
    if _OPENAI_FAMILY_CAPABILITIES.intersection(spec.application_capabilities):
        domains.append(_OPENAI_PROVIDER_DOMAIN)
    if _ANTHROPIC_FAMILY_CAPABILITIES.intersection(spec.application_capabilities):
        domains.append(_ANTHROPIC_PROVIDER_DOMAIN)

    return tuple(dict.fromkeys(domains))


def _build_mcp_sidecar_allowed_domains(spec: McpSidecarSpec) -> tuple[str, ...]:
    domains = []
    if _OPENAI_FAMILY_CAPABILITIES.intersection(spec.application_capabilities):
        domains.append(_OPENAI_PROVIDER_DOMAIN)
    if _ANTHROPIC_FAMILY_CAPABILITIES.intersection(spec.application_capabilities):
        domains.append(_ANTHROPIC_PROVIDER_DOMAIN)

    return tuple(dict.fromkeys(domains))


def _build_agent_image_name(run_spec: SandboxRunSpec, spec: AgentSpec) -> str:
    return f"sandbox-agent/sandbox-agent:{_agent_image_tag(run_spec, spec)}"


def _build_agent_profile_name(run_spec: SandboxRunSpec, spec: AgentSpec) -> str:
    return f"sandbox-spec-{_agent_image_tag(run_spec, spec)}"


def _agent_image_tag(run_spec: SandboxRunSpec, spec: AgentSpec) -> str:
    return f"{run_spec.schema_version}-{_agent_image_hash(run_spec, spec)}"


def _agent_image_hash(run_spec: SandboxRunSpec, spec: AgentSpec) -> str:
    normalized_json = json.dumps(
        _agent_image_hash_data(run_spec, spec),
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(normalized_json.encode("utf-8")).hexdigest()
    return digest[:_HASH_LENGTH]


def _agent_image_hash_data(
    run_spec: SandboxRunSpec,
    spec: AgentSpec,
) -> dict[str, object]:
    return {
        "agent": {
            "application_capabilities": list(spec.application_capabilities),
            "container_capabilities": list(spec.container_capabilities),
            "environment_variables": [
                {"name": name, "value": value}
                for name, value in spec.environment_variables
            ],
            "haproxy": {
                "ports": list(spec.haproxy.ports),
            },
            "mcp_sidecar": {
                "resources": list(spec.mcp_sidecar.resources),
                "tools": list(spec.mcp_sidecar.tools),
            },
            "squid_proxy": {
                "allowed_domains": list(spec.squid_proxy.allowed_domains),
                "allowed_ip_addresses": list(spec.squid_proxy.allowed_ip_addresses),
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


def _container_name(prefix: str, run_id: str, agent_id: str | None = None) -> str:
    parts = [prefix, _normalize_docker_identifier(run_id)]
    if agent_id is not None:
        parts.append(_normalize_docker_identifier(agent_id))

    return "-".join(parts)


def _normalize_docker_identifier(value: str) -> str:
    normalized = []
    for character in value.strip().lower():
        if character.isalnum() or character in {"_", "."}:
            normalized.append(character)
            continue

        normalized.append("-")

    result = "".join(normalized).strip("-._")
    if not result:
        raise ValueError("Docker identifier values must contain letters or numbers.")

    return result


def build_mcp_sidecar_plan(
    spec: McpSidecarSpec,
    agents: tuple[AgentSpec, ...],
    container_name: str | None = None,
    ip_address: str | None = None,
) -> ResolvedMcpSidecarPlan:
    """Build the shared MCP exposure plan from defaults and agent requirements."""
    tools = _deduplicate(
        (
            *spec.default_tools,
            *(tool for agent in agents for tool in agent.mcp_sidecar.tools),
        )
    )
    resources = _deduplicate(
        (
            *spec.default_resources,
            *(resource for agent in agents for resource in agent.mcp_sidecar.resources),
        )
    )
    enabled = bool(tools or resources)
    return ResolvedMcpSidecarPlan(
        enabled=enabled,
        container_name=container_name if enabled else None,
        ip_address=ip_address if enabled else None,
        default_tools=spec.default_tools,
        default_resources=spec.default_resources,
        tools=tools,
        resources=resources,
        container_capabilities=spec.container_capabilities,
        application_capabilities=spec.application_capabilities,
        capabilities=spec.capabilities,
        allowed_domains=_build_mcp_sidecar_allowed_domains(spec),
        allowed_ip_addresses=(),
    )


def load_sandbox_run_spec(path: Path) -> SandboxRunSpec:
    """Load and validate a multi-agent sandbox run spec TOML file."""
    if not path.exists():
        raise ValueError(f"Sandbox run spec was not found: {path}")

    with path.open("rb") as file:
        data = tomllib.load(file)

    unknown_keys = set(data) - _SUPPORTED_RUN_KEYS
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unsupported sandbox run spec key: {names}")

    schema_version = data.get("schema_version", _SUPPORTED_RUN_SCHEMA_VERSION)
    if schema_version != _SUPPORTED_RUN_SCHEMA_VERSION:
        raise ValueError(f"Unsupported sandbox run schema_version: {schema_version}")

    agents = _read_agent_spec_paths(data, path.parent)
    return SandboxRunSpec(
        schema_version=schema_version,
        agent_spec_paths=agents,
        network=_read_network_spec(data),
        execution=_read_execution_spec(data),
        squid_proxy=_read_squid_proxy_spec(data),
        haproxy=_read_haproxy_spec(data),
        mcp_sidecar=_read_mcp_sidecar_spec(data),
    )


def load_agent_spec(path: Path) -> AgentSpec:
    """Load and validate one agent spec TOML file."""
    if not path.exists():
        raise ValueError(f"Agent spec was not found: {path}")

    with path.open("rb") as file:
        data = tomllib.load(file)

    unknown_keys = set(data) - _SUPPORTED_AGENT_KEYS
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unsupported agent spec key: {names}")

    schema_version = data.get("schema_version", _SUPPORTED_AGENT_SCHEMA_VERSION)
    if schema_version != _SUPPORTED_AGENT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported agent schema_version: {schema_version}")

    agent_id = _read_required_string(data, "agent_id")
    module = _read_required_string(data, "module")
    container_capabilities = _read_string_tuple(data, "container_capabilities")
    application_capabilities = _read_string_tuple(data, "application_capabilities")
    environment_variables = _read_environment_variables(data)
    squid_proxy = _read_agent_squid_proxy_spec(data)
    haproxy = _read_agent_haproxy_spec(data)
    mcp_sidecar = _read_agent_mcp_sidecar_spec(data)
    _validate_capabilities(
        container_capabilities,
        _SUPPORTED_CONTAINER_CAPABILITIES,
        "container",
    )
    _validate_capabilities(
        application_capabilities,
        _SUPPORTED_APPLICATION_CAPABILITIES,
        "application",
    )
    _validate_agent_network_requirements(
        container_capabilities,
        application_capabilities,
    )
    _validate_agent_appliance_requirements(
        container_capabilities,
        application_capabilities,
        squid_proxy,
        haproxy,
        mcp_sidecar,
    )

    return AgentSpec(
        agent_id=agent_id,
        module=module,
        container_capabilities=container_capabilities,
        application_capabilities=application_capabilities,
        environment_variables=environment_variables,
        squid_proxy=squid_proxy,
        haproxy=haproxy,
        mcp_sidecar=mcp_sidecar,
    )


def _read_agent_spec_paths(
    data: dict[str, object],
    base_directory: Path,
) -> tuple[Path, ...]:
    value = data.get("agents")
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("agents must be a non-empty list of strings.")

    if not value:
        raise ValueError("agents must be a non-empty list of strings.")

    paths = []
    seen_paths = set()
    for item in value:
        if not item.strip():
            raise ValueError("agents entries must not be empty.")

        path = Path(item).expanduser()
        if not path.is_absolute():
            path = base_directory / path

        resolved_path = path.resolve(strict=False)
        if resolved_path in seen_paths:
            raise ValueError(f"Duplicate agent spec path: {item}")

        seen_paths.add(resolved_path)
        paths.append(resolved_path)

    return tuple(paths)


def _read_environment_variables(
    data: dict[str, object],
) -> tuple[tuple[str, str], ...]:
    entries = data.get("environment_variables", [])
    if not isinstance(entries, list):
        raise ValueError("environment_variables must be an array of tables.")

    variables = []
    names = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("environment_variables entries must be tables.")

        name = _read_required_string(entry, "name")
        value = _read_required_string(entry, "value")
        if name in names:
            raise ValueError(f"Duplicate environment variable: {name}")

        unknown_keys = set(entry) - {"name", "value"}
        if unknown_keys:
            names_text = ", ".join(sorted(unknown_keys))
            raise ValueError(f"Unsupported environment variable key: {names_text}")

        names.add(name)
        variables.append((name, value))

    return tuple(variables)


def _read_agent_squid_proxy_spec(data: dict[str, object]) -> AgentSquidProxySpec:
    value = _read_table(data, "squid_proxy", _AGENT_SQUID_PROXY_KEYS)
    allowed_domains = _read_string_tuple(value, "allowed_domains")
    allowed_ip_addresses = _read_string_tuple(value, "allowed_ip_addresses")
    for domain in allowed_domains:
        _validate_domain_allowlist_entry(domain, "allowed_domains")
    for ip_address in allowed_ip_addresses:
        ipaddress.ip_network(ip_address.strip().strip("[]"), strict=False)

    return AgentSquidProxySpec(
        allowed_domains=allowed_domains,
        allowed_ip_addresses=allowed_ip_addresses,
    )


def _read_agent_haproxy_spec(data: dict[str, object]) -> AgentHAProxySpec:
    value = _read_table(data, "haproxy", _AGENT_HAPROXY_KEYS)
    return AgentHAProxySpec(ports=_read_tcp_ports(value, "ports"))


def _read_agent_mcp_sidecar_spec(data: dict[str, object]) -> AgentMcpSidecarSpec:
    value = _read_table(data, "mcp_sidecar", _AGENT_MCP_SIDECAR_KEYS)
    return AgentMcpSidecarSpec(
        tools=_read_string_tuple(value, "tools"),
        resources=_read_string_tuple(value, "resources"),
    )


def _read_network_spec(data: dict[str, object]) -> NetworkSpec:
    value = _read_table(data, "network", _NETWORK_KEYS)
    enabled = _read_bool(value, "enabled", default=True)
    internal = _read_bool(value, "internal", default=True)
    subnet = _read_optional_string(value, "subnet")
    if subnet is not None:
        ipaddress.ip_network(subnet, strict=False)

    return NetworkSpec(enabled=enabled, internal=internal, subnet=subnet)


def _read_execution_spec(data: dict[str, object]) -> ExecutionSpec:
    value = _read_table(data, "execution", _EXECUTION_KEYS)
    mode = _read_string(value, "mode", default="sequential")
    if mode not in _SUPPORTED_EXECUTION_MODES:
        names = ", ".join(sorted(_SUPPORTED_EXECUTION_MODES))
        raise ValueError(f"Unsupported execution mode: {mode}. Supported: {names}")

    return ExecutionSpec(
        mode=mode,
        order=_read_string_tuple(value, "order"),
        entry_agent=_read_optional_string(value, "entry_agent"),
    )


def _read_squid_proxy_spec(data: dict[str, object]) -> SquidProxySpec:
    value = _read_table(data, "squid_proxy", _SQUID_PROXY_KEYS)
    allowed_domains = _read_string_tuple(value, "default_allowed_domains")
    allowed_ip_addresses = _read_string_tuple(value, "default_allowed_ip_addresses")
    for domain in allowed_domains:
        _validate_domain_allowlist_entry(domain, "default_allowed_domains")
    for ip_address in allowed_ip_addresses:
        ipaddress.ip_network(ip_address.strip().strip("[]"), strict=False)

    return SquidProxySpec(
        default_allowed_domains=allowed_domains,
        default_allowed_ip_addresses=allowed_ip_addresses,
    )


def _read_haproxy_spec(data: dict[str, object]) -> HAProxySpec:
    value = _read_table(data, "haproxy", _HAPROXY_KEYS)
    backend_host = _read_string(
        value,
        "backend_host",
        default=HAProxySpec().backend_host,
    )
    return HAProxySpec(
        backend_host=backend_host,
        default_ports=_read_tcp_ports(value, "default_ports"),
    )


def _read_mcp_sidecar_spec(data: dict[str, object]) -> McpSidecarSpec:
    value = _read_table(data, "mcp_sidecar", _MCP_SIDECAR_KEYS)
    default_tools = _read_string_tuple(value, "default_tools")
    default_resources = _read_string_tuple(value, "default_resources")
    container_capabilities = _read_string_tuple(value, "container_capabilities")
    application_capabilities = _read_string_tuple(value, "application_capabilities")
    _validate_capabilities(
        container_capabilities,
        _SUPPORTED_CONTAINER_CAPABILITIES,
        "MCP sidecar container",
    )
    _validate_capabilities(
        application_capabilities,
        _SUPPORTED_APPLICATION_CAPABILITIES,
        "MCP sidecar application",
    )
    _validate_mcp_sidecar_capabilities(
        container_capabilities,
        application_capabilities,
        default_tools,
        default_resources,
    )
    return McpSidecarSpec(
        default_tools=default_tools,
        default_resources=default_resources,
        container_capabilities=container_capabilities,
        application_capabilities=application_capabilities,
    )


def _read_table(
    data: dict[str, object],
    key: str,
    supported_keys: set[str],
) -> dict[str, object]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a table.")

    unknown_keys = set(value) - supported_keys
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ValueError(f"Unsupported {key} key: {names}")

    return value


def _read_bool(data: dict[str, object], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean.")

    return value


def _read_string(
    data: dict[str, object],
    key: str,
    default: str,
) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string.")

    return value.strip()


def _read_required_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string.")

    return value.strip()


def _read_optional_string(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string.")

    return value.strip()


def _read_string_tuple(data: dict[str, object], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings.")

    if any(not item.strip() for item in value):
        raise ValueError(f"{key} entries must not be empty.")

    return tuple(item.strip() for item in value)


def _read_tcp_ports(data: dict[str, object], key: str) -> tuple[int, ...]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list of TCP ports.")

    ports = []
    for port in value:
        if not isinstance(port, int) or isinstance(port, bool):
            raise ValueError(f"{key} must contain only integer TCP ports.")
        if port < 1 or port > 65535:
            raise ValueError(f"{key} entries must be between 1 and 65535.")
        ports.append(port)

    duplicates = _find_duplicates(tuple(ports))
    if duplicates:
        names = ", ".join(str(port) for port in duplicates)
        raise ValueError(f"Duplicate {key} entry: {names}")

    return tuple(ports)


def _validate_domain_allowlist_entry(domain: str, key: str) -> None:
    normalized_domain = domain.strip().lower()
    if "://" in normalized_domain or "/" in normalized_domain:
        raise ValueError(f"{key} entries must be host names, not URLs or paths.")


def _validate_capabilities(
    capabilities: tuple[str, ...],
    supported_capabilities: set[str],
    capability_type: str,
) -> None:
    unsupported_capabilities = set(capabilities) - supported_capabilities
    if unsupported_capabilities:
        names = ", ".join(sorted(unsupported_capabilities))
        raise ValueError(f"Unsupported {capability_type} capability: {names}")


def _validate_agent_network_requirements(
    container_capabilities: tuple[str, ...],
    application_capabilities: tuple[str, ...],
) -> None:
    if "network" in container_capabilities:
        return

    networked_application_capabilities = {
        "a2a",
        "anthropic_claude",
        "anthropic_python",
        "crewai",
        "google_adk",
        "ibm_beeai",
        "langchain",
        "langgraph",
        "mcp_client",
        "microsoft_agent",
        "openai",
        "openai_agents",
        "otto_agent",
    }.intersection(application_capabilities)
    if networked_application_capabilities:
        names = ", ".join(sorted(networked_application_capabilities))
        raise ValueError(f"The {names} capability requires the network capability.")


def _validate_agent_appliance_requirements(
    container_capabilities: tuple[str, ...],
    application_capabilities: tuple[str, ...],
    squid_proxy: AgentSquidProxySpec,
    haproxy: AgentHAProxySpec,
    mcp_sidecar: AgentMcpSidecarSpec,
) -> None:
    has_network = "network" in container_capabilities
    if (
        squid_proxy.allowed_domains or squid_proxy.allowed_ip_addresses
    ) and not has_network:
        raise ValueError("Agent Squid proxy allowlists require the network capability.")
    if haproxy.ports and not has_network:
        raise ValueError("Agent HAProxy ports require the network capability.")
    if (mcp_sidecar.tools or mcp_sidecar.resources) and "mcp_client" not in (
        application_capabilities
    ):
        raise ValueError("Agent MCP exposure requires the mcp_client capability.")


def _validate_mcp_sidecar_capabilities(
    container_capabilities: tuple[str, ...],
    application_capabilities: tuple[str, ...],
    default_tools: tuple[str, ...],
    default_resources: tuple[str, ...],
) -> None:
    _validate_agent_network_requirements(
        container_capabilities,
        application_capabilities,
    )
    if (default_tools or default_resources) and "network" not in (
        container_capabilities
    ):
        raise ValueError("MCP sidecar exposure requires the network capability.")


def _validate_mcp_sidecar_network_requirement(
    run_spec: SandboxRunSpec,
    agent_specs: tuple[AgentSpec, ...],
) -> None:
    _validate_mcp_sidecar_tool_requirements(run_spec, agent_specs)
    has_exposure = bool(
        run_spec.mcp_sidecar.default_tools
        or run_spec.mcp_sidecar.default_resources
        or any(
            agent.mcp_sidecar.tools or agent.mcp_sidecar.resources
            for agent in agent_specs
        )
    )
    if not has_exposure:
        return
    if "network" in run_spec.mcp_sidecar.container_capabilities:
        return

    raise ValueError("MCP sidecar exposure requires the network capability.")


def _validate_mcp_sidecar_tool_requirements(
    run_spec: SandboxRunSpec,
    agent_specs: tuple[AgentSpec, ...],
) -> None:
    exposed_tools = (
        *run_spec.mcp_sidecar.default_tools,
        *(tool for agent in agent_specs for tool in agent.mcp_sidecar.tools),
    )
    if _GENERATE_IMAGE_TOOL_NAME not in exposed_tools:
        return
    if "openai" in run_spec.mcp_sidecar.application_capabilities:
        return

    raise ValueError("The generate_image MCP tool requires the openai capability.")


def _find_duplicates(items: tuple[_T, ...]) -> tuple[_T, ...]:
    seen = set()
    duplicates = []
    for item in items:
        if item in seen and item not in duplicates:
            duplicates.append(item)
            continue

        seen.add(item)

    return tuple(duplicates)


def _deduplicate(items: tuple[_T, ...]) -> tuple[_T, ...]:
    unique_items = []
    for item in items:
        if item in unique_items:
            continue

        unique_items.append(item)

    return tuple(unique_items)


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
