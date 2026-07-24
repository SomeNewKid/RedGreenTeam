"""Tests for bug assessment worker agent packages."""

from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol, cast

import pytest

from docker_sandbox.sandbox_plan import load_agent_spec

_AGENT_CASES = (
    (
        "frontend_agent",
        "Frontend Bug Assessor",
        "web frontend",
        "The button is clipped on mobile.",
    ),
    (
        "backend_agent",
        "Backend Bug Assessor",
        "web server backend",
        "The API returns HTTP 500 during checkout.",
    ),
    (
        "database_agent",
        "Database Bug Assessor",
        "database",
        "Saved records disappear after refresh.",
    ),
)


class _JsonRpcServerModule(Protocol):
    _OUTPUT_DIRECTORY: Path

    def _handle_json_rpc_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]: ...


@pytest.mark.parametrize(
    ("package_name", "agent_name", "area", "bug_report"),
    _AGENT_CASES,
)
def test_create_bug_assessment_agent_uses_gpt_4_1_mini(
    monkeypatch,
    package_name: str,
    agent_name: str,
    area: str,
    bug_report: str,
) -> None:
    """Verify worker agents are configured for OpenAI Agents SDK assessment."""
    _ = area
    _ = bug_report
    calls = []

    class _FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    _install_fake_agent_dependencies(monkeypatch, agent=_FakeAgent)
    module = importlib.import_module(f"{package_name}.openai_agent")
    create_agent = getattr(module, f"create_{package_name}")

    create_agent()

    assert calls[0]["name"] == agent_name
    assert calls[0]["model"] == "gpt-4.1-mini"
    assert "valid JSON" in calls[0]["instructions"]


@pytest.mark.parametrize(
    ("package_name", "agent_name", "area", "bug_report"),
    _AGENT_CASES,
)
def test_run_bug_assessment_agent_returns_validated_json(
    monkeypatch,
    package_name: str,
    agent_name: str,
    area: str,
    bug_report: str,
) -> None:
    """Verify worker agent output is parsed into the required schema."""
    _ = agent_name
    prompts = []

    class _FakeRunner:
        @staticmethod
        def run_sync(agent: object, prompt: str, max_turns: int) -> SimpleNamespace:
            _ = agent
            prompts.append((prompt, max_turns))
            return SimpleNamespace(
                final_output=json.dumps(
                    {
                        "area": area,
                        "likelihood_percent": 82,
                        "reasons": [
                            "The symptoms match this specialist area.",
                            "The report does not give stronger evidence elsewhere.",
                        ],
                    }
                )
            )

    _install_fake_agent_dependencies(monkeypatch, runner=_FakeRunner)
    module = importlib.import_module(f"{package_name}.openai_agent")
    run_agent = getattr(module, f"run_{package_name}")

    result = run_agent(bug_report)

    assert result["area"] == area
    assert result["likelihood_percent"] == 82
    assert len(result["reasons"]) == 2
    assert bug_report in prompts[0][0]
    assert prompts[0][1] == 4


@pytest.mark.parametrize(
    ("package_name", "agent_name", "area", "bug_report"),
    _AGENT_CASES,
)
def test_bug_assessment_a2a_message_send_returns_task_artifact(
    monkeypatch,
    tmp_path: Path,
    package_name: str,
    agent_name: str,
    area: str,
    bug_report: str,
) -> None:
    """Verify worker A2A surfaces complete task-based assessments."""
    _ = agent_name
    server_module = cast(
        _JsonRpcServerModule,
        importlib.import_module(f"{package_name}.a2a_server"),
    )

    def fake_run_agent(received_bug_report: str) -> dict[str, object]:
        assert received_bug_report == bug_report
        return {
            "area": area,
            "likelihood_percent": 67,
            "reasons": [
                "The report includes a relevant symptom.",
                "The worker can still answer not my area when evidence is weak.",
            ],
        }

    monkeypatch.setattr(server_module, f"run_{package_name}", fake_run_agent)
    monkeypatch.setattr(server_module, "_OUTPUT_DIRECTORY", tmp_path)

    response = server_module._handle_json_rpc_request(
        {
            "jsonrpc": "2.0",
            "id": "request-1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": bug_report}],
                }
            },
        }
    )

    result = response["result"]
    assert isinstance(result, dict)
    assert result["kind"] == "task"
    status = result["status"]
    assert isinstance(status, dict)
    assert status["state"] == "TASK_STATE_SUBMITTED"
    task_id = result["id"]
    assert isinstance(task_id, str)

    task = _wait_for_completed_task(server_module, task_id)
    artifacts = task["artifacts"]
    assert isinstance(artifacts, list)
    artifact = artifacts[0]
    assert isinstance(artifact, dict)
    parts = artifact["parts"]
    assert isinstance(parts, list)
    part = parts[0]
    assert isinstance(part, dict)
    assessment = json.loads(part["text"])
    assert assessment["area"] == area
    assert assessment["likelihood_percent"] == 67
    assert part["metadata"] == {"mimeType": "application/json"}

    assessment_path = tmp_path / "assessment.json"
    assert assessment_path.exists()
    assert assessment_path.read_text(encoding="utf-8") == (
        json.dumps(assessment, indent=2, sort_keys=True) + "\n"
    )


@pytest.mark.parametrize(
    ("package_name", "agent_name", "area", "bug_report"),
    _AGENT_CASES,
)
def test_bug_assessment_sandbox_specs_include_openai_agents(
    package_name: str,
    agent_name: str,
    area: str,
    bug_report: str,
) -> None:
    """Verify new worker specs declare the OpenAI Agents SDK capability."""
    _ = agent_name
    _ = area
    _ = bug_report
    spec = load_agent_spec(Path("src") / package_name / "sandbox_spec.toml")

    assert spec.agent_id == package_name
    assert spec.module == package_name
    assert "a2a" in spec.application_capabilities
    assert "openai_agents" in spec.application_capabilities


def _wait_for_completed_task(
    server_module: _JsonRpcServerModule,
    task_id: str,
) -> dict[str, object]:
    for _ in range(50):
        task_response = server_module._handle_json_rpc_request(
            {
                "jsonrpc": "2.0",
                "id": "request-2",
                "method": "tasks/get",
                "params": {
                    "id": task_id,
                    "historyLength": 0,
                },
            }
        )
        task = task_response["result"]
        assert isinstance(task, dict)
        status = task["status"]
        assert isinstance(status, dict)
        if status["state"] == "TASK_STATE_COMPLETED":
            return task
        time.sleep(0.01)

    raise AssertionError("Bug assessment task did not complete.")


def _install_fake_agent_dependencies(
    monkeypatch,
    *,
    agent: type | None = None,
    runner: type | None = None,
) -> None:
    if agent is None:

        class _FakeAgent:
            def __init__(self, **kwargs: Any) -> None:
                _ = kwargs

        agent = _FakeAgent

    if runner is None:

        class _FakeRunner:
            @staticmethod
            def run_sync(agent: object, prompt: str, max_turns: int) -> SimpleNamespace:
                _ = agent
                _ = prompt
                _ = max_turns
                return SimpleNamespace(
                    final_output=json.dumps(
                        {
                            "area": "web frontend",
                            "likelihood_percent": 50,
                            "reasons": [
                                "The report could involve this area.",
                                "More evidence is needed for certainty.",
                            ],
                        }
                    )
                )

        runner = _FakeRunner

    fake_agents_module = SimpleNamespace(
        Agent=agent,
        Runner=runner,
    )
    monkeypatch.setitem(sys.modules, "agents", fake_agents_module)
