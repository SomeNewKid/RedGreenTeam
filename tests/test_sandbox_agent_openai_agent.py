"""Tests for the OpenAI-backed Sandbox Agent workload."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

from sandbox_agent.openai_agent import create_openai_agent, run_html_element_agent


def test_create_openai_agent_uses_gpt_model_and_tools(monkeypatch) -> None:
    """Verify the agent is configured to let GPT call the required tools."""
    calls = []

    class _FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    _install_fake_agent_dependencies(monkeypatch, agent=_FakeAgent)

    create_openai_agent()

    assert calls[0]["name"] == "Bug Report Manager"
    assert calls[0]["model"] == "gpt-4.1-mini"
    assert calls[0]["tools"] == [
        "tool:get_parallel_bug_assessments",
        "tool:save_answer",
    ]
    assert (
        "Do not finish until both tool calls have succeeded."
        in (calls[0]["instructions"])
    )


def test_create_openai_agent_accepts_explicit_model(monkeypatch) -> None:
    """Verify callers can override the hosted model name."""
    requested_models = []

    class _FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            requested_models.append(kwargs["model"])

    _install_fake_agent_dependencies(monkeypatch, agent=_FakeAgent)

    create_openai_agent("gpt-5-mini")

    assert requested_models == ["gpt-5-mini"]


def test_run_html_element_agent_lets_model_sequence_tool_calls(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify Runner receives a tool-oriented prompt instead of precomputed HTML."""
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
            return SimpleNamespace(final_output="index.html lists 1 active item.")

    _install_fake_agent_dependencies(
        monkeypatch,
        agent=_FakeAgent,
        runner=_FakeRunner,
    )
    monkeypatch.setattr("sandbox_agent.openai_agent._SITE_DIRECTORY", tmp_path / "site")

    result = run_html_element_agent()

    assert result == "index.html lists 1 active item."
    assert (tmp_path / "site").exists()
    assert calls[0]["type"] == "agent"
    assert calls[0]["model"] == "gpt-4.1-mini"
    assert calls[0]["tools"] == [
        "tool:get_parallel_bug_assessments",
        "tool:save_answer",
    ]
    assert calls[1]["type"] == "run"
    assert "Assess this fictional software bug report" in calls[1]["prompt"]
    assert "get_parallel_bug_assessments exactly once" in calls[1]["prompt"]
    assert "frontend, backend, and database" in calls[1]["prompt"]
    assert "final likely category and priority" in calls[1]["prompt"]
    assert "exactly once" in calls[1]["prompt"]
    assert "Treat the response as a JSON object" in calls[1]["prompt"]
    assert "save_answer tool" in calls[1]["prompt"]
    assert calls[1]["max_turns"] == 14


def test_run_html_element_agent_accepts_explicit_model(tmp_path, monkeypatch) -> None:
    """Verify run_html_element_agent forwards explicit model choices."""
    requested_models = []

    class _FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            requested_models.append(kwargs["model"])

    _install_fake_agent_dependencies(monkeypatch, agent=_FakeAgent)
    monkeypatch.setattr("sandbox_agent.openai_agent._SITE_DIRECTORY", tmp_path / "site")

    result = run_html_element_agent("gpt-5-mini")

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
        generate_image_artifact_tool="tool:generate_image_artifact",
        generate_image_tool="tool:generate_image",
        get_active_items_tool="tool:get_active_items",
        get_html_element_name_tool="tool:get_html_element_name",
        get_parallel_bug_assessments_tool="tool:get_parallel_bug_assessments",
        save_answer_tool="tool:save_answer",
        save_html_document_tool="tool:save_html_document",
        save_image_tool="tool:save_image",
        save_shared_image_artifact_tool="tool:save_shared_image_artifact",
    )
    monkeypatch.setitem(sys.modules, "agents", fake_agents_module)
    monkeypatch.setitem(
        sys.modules,
        "sandbox_agent.openai_tools",
        fake_openai_tools_module,
    )
