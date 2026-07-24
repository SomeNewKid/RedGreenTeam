"""Tests for shared A2A support helpers."""

from __future__ import annotations

import pytest

from a2a_support.client import (
    TextTaskRequest,
    read_agent_endpoint_url,
    read_message_text_result,
    send_text_tasks_and_wait_for_text_artifacts,
)
from a2a_support.server import (
    build_agent_card,
    json_rpc_error,
    json_rpc_text_result,
    read_message_text,
)


def test_build_agent_card_uses_public_a2a_endpoint() -> None:
    """Verify Agent Cards expose the JSON-RPC endpoint URL."""
    card = build_agent_card(
        name="Writer Agent",
        description="Writes movie concepts.",
        public_base_url="http://writer-agent:8080/",
        skills=[{"id": "write_movie_concept"}],
    )

    assert card["name"] == "Writer Agent"
    assert card["url"] == "http://writer-agent:8080/a2a"
    assert card["skills"] == [{"id": "write_movie_concept"}]


def test_read_message_text_joins_text_parts() -> None:
    """Verify JSON-RPC message text parts are read in order."""
    text = read_message_text(
        {
            "message": {
                "parts": [
                    {"kind": "text", "text": "First"},
                    {"kind": "data", "data": {"ignored": True}},
                    {"kind": "text", "text": "Second"},
                ]
            }
        }
    )

    assert text == "First\n\nSecond"


def test_json_rpc_text_result_can_be_read_by_client_helper() -> None:
    """Verify server text results match the shared client reader."""
    response = json_rpc_text_result(
        request_id="request-1",
        text='{"title": "Moon Harbor"}',
        mime_type="application/json",
    )

    assert read_message_text_result(response["result"]) == '{"title": "Moon Harbor"}'


def test_json_rpc_error_uses_standard_error_shape() -> None:
    """Verify JSON-RPC error responses carry code and message."""
    response = json_rpc_error("request-1", -32601, "Unsupported method.")

    assert response == {
        "jsonrpc": "2.0",
        "id": "request-1",
        "error": {
            "code": -32601,
            "message": "Unsupported method.",
        },
    }


def test_read_agent_endpoint_url_requires_url() -> None:
    """Verify Agent Cards must include a usable endpoint URL."""
    with pytest.raises(RuntimeError, match="must include a URL"):
        read_agent_endpoint_url({})


def test_read_message_text_result_requires_text_part() -> None:
    """Verify client parsing fails closed when no text part is present."""
    with pytest.raises(RuntimeError, match="did not contain text"):
        read_message_text_result({"parts": [{"kind": "data", "data": {}}]})


def test_parallel_text_task_helper_starts_all_tasks_before_polling(monkeypatch) -> None:
    """Verify parallel task helper submits all work before polling any task."""
    calls = []
    task_states = {
        "frontend-task": "TASK_STATE_SUBMITTED",
        "backend-task": "TASK_STATE_SUBMITTED",
    }

    def fake_send_text_task(
        endpoint_url: str,
        text: str,
        request_id: str,
        timeout: int,
    ) -> dict[str, object]:
        calls.append(("send", endpoint_url, text, request_id, timeout))
        task_id = f"{request_id.removesuffix('-request')}"
        return _build_client_task(task_id, task_states[task_id])

    def fake_get_task(
        endpoint_url: str,
        task_id: str,
        request_id: str,
        timeout: int,
    ) -> dict[str, object]:
        calls.append(("get", endpoint_url, task_id, request_id, timeout))
        task_states[task_id] = "TASK_STATE_COMPLETED"
        return _build_client_task(
            task_id,
            "TASK_STATE_COMPLETED",
            artifact_text=f'{{"task": "{task_id}"}}',
        )

    monkeypatch.setattr("a2a_support.client.send_text_task", fake_send_text_task)
    monkeypatch.setattr("a2a_support.client.get_task", fake_get_task)

    results = send_text_tasks_and_wait_for_text_artifacts(
        (
            TextTaskRequest(
                name="frontend",
                endpoint_url="http://frontend-agent:8080/a2a",
                text="Bug report",
                request_id="frontend-task-request",
            ),
            TextTaskRequest(
                name="backend",
                endpoint_url="http://backend-agent:8080/a2a",
                text="Bug report",
                request_id="backend-task-request",
            ),
        ),
        timeout_seconds=30,
        poll_interval_seconds=0,
    )

    assert [call[0] for call in calls[:2]] == ["send", "send"]
    assert [result.name for result in results] == ["frontend", "backend"]
    assert [result.task_id for result in results] == ["frontend-task", "backend-task"]
    assert [result.text for result in results] == [
        '{"task": "frontend-task"}',
        '{"task": "backend-task"}',
    ]


def _build_client_task(
    task_id: str,
    state: str,
    artifact_text: str | None = None,
) -> dict[str, object]:
    task: dict[str, object] = {
        "kind": "task",
        "id": task_id,
        "contextId": f"{task_id}-context",
        "status": {
            "state": state,
        },
    }
    if artifact_text is not None:
        task["artifacts"] = [
            {
                "artifactId": f"{task_id}-artifact",
                "name": "Assessment",
                "parts": [
                    {
                        "kind": "text",
                        "text": artifact_text,
                    }
                ],
            }
        ]

    return task
