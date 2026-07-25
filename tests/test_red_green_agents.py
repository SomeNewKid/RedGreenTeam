"""Tests for RedGreenTeam scaffold agent packages."""

from __future__ import annotations

import importlib
import json
import time
from pathlib import Path
from typing import Protocol, cast

import pytest


class _JsonRpcServerModule(Protocol):
    _OUTPUT_DIRECTORY: Path

    def _handle_json_rpc_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]: ...


_AGENT_CASES = (
    ("tester_agent", "tester_agent"),
    ("coder_agent", "coder_agent"),
)


@pytest.mark.parametrize(("package_name", "agent_name"), _AGENT_CASES)
def test_red_green_a2a_message_send_returns_task_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    package_name: str,
    agent_name: str,
) -> None:
    """Verify RedGreenTeam scaffold agents expose task-based A2A surfaces."""
    server_module = cast(
        _JsonRpcServerModule,
        importlib.import_module(f"{package_name}.a2a_server"),
    )
    monkeypatch.setattr(server_module, "_OUTPUT_DIRECTORY", tmp_path)
    if package_name == "tester_agent":

        def fake_run_solution_tests() -> dict[str, object]:
            return {
                "agent": "tester_agent",
                "status": "failed",
                "passed": False,
                "message": "Stubbed test result.",
            }

        monkeypatch.setattr(
            server_module, "run_solution_tests", fake_run_solution_tests
        )
    if package_name == "coder_agent":

        def fake_update_solution(requirement: str) -> dict[str, object]:
            return {
                "agent": "coder_agent",
                "status": "updated",
                "updated": True,
                "message": f"Stubbed update for: {requirement}",
            }

        monkeypatch.setattr(server_module, "update_solution", fake_update_solution)

    response = server_module._handle_json_rpc_request(
        {
            "jsonrpc": "2.0",
            "id": "request-1",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Prepare solution.py."}],
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
    scaffold_result = json.loads(part["text"])

    assert scaffold_result["agent"] == agent_name
    if package_name == "tester_agent":
        assert scaffold_result["status"] == "failed"
        assert scaffold_result["passed"] is False
        assert scaffold_result["message"] == "Stubbed test result."
    else:
        assert scaffold_result["status"] == "updated"
        assert scaffold_result["updated"] is True
        assert scaffold_result["message"] == "Stubbed update for: Prepare solution.py."
    assert part["metadata"] == {"mimeType": "application/json"}


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

    raise AssertionError("RedGreenTeam scaffold task did not complete.")
