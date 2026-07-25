"""Tests for the OpenAI-backed Sandbox Agent workload."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

from sandbox_agent.openai_agent import create_openai_agent, run_red_green_coordinator


def test_create_openai_agent_uses_gpt_model_and_tools(monkeypatch) -> None:
    """Verify the coordinator is configured to call the required tools."""
    calls = []

    class _FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    _install_fake_agent_dependencies(monkeypatch, agent=_FakeAgent)

    create_openai_agent()

    assert calls[0]["name"] == "RedGreenTeam Coordinator"
    assert calls[0]["model"] == "gpt-4.1-mini"
    assert calls[0]["tools"] == [
        "tool:create_solution_skeleton",
        "tool:get_test_assessment",
        "tool:read_shared_file",
        "tool:request_code_update",
        "tool:request_solution_stub",
        "tool:request_test_creation",
        "tool:run_red_green_loop",
        "tool:save_answer",
        "tool:save_shared_file",
    ]
    assert "run the tester/coder red-green loop" in calls[0]["instructions"]


def test_create_openai_agent_accepts_explicit_model(monkeypatch) -> None:
    """Verify callers can override the hosted model name."""
    requested_models = []

    class _FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            requested_models.append(kwargs["model"])

    _install_fake_agent_dependencies(monkeypatch, agent=_FakeAgent)

    create_openai_agent("gpt-5-mini")

    assert requested_models == ["gpt-5-mini"]


def test_run_red_green_coordinator_lets_model_sequence_tool_calls(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify Runner receives the RedGreen coordinator prompt."""
    calls = []

    class _FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            calls.append({"type": "agent", **kwargs})

    class _FakeRunner:
        @staticmethod
        def run_sync(
            agent: _FakeAgent,
            prompt: str,
            max_turns: int,
        ) -> SimpleNamespace:
            calls.append(
                {
                    "type": "run",
                    "agent": agent,
                    "prompt": prompt,
                    "max_turns": max_turns,
                }
            )
            return SimpleNamespace(final_output="solution.py scaffolded.")

    _install_fake_agent_dependencies(
        monkeypatch,
        agent=_FakeAgent,
        runner=_FakeRunner,
    )
    monkeypatch.setattr("sandbox_agent.openai_agent._SITE_DIRECTORY", tmp_path / "site")

    result = run_red_green_coordinator()

    assert result == "solution.py scaffolded."
    assert (tmp_path / "site").exists()
    assert calls[0]["type"] == "agent"
    assert calls[0]["model"] == "gpt-4.1-mini"
    assert calls[0]["tools"] == [
        "tool:create_solution_skeleton",
        "tool:get_test_assessment",
        "tool:read_shared_file",
        "tool:request_code_update",
        "tool:request_solution_stub",
        "tool:request_test_creation",
        "tool:run_red_green_loop",
        "tool:save_answer",
        "tool:save_shared_file",
    ]
    assert calls[1]["type"] == "run"
    assert "Coordinate the RedGreenTeam" in calls[1]["prompt"]
    assert "Implement slugify_title(title: str) -> str" in calls[1]["prompt"]
    assert "run_red_green_loop exactly once" in calls[1]["prompt"]
    assert "max_iterations=10" in calls[1]["prompt"]
    assert "/sandbox-shared/solution.py" in calls[1]["prompt"]
    assert (
        "asks tester_agent to create /sandbox-shared/tests.py once"
        in calls[1]["prompt"]
    )
    assert "asks coder_agent for an" in calls[1]["prompt"]
    assert "answer.txt" in calls[1]["prompt"]
    assert calls[1]["max_turns"] == 14


def test_run_red_green_coordinator_accepts_explicit_model(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify run_red_green_coordinator forwards explicit model choices."""
    requested_models = []

    class _FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            requested_models.append(kwargs["model"])

    _install_fake_agent_dependencies(monkeypatch, agent=_FakeAgent)
    monkeypatch.setattr("sandbox_agent.openai_agent._SITE_DIRECTORY", tmp_path / "site")

    result = run_red_green_coordinator("gpt-5-mini")

    assert result == "ok"
    assert requested_models == ["gpt-5-mini"]


def _install_fake_agent_dependencies(
    monkeypatch,
    *,
    agent: type | None = None,
    runner: type | None = None,
) -> None:
    if agent is None:

        class _FakeAgent:
            def __init__(self, **kwargs: Any) -> None:
                pass

        agent = _FakeAgent

    if runner is None:

        class _FakeRunner:
            @staticmethod
            def run_sync(
                agent: Any,
                prompt: str,
                max_turns: int,
            ) -> SimpleNamespace:
                _ = agent
                _ = prompt
                _ = max_turns
                return SimpleNamespace(final_output="ok")

        runner = _FakeRunner

    fake_agents_module = SimpleNamespace(
        Agent=agent,
        Runner=runner,
    )
    fake_openai_tools_module = SimpleNamespace(
        create_solution_skeleton_tool="tool:create_solution_skeleton",
        generate_image_artifact_tool="tool:generate_image_artifact",
        generate_image_tool="tool:generate_image",
        get_active_items_tool="tool:get_active_items",
        get_html_element_name_tool="tool:get_html_element_name",
        get_test_assessment_tool="tool:get_test_assessment",
        read_shared_file_tool="tool:read_shared_file",
        request_code_update_tool="tool:request_code_update",
        request_solution_stub_tool="tool:request_solution_stub",
        request_test_creation_tool="tool:request_test_creation",
        run_red_green_loop_tool="tool:run_red_green_loop",
        save_answer_tool="tool:save_answer",
        save_html_document_tool="tool:save_html_document",
        save_image_tool="tool:save_image",
        save_shared_file_tool="tool:save_shared_file",
        save_shared_image_artifact_tool="tool:save_shared_image_artifact",
    )
    monkeypatch.setitem(sys.modules, "agents", fake_agents_module)
    monkeypatch.setitem(
        sys.modules,
        "sandbox_agent.openai_tools",
        fake_openai_tools_module,
    )
