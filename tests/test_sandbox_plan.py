"""Tests for multi-agent sandbox plan models."""

from __future__ import annotations

from pathlib import Path

import pytest

from docker_sandbox.sandbox_plan import (
    AgentHAProxySpec,
    AgentMcpSidecarSpec,
    AgentSpec,
    AgentSquidProxySpec,
    ExecutionSpec,
    HAProxySpec,
    McpSidecarSpec,
    NetworkSpec,
    ResolvedAgentPlan,
    ResolvedHAProxyPlan,
    ResolvedMcpSidecarPlan,
    ResolvedSandboxPlan,
    ResolvedSquidPlan,
    SandboxRunSpec,
    SquidProxySpec,
    build_container_network_options,
    build_haproxy_acl_configuration,
    build_mcp_sidecar_plan,
    build_network_create_command,
    build_sandbox_plan,
    build_squid_acl_configuration,
    load_agent_spec,
    load_sandbox_plan,
    load_sandbox_run_spec,
    save_resolved_sandbox_plan,
)


def test_agent_spec_combines_capabilities_without_duplicates() -> None:
    """Verify agent capabilities preserve declaration order while deduplicating."""
    spec = AgentSpec(
        agent_id="agent_1",
        module="sandbox_agent",
        container_capabilities=("network", "mcp_client"),
        application_capabilities=("image_artifacts", "mcp_client", "openai_agents"),
    )

    assert spec.capabilities == (
        "network",
        "mcp_client",
        "image_artifacts",
        "openai_agents",
    )


def test_shared_mcp_plan_unions_default_and_agent_exposure() -> None:
    """Verify one shared MCP sidecar exposes all declared tools and resources."""
    spec = McpSidecarSpec(
        default_tools=("get_active_items",),
        default_resources=("answer_format",),
    )
    agents = (
        AgentSpec(
            agent_id="agent_1",
            module="sandbox_agent",
            mcp_sidecar=AgentMcpSidecarSpec(
                tools=("get_active_items", "jina_read_url"),
                resources=(),
            ),
        ),
        AgentSpec(
            agent_id="agent_2",
            module="review_agent",
            mcp_sidecar=AgentMcpSidecarSpec(
                tools=("microsoft_docs_search",),
                resources=("answer_format",),
            ),
        ),
    )

    plan = build_mcp_sidecar_plan(spec, agents)

    assert plan.enabled
    assert plan.tools == (
        "get_active_items",
        "jina_read_url",
        "microsoft_docs_search",
    )
    assert plan.resources == ("answer_format",)


def test_shared_mcp_plan_is_disabled_without_exposure() -> None:
    """Verify the shared MCP sidecar can be omitted when no exposure is declared."""
    plan = build_mcp_sidecar_plan(McpSidecarSpec(), ())

    assert not plan.enabled
    assert plan.tools == ()
    assert plan.resources == ()


def test_shared_mcp_plan_carries_sidecar_capabilities() -> None:
    """Verify MCP sidecar capabilities are carried into the resolved plan."""
    spec = McpSidecarSpec(
        default_tools=("get_active_items",),
        container_capabilities=("network",),
        application_capabilities=("openai",),
    )

    plan = build_mcp_sidecar_plan(spec, ())

    assert plan.enabled
    assert plan.container_capabilities == ("network",)
    assert plan.application_capabilities == ("openai",)
    assert plan.capabilities == ("network", "openai")
    assert plan.allowed_domains == (".openai.com",)


def test_squid_plan_combines_default_and_agent_allowlists() -> None:
    """Verify Squid can model default and agent-specific source-IP ACL inputs."""
    squid = ResolvedSquidPlan(
        enabled=True,
        default_allowed_domains=(".openai.com",),
        default_allowed_ip_addresses=("203.0.113.10",),
    )
    agent = ResolvedAgentPlan(
        agent_id="agent_1",
        module="sandbox_agent",
        image_name="sandbox-agent/agent-1:test",
        container_name="agent-1",
        ip_address="172.28.0.11",
        allowed_domains=(".example.com", ".openai.com"),
        allowed_ip_addresses=("198.51.100.7",),
    )

    assert squid.allowed_domains_for(agent) == (".openai.com", ".example.com")
    assert squid.allowed_ip_addresses_for(agent) == (
        "203.0.113.10",
        "198.51.100.7",
    )


def test_haproxy_plan_combines_default_and_agent_ports() -> None:
    """Verify HAProxy can model default and agent-specific source-IP ACL inputs."""
    haproxy = ResolvedHAProxyPlan(
        enabled=True,
        backend_host=HAProxySpec().backend_host,
        default_ports=(3306,),
    )
    agent = ResolvedAgentPlan(
        agent_id="agent_1",
        module="sandbox_agent",
        image_name="sandbox-agent/agent-1:test",
        container_name="agent-1",
        ip_address="172.28.0.11",
        haproxy_ports=(3307, 3306),
    )

    assert haproxy.ports_for(agent) == (3306, 3307)


def test_resolved_sandbox_plan_serializes_to_json_safe_data() -> None:
    """Verify resolved plans can be persisted as run artifacts."""
    agent = ResolvedAgentPlan(
        agent_id="agent_1",
        module="sandbox_agent",
        image_name="sandbox-agent/agent-1:test",
        container_name="agent-1",
        ip_address="172.28.0.11",
    )
    plan = ResolvedSandboxPlan(
        run_id="run-test",
        network_name="sandbox-agent-net-test",
        subnet="172.28.0.0/24",
        agents=(agent,),
        squid_proxy=ResolvedSquidPlan(enabled=True),
        haproxy=ResolvedHAProxyPlan(enabled=True),
        mcp_sidecar=ResolvedMcpSidecarPlan(enabled=True),
        execution=ExecutionSpec(mode="sequential", order=("agent_1",)),
    )

    data = plan.to_dict()
    agents_data = data["agents"]

    assert plan.agent_ids() == ("agent_1",)
    assert isinstance(agents_data, list)
    assert agents_data[0]["agent_id"] == "agent_1"
    assert agents_data[0]["ip_address"] == "172.28.0.11"
    assert '"agent_1"' in plan.to_json()


def test_load_sandbox_run_spec_reads_run_level_defaults(tmp_path: Path) -> None:
    """Verify run-level TOML defaults are parsed into the new run spec model."""
    spec_path = tmp_path / "sandbox_run.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agents = ["agent_1.toml"]',
                "",
                "[network]",
                "enabled = true",
                "internal = true",
                'subnet = "172.28.0.0/24"',
                "",
                "[execution]",
                'mode = "sequential"',
                'order = ["agent_1"]',
                "",
                "[squid_proxy]",
                'default_allowed_domains = [".openai.com"]',
                'default_allowed_ip_addresses = ["203.0.113.0/24"]',
                "",
                "[haproxy]",
                'backend_host = "host.docker.internal"',
                "default_ports = [3306]",
                "",
                "[mcp_sidecar]",
                'default_tools = ["get_active_items"]',
                'default_resources = ["answer_format"]',
                'container_capabilities = ["network"]',
                'application_capabilities = ["openai"]',
            ]
        ),
        encoding="utf-8",
    )

    spec = load_sandbox_run_spec(spec_path)

    assert spec.schema_version == 1
    assert spec.agent_spec_paths == ((tmp_path / "agent_1.toml").resolve(),)
    assert spec.network.subnet == "172.28.0.0/24"
    assert spec.execution.order == ("agent_1",)
    assert spec.squid_proxy.default_allowed_domains == (".openai.com",)
    assert spec.squid_proxy.default_allowed_ip_addresses == ("203.0.113.0/24",)
    assert spec.haproxy.backend_host == "host.docker.internal"
    assert spec.haproxy.default_ports == (3306,)
    assert spec.mcp_sidecar.default_tools == ("get_active_items",)
    assert spec.mcp_sidecar.default_resources == ("answer_format",)
    assert spec.mcp_sidecar.container_capabilities == ("network",)
    assert spec.mcp_sidecar.application_capabilities == ("openai",)


def test_default_sandbox_run_spec_starts_support_agents_before_entry_agent() -> None:
    """Verify the default run includes specialist bug assessment services."""
    spec_path = Path("src") / "sandbox_agent" / "sandbox_run.toml"
    repository_root = Path.cwd()

    spec = load_sandbox_run_spec(spec_path)

    assert spec.agent_spec_paths == (
        repository_root / "src" / "frontend_agent" / "sandbox_spec.toml",
        repository_root / "src" / "backend_agent" / "sandbox_spec.toml",
        repository_root / "src" / "database_agent" / "sandbox_spec.toml",
        repository_root / "src" / "sandbox_agent" / "sandbox_spec.toml",
    )
    assert spec.execution.entry_agent == "agent_1"
    assert spec.execution.order == (
        "frontend_agent",
        "backend_agent",
        "database_agent",
        "agent_1",
    )


def test_default_bug_agents_use_a2a_without_shared_volume() -> None:
    """Verify default bug agents use A2A tasks without shared storage."""
    frontend_spec = load_agent_spec(
        Path("src") / "frontend_agent" / "sandbox_spec.toml"
    )
    backend_spec = load_agent_spec(Path("src") / "backend_agent" / "sandbox_spec.toml")
    database_spec = load_agent_spec(
        Path("src") / "database_agent" / "sandbox_spec.toml"
    )
    sandbox_spec = load_agent_spec(Path("src") / "sandbox_agent" / "sandbox_spec.toml")

    assert "a2a" in frontend_spec.application_capabilities
    assert "openai_agents" in frontend_spec.application_capabilities
    assert "a2a" in backend_spec.application_capabilities
    assert "openai_agents" in backend_spec.application_capabilities
    assert "a2a" in database_spec.application_capabilities
    assert "openai_agents" in database_spec.application_capabilities
    assert "a2a" in sandbox_spec.application_capabilities
    assert "shared_volume" not in frontend_spec.container_capabilities
    assert "shared_volume" not in backend_spec.container_capabilities
    assert "shared_volume" not in database_spec.container_capabilities
    assert "shared_volume" not in sandbox_spec.container_capabilities


def test_load_sandbox_run_spec_rejects_unknown_top_level_keys(
    tmp_path: Path,
) -> None:
    """Verify run-level specs fail closed for unsupported top-level keys."""
    spec_path = tmp_path / "sandbox_run.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agents = ["agent_1.toml"]',
                "unexpected = true",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported sandbox run spec key"):
        load_sandbox_run_spec(spec_path)


def test_load_sandbox_run_spec_rejects_unknown_table_keys(
    tmp_path: Path,
) -> None:
    """Verify run-level nested tables fail closed for unsupported keys."""
    spec_path = tmp_path / "sandbox_run.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agents = ["agent_1.toml"]',
                "[network]",
                'driver = "bridge"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported network key"):
        load_sandbox_run_spec(spec_path)


def test_load_sandbox_run_spec_requires_supported_schema_version(
    tmp_path: Path,
) -> None:
    """Verify unsupported run spec schema versions are rejected."""
    spec_path = tmp_path / "sandbox_run.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 2",
                'agents = ["agent_1.toml"]',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported sandbox run schema_version"):
        load_sandbox_run_spec(spec_path)


def test_load_sandbox_run_spec_requires_agents(tmp_path: Path) -> None:
    """Verify a run spec must declare at least one agent spec path."""
    spec_path = tmp_path / "sandbox_run.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                "agents = []",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="agents must be a non-empty"):
        load_sandbox_run_spec(spec_path)


def test_load_sandbox_run_spec_rejects_duplicate_agents(tmp_path: Path) -> None:
    """Verify duplicate agent spec paths are rejected."""
    spec_path = tmp_path / "sandbox_run.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agents = ["agent_1.toml", "agent_1.toml"]',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate agent spec path"):
        load_sandbox_run_spec(spec_path)


def test_load_sandbox_run_spec_rejects_invalid_subnet(tmp_path: Path) -> None:
    """Verify network subnets must be valid IP network notation."""
    spec_path = tmp_path / "sandbox_run.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agents = ["agent_1.toml"]',
                "[network]",
                'subnet = "not-a-subnet"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_sandbox_run_spec(spec_path)


def test_load_sandbox_run_spec_rejects_unknown_execution_mode(
    tmp_path: Path,
) -> None:
    """Verify execution mode is constrained to known orchestration modes."""
    spec_path = tmp_path / "sandbox_run.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agents = ["agent_1.toml"]',
                "[execution]",
                'mode = "pipeline"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported execution mode"):
        load_sandbox_run_spec(spec_path)


def test_load_sandbox_run_spec_rejects_url_domain_allowlist_entries(
    tmp_path: Path,
) -> None:
    """Verify Squid domains are host names rather than URLs or paths."""
    spec_path = tmp_path / "sandbox_run.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agents = ["agent_1.toml"]',
                "[squid_proxy]",
                'default_allowed_domains = ["https://example.com/path"]',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="host names"):
        load_sandbox_run_spec(spec_path)


def test_load_sandbox_run_spec_rejects_duplicate_haproxy_ports(
    tmp_path: Path,
) -> None:
    """Verify run-level HAProxy default ports must be unique."""
    spec_path = tmp_path / "sandbox_run.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agents = ["agent_1.toml"]',
                "[haproxy]",
                "default_ports = [3306, 3306]",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate default_ports"):
        load_sandbox_run_spec(spec_path)


def test_load_agent_spec_reads_split_agent_requirements(tmp_path: Path) -> None:
    """Verify agent-level TOML describes only one agent's requirements."""
    spec_path = tmp_path / "agent_1.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agent_id = "agent_1"',
                'module = "sandbox_agent"',
                'container_capabilities = ["network"]',
                "application_capabilities = ["
                '"image_artifacts", "mcp_client", "openai_agents"]',
                "",
                "[[environment_variables]]",
                'name = "APP_MODE"',
                'value = "test"',
                "",
                "[squid_proxy]",
                'allowed_domains = [".example.com"]',
                'allowed_ip_addresses = ["198.51.100.7"]',
                "",
                "[haproxy]",
                "ports = [3306]",
                "",
                "[mcp_sidecar]",
                'tools = ["get_active_items"]',
                'resources = ["answer_format"]',
            ]
        ),
        encoding="utf-8",
    )

    spec = load_agent_spec(spec_path)

    assert spec.agent_id == "agent_1"
    assert spec.module == "sandbox_agent"
    assert spec.container_capabilities == ("network",)
    assert spec.application_capabilities == (
        "image_artifacts",
        "mcp_client",
        "openai_agents",
    )
    assert spec.capabilities == (
        "network",
        "image_artifacts",
        "mcp_client",
        "openai_agents",
    )
    assert spec.environment_variables == (("APP_MODE", "test"),)
    assert spec.squid_proxy.allowed_domains == (".example.com",)
    assert spec.squid_proxy.allowed_ip_addresses == ("198.51.100.7",)
    assert spec.haproxy.ports == (3306,)
    assert spec.mcp_sidecar.tools == ("get_active_items",)
    assert spec.mcp_sidecar.resources == ("answer_format",)


def test_load_agent_spec_rejects_old_flat_capabilities(tmp_path: Path) -> None:
    """Verify the new agent spec no longer accepts ambiguous flat capabilities."""
    spec_path = tmp_path / "agent_1.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agent_id = "agent_1"',
                'module = "sandbox_agent"',
                'capabilities = ["network"]',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported agent spec key"):
        load_agent_spec(spec_path)


def test_load_agent_spec_requires_agent_id_and_module(tmp_path: Path) -> None:
    """Verify agent specs require identity and module routing fields."""
    spec_path = tmp_path / "agent_1.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agent_id = "agent_1"',
                'container_capabilities = ["network"]',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="module must be a non-empty string"):
        load_agent_spec(spec_path)


def test_load_agent_spec_rejects_unknown_container_capability(
    tmp_path: Path,
) -> None:
    """Verify container capabilities are validated independently."""
    spec_path = tmp_path / "agent_1.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agent_id = "agent_1"',
                'module = "sandbox_agent"',
                'container_capabilities = ["network", "haproxy"]',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported container capability"):
        load_agent_spec(spec_path)


def test_load_agent_spec_rejects_unknown_application_capability(
    tmp_path: Path,
) -> None:
    """Verify application capabilities are validated independently."""
    spec_path = tmp_path / "agent_1.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agent_id = "agent_1"',
                'module = "sandbox_agent"',
                'application_capabilities = ["haproxy"]',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported application capability"):
        load_agent_spec(spec_path)


def test_load_agent_spec_networked_application_capabilities_require_network(
    tmp_path: Path,
) -> None:
    """Verify networked application runtimes require container network access."""
    spec_path = tmp_path / "agent_1.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agent_id = "agent_1"',
                'module = "sandbox_agent"',
                'application_capabilities = ["a2a"]',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires the network capability"):
        load_agent_spec(spec_path)


def test_load_agent_spec_rejects_unknown_agent_table_keys(
    tmp_path: Path,
) -> None:
    """Verify agent-level nested tables fail closed for unsupported keys."""
    spec_path = tmp_path / "agent_1.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agent_id = "agent_1"',
                'module = "sandbox_agent"',
                "[mcp_sidecar]",
                'toolz = ["get_active_items"]',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported mcp_sidecar key"):
        load_agent_spec(spec_path)


def test_load_agent_spec_rejects_duplicate_haproxy_ports(tmp_path: Path) -> None:
    """Verify agent-level HAProxy ports must be unique."""
    spec_path = tmp_path / "agent_1.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agent_id = "agent_1"',
                'module = "sandbox_agent"',
                "[haproxy]",
                "ports = [3306, 3306]",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate ports"):
        load_agent_spec(spec_path)


def test_load_agent_spec_rejects_url_domain_allowlist_entries(
    tmp_path: Path,
) -> None:
    """Verify agent-level Squid domains are host names rather than URLs."""
    spec_path = tmp_path / "agent_1.toml"
    spec_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agent_id = "agent_1"',
                'module = "sandbox_agent"',
                "[squid_proxy]",
                'allowed_domains = ["https://example.com/path"]',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="host names"):
        load_agent_spec(spec_path)


def test_build_sandbox_plan_resolves_shared_sidecars_and_agents() -> None:
    """Verify the planner resolves names, IPs, sidecars, and agent settings."""
    run_spec = SandboxRunSpec(
        schema_version=1,
        agent_spec_paths=(Path("agent_1.toml"), Path("agent_2.toml")),
        network=NetworkSpec(enabled=True, internal=True, subnet="172.28.0.0/24"),
        execution=ExecutionSpec(mode="sequential", order=("agent_2", "agent_1")),
        squid_proxy=SquidProxySpec(
            default_allowed_domains=(".openai.com",),
            default_allowed_ip_addresses=("203.0.113.10",),
        ),
        haproxy=HAProxySpec(
            backend_host="host.docker.internal",
            default_ports=(3306,),
        ),
        mcp_sidecar=McpSidecarSpec(
            default_tools=("get_html_element_name",),
            default_resources=("answer_format",),
            container_capabilities=("network",),
        ),
    )
    agent_1 = AgentSpec(
        agent_id="agent_1",
        module="sandbox_agent",
        container_capabilities=("network",),
        application_capabilities=("mcp_client", "openai_agents"),
        environment_variables=(("APP_MODE", "writer"),),
        squid_proxy=AgentSquidProxySpec(allowed_domains=(".example.com",)),
        haproxy=AgentHAProxySpec(ports=(3307,)),
        mcp_sidecar=AgentMcpSidecarSpec(tools=("get_active_items",)),
    )
    agent_2 = AgentSpec(
        agent_id="agent_2",
        module="review_agent",
        container_capabilities=("network",),
        application_capabilities=("mcp_client", "openai_agents"),
        mcp_sidecar=AgentMcpSidecarSpec(tools=("microsoft_docs_search",)),
    )

    plan = build_sandbox_plan(run_spec, (agent_1, agent_2), "run-2026-07-23")

    assert plan.network_name == "sandbox-agent-net-run-2026-07-23"
    assert plan.subnet == "172.28.0.0/24"
    assert plan.agent_ids() == ("agent_2", "agent_1")
    assert plan.squid_proxy.enabled
    assert plan.squid_proxy.container_name == "squid-proxy-run-2026-07-23"
    assert plan.squid_proxy.ip_address == "172.28.0.2"
    assert plan.haproxy.enabled
    assert plan.haproxy.ip_address == "172.28.0.4"
    assert plan.haproxy.default_ports == (3306,)
    assert plan.mcp_sidecar.enabled
    assert plan.mcp_sidecar.ip_address == "172.28.0.3"
    assert plan.mcp_sidecar.tools == (
        "get_html_element_name",
        "microsoft_docs_search",
        "get_active_items",
    )
    assert plan.mcp_sidecar.resources == ("answer_format",)

    first_agent = plan.agents[0]
    second_agent = plan.agents[1]
    assert first_agent.agent_id == "agent_2"
    assert first_agent.ip_address == "172.28.0.11"
    assert first_agent.command == ("python", "-m", "review_agent")
    assert first_agent.mcp_sidecar_url == "http://mcp-sidecar:8000/mcp"
    assert first_agent.http_proxy == "http://egress-gateway:3128"
    assert first_agent.no_proxy == (
        "localhost",
        "127.0.0.1",
        "mcp-sidecar",
        "haproxy-sidecar",
    )
    assert second_agent.agent_id == "agent_1"
    assert second_agent.ip_address == "172.28.0.12"
    assert second_agent.environment_variables == (("APP_MODE", "writer"),)
    assert second_agent.haproxy_ports == (3307,)
    assert plan.squid_proxy.allowed_domains_for(second_agent) == (
        ".openai.com",
        ".example.com",
    )
    assert plan.haproxy.ports_for(second_agent) == (3306, 3307)


def test_build_sandbox_plan_uses_defaults_for_execution_order_and_subnet() -> None:
    """Verify omitted execution order and subnet still produce a complete plan."""
    run_spec = SandboxRunSpec(
        schema_version=1,
        agent_spec_paths=(Path("agent_1.toml"),),
    )
    agent = AgentSpec(
        agent_id="agent_1",
        module="sandbox_agent",
        container_capabilities=("network",),
    )

    plan = build_sandbox_plan(run_spec, (agent,), "run-test")

    assert plan.execution.order == ("agent_1",)
    assert plan.subnet == "172.28.0.0/24"
    assert plan.agents[0].ip_address == "172.28.0.11"


def test_build_sandbox_plan_rejects_duplicate_agent_ids() -> None:
    """Verify the planner rejects duplicate agent identities."""
    run_spec = SandboxRunSpec(
        schema_version=1,
        agent_spec_paths=(Path("agent_1.toml"), Path("agent_2.toml")),
    )
    agent = AgentSpec(agent_id="agent_1", module="sandbox_agent")

    with pytest.raises(ValueError, match="Duplicate agent_id"):
        build_sandbox_plan(run_spec, (agent, agent), "run-test")


def test_build_sandbox_plan_rejects_incomplete_execution_order() -> None:
    """Verify execution order must name every declared agent exactly once."""
    run_spec = SandboxRunSpec(
        schema_version=1,
        agent_spec_paths=(Path("agent_1.toml"), Path("agent_2.toml")),
        execution=ExecutionSpec(order=("agent_1",)),
    )
    agents = (
        AgentSpec(agent_id="agent_1", module="sandbox_agent"),
        AgentSpec(agent_id="agent_2", module="review_agent"),
    )

    with pytest.raises(ValueError, match="missing agent_id"):
        build_sandbox_plan(run_spec, agents, "run-test")


def test_build_sandbox_plan_rejects_disabled_network_when_agent_needs_it() -> None:
    """Verify the run-level network switch is enforced by the planner."""
    run_spec = SandboxRunSpec(
        schema_version=1,
        agent_spec_paths=(Path("agent_1.toml"),),
        network=NetworkSpec(enabled=False),
    )
    agent = AgentSpec(
        agent_id="agent_1",
        module="sandbox_agent",
        container_capabilities=("network",),
    )

    with pytest.raises(ValueError, match="Network is disabled"):
        build_sandbox_plan(run_spec, (agent,), "run-test")


def test_build_sandbox_plan_rejects_mcp_exposure_without_network() -> None:
    """Verify exposed MCP tools require sidecar network capability."""
    run_spec = SandboxRunSpec(
        schema_version=1,
        agent_spec_paths=(Path("agent_1.toml"),),
    )
    agent = AgentSpec(
        agent_id="agent_1",
        module="sandbox_agent",
        container_capabilities=("network",),
        application_capabilities=("mcp_client",),
        mcp_sidecar=AgentMcpSidecarSpec(tools=("get_active_items",)),
    )

    with pytest.raises(ValueError, match="MCP sidecar exposure requires"):
        build_sandbox_plan(run_spec, (agent,), "run-test")


def test_build_sandbox_plan_rejects_image_tool_without_sidecar_openai() -> None:
    """Verify image generation exposure requires sidecar OpenAI support."""
    run_spec = SandboxRunSpec(
        schema_version=1,
        agent_spec_paths=(Path("agent_1.toml"),),
        mcp_sidecar=McpSidecarSpec(container_capabilities=("network",)),
    )
    agent = AgentSpec(
        agent_id="agent_1",
        module="sandbox_agent",
        container_capabilities=("network",),
        application_capabilities=("mcp_client",),
        mcp_sidecar=AgentMcpSidecarSpec(tools=("generate_image",)),
    )

    with pytest.raises(ValueError, match="requires the openai capability"):
        build_sandbox_plan(run_spec, (agent,), "run-test")


def test_load_sandbox_plan_loads_run_and_agent_specs(tmp_path: Path) -> None:
    """Verify the planner can load a full run from TOML files."""
    agent_path = tmp_path / "agent_1.toml"
    agent_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agent_id = "agent_1"',
                'module = "sandbox_agent"',
                'container_capabilities = ["network"]',
                'application_capabilities = ["mcp_client"]',
                "[mcp_sidecar]",
                'tools = ["get_active_items"]',
            ]
        ),
        encoding="utf-8",
    )
    run_path = tmp_path / "sandbox_run.toml"
    run_path.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'agents = ["agent_1.toml"]',
                "[mcp_sidecar]",
                'container_capabilities = ["network"]',
            ]
        ),
        encoding="utf-8",
    )

    plan = load_sandbox_plan(run_path, "run-test")

    assert plan.agent_ids() == ("agent_1",)
    assert plan.mcp_sidecar.tools == ("get_active_items",)


def test_save_resolved_sandbox_plan_writes_run_artifact(tmp_path: Path) -> None:
    """Verify resolved plans can be saved as a named run artifact."""
    plan = ResolvedSandboxPlan(
        run_id="run-test",
        network_name="sandbox-agent-net-run-test",
        subnet="172.28.0.0/24",
        agents=(),
        squid_proxy=ResolvedSquidPlan(enabled=False),
        haproxy=ResolvedHAProxyPlan(enabled=False),
        mcp_sidecar=ResolvedMcpSidecarPlan(enabled=False),
    )

    plan_path = save_resolved_sandbox_plan(plan, tmp_path)

    assert plan_path == tmp_path / "resolved-sandbox-plan.json"
    assert '"run_id": "run-test"' in plan_path.read_text(encoding="utf-8")


def test_build_network_create_command_uses_planned_subnet() -> None:
    """Verify Docker network creation uses the resolved subnet and internal flag."""
    plan = _build_two_agent_plan()

    command = build_network_create_command(plan)

    assert command == [
        "docker",
        "network",
        "create",
        "--internal",
        "--subnet",
        "172.28.0.0/24",
        "sandbox-agent-net-run-test",
    ]


def test_build_network_create_command_omits_internal_flag_when_public() -> None:
    """Verify the run-level internal network flag is preserved in network commands."""
    run_spec = SandboxRunSpec(
        schema_version=1,
        agent_spec_paths=(Path("agent_1.toml"),),
        network=NetworkSpec(enabled=True, internal=False, subnet="172.28.0.0/24"),
    )
    agent = AgentSpec(
        agent_id="agent_1",
        module="sandbox_agent",
        container_capabilities=("network",),
    )
    plan = build_sandbox_plan(run_spec, (agent,), "run-test")

    command = build_network_create_command(plan)

    assert command == [
        "docker",
        "network",
        "create",
        "--subnet",
        "172.28.0.0/24",
        "sandbox-agent-net-run-test",
    ]


def test_build_container_network_options_assigns_stable_ip_and_alias() -> None:
    """Verify planned containers can join the network with deterministic IPs."""
    plan = _build_two_agent_plan()

    options = build_container_network_options(
        plan,
        plan.mcp_sidecar.ip_address,
        "mcp-sidecar",
    )

    assert options == [
        "--network",
        "sandbox-agent-net-run-test",
        "--network-alias",
        "mcp-sidecar",
        "--ip",
        "172.28.0.3",
    ]


def test_build_squid_acl_configuration_scopes_domains_by_source_ip() -> None:
    """Verify Squid defaults apply to all agents and agent domains stay scoped."""
    plan = _build_two_agent_plan()

    config = build_squid_acl_configuration(plan)

    assert "acl agent_agent_1 src 172.28.0.11" in config
    assert "acl agent_agent_2 src 172.28.0.12" in config
    assert "acl planned_agents src 172.28.0.11 172.28.0.12" in config
    assert "acl default_allowed_sites dstdomain .openai.com" in config
    assert "http_access allow planned_agents default_allowed_sites" in config
    assert "acl agent_agent_1_allowed_sites dstdomain .example.com" in config
    assert "http_access allow agent_agent_1 agent_agent_1_allowed_sites" in config
    assert "http_access allow agent_agent_2 agent_agent_1_allowed_sites" not in config
    assert config.rstrip().endswith("cache_log /tmp/squid-cache.log")


def test_build_haproxy_acl_configuration_scopes_ports_by_source_ip() -> None:
    """Verify HAProxy default ports are shared and agent ports are scoped."""
    plan = _build_two_agent_plan()

    config = build_haproxy_acl_configuration(plan)

    assert "frontend tcp_3306" in config
    assert "    bind *:3306" in config
    assert "    acl mcp_sidecar src 172.28.0.3" in config
    assert "    tcp-request connection accept if agent_agent_1" in config
    assert "    tcp-request connection accept if agent_agent_2" in config
    assert "    tcp-request connection accept if mcp_sidecar" in config
    assert "frontend tcp_3307" in config
    assert "    bind *:3307" in config
    assert config.count("    tcp-request connection accept if agent_agent_1") == 2
    assert config.count("    tcp-request connection accept if agent_agent_2") == 1
    assert config.count("    tcp-request connection accept if mcp_sidecar") == 2
    assert "    server host_service host.docker.internal:3307" in config


def _build_two_agent_plan() -> ResolvedSandboxPlan:
    run_spec = SandboxRunSpec(
        schema_version=1,
        agent_spec_paths=(Path("agent_1.toml"), Path("agent_2.toml")),
        network=NetworkSpec(enabled=True, internal=True, subnet="172.28.0.0/24"),
        squid_proxy=SquidProxySpec(default_allowed_domains=(".openai.com",)),
        haproxy=HAProxySpec(
            backend_host="host.docker.internal",
            default_ports=(3306,),
        ),
        mcp_sidecar=McpSidecarSpec(
            default_tools=("get_html_element_name",),
            container_capabilities=("network",),
        ),
    )
    agent_1 = AgentSpec(
        agent_id="agent_1",
        module="sandbox_agent",
        container_capabilities=("network",),
        application_capabilities=("mcp_client",),
        squid_proxy=AgentSquidProxySpec(allowed_domains=(".example.com",)),
        haproxy=AgentHAProxySpec(ports=(3307,)),
        mcp_sidecar=AgentMcpSidecarSpec(tools=("get_active_items",)),
    )
    agent_2 = AgentSpec(
        agent_id="agent_2",
        module="review_agent",
        container_capabilities=("network",),
        application_capabilities=("mcp_client",),
        mcp_sidecar=AgentMcpSidecarSpec(tools=("microsoft_docs_search",)),
    )
    return build_sandbox_plan(run_spec, (agent_1, agent_2), "run-test")
