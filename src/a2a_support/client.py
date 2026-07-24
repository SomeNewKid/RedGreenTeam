"""Client helpers for small A2A HTTP integrations."""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

_TERMINAL_TASK_STATES = frozenset(
    {
        "TASK_STATE_COMPLETED",
        "TASK_STATE_FAILED",
        "TASK_STATE_CANCELED",
        "TASK_STATE_REJECTED",
    }
)


@dataclass(frozen=True)
class TextTaskRequest:
    """A request for one non-blocking A2A text task."""

    name: str
    endpoint_url: str
    text: str
    request_id: str


@dataclass(frozen=True)
class TextTaskArtifactResult:
    """The completed text artifact returned by one A2A task."""

    name: str
    task_id: str
    text: str


def read_agent_card(base_url: str, timeout: int = 10) -> dict[str, object]:
    """Read an A2A Agent Card from a base URL."""
    card_url = f"{base_url.rstrip('/')}/.well-known/agent.json"
    with _urlopen_no_proxy(card_url, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("A2A Agent Card must be a JSON object.")

    return data


def read_agent_endpoint_url(agent_card: dict[str, object]) -> str:
    """Read the JSON-RPC endpoint URL from an A2A Agent Card."""
    endpoint_url = agent_card.get("url")
    if not isinstance(endpoint_url, str) or not endpoint_url.strip():
        raise RuntimeError("A2A Agent Card must include a URL.")

    return endpoint_url.strip()


def send_text_message(
    endpoint_url: str,
    text: str,
    request_id: str = "a2a-message-request",
    timeout: int = 60,
) -> str:
    """Send a JSON-RPC message/send text request and return the response text."""
    request_body = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "kind": "text",
                        "text": text,
                    }
                ],
            }
        },
    }
    request = urllib.request.Request(
        endpoint_url,
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _urlopen_no_proxy(request, timeout=timeout) as response:
        response_data = json.loads(response.read().decode("utf-8"))
    if not isinstance(response_data, dict):
        raise RuntimeError("A2A response must be a JSON object.")
    if "error" in response_data:
        raise RuntimeError(f"A2A error: {response_data['error']}")

    return read_message_text_result(response_data.get("result"))


def send_text_task_and_wait_for_text_artifact(
    endpoint_url: str,
    text: str,
    request_id: str = "a2a-task-request",
    timeout_seconds: int = 300,
    poll_interval_seconds: float = 1.0,
) -> str:
    """Start an A2A task with text input and return its first text artifact."""
    task = send_text_task(
        endpoint_url,
        text,
        request_id=request_id,
        timeout=min(timeout_seconds, 60),
    )
    task_id = _read_task_id(task)
    deadline = time.monotonic() + timeout_seconds

    while True:
        state = _read_task_state(task)
        if state in _TERMINAL_TASK_STATES:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(f"A2A task {task_id} did not complete before timeout.")

        time.sleep(poll_interval_seconds)
        task = get_task(
            endpoint_url,
            task_id,
            request_id=f"{request_id}-get",
            timeout=min(timeout_seconds, 60),
        )

    state = _read_task_state(task)
    if state != "TASK_STATE_COMPLETED":
        message = _read_task_status_message(task)
        detail = f": {message}" if message else ""
        raise RuntimeError(f"A2A task {task_id} finished with state {state}{detail}.")

    return read_task_text_artifact(task)


def send_text_tasks_and_wait_for_text_artifacts(
    requests: Sequence[TextTaskRequest],
    timeout_seconds: int = 300,
    poll_interval_seconds: float = 1.0,
) -> tuple[TextTaskArtifactResult, ...]:
    """Start multiple A2A text tasks, poll them together, and return artifacts."""
    if not requests:
        return ()

    pending_tasks = {}
    for request in requests:
        task = send_text_task(
            request.endpoint_url,
            request.text,
            request_id=request.request_id,
            timeout=min(timeout_seconds, 60),
        )
        task_id = _read_task_id(task)
        pending_tasks[request.name] = (request, task_id, task)

    deadline = time.monotonic() + timeout_seconds
    completed_tasks: dict[str, tuple[str, dict[str, object]]] = {}
    while pending_tasks:
        for name, (_request, task_id, task) in tuple(pending_tasks.items()):
            state = _read_task_state(task)
            if state not in _TERMINAL_TASK_STATES:
                continue
            if state != "TASK_STATE_COMPLETED":
                message = _read_task_status_message(task)
                detail = f": {message}" if message else ""
                raise RuntimeError(
                    f"A2A task {task_id} for {name} finished with state "
                    f"{state}{detail}."
                )

            completed_tasks[name] = (task_id, task)
            del pending_tasks[name]

        if not pending_tasks:
            break
        if time.monotonic() >= deadline:
            names = ", ".join(sorted(pending_tasks))
            raise RuntimeError(f"A2A tasks did not complete before timeout: {names}.")

        time.sleep(poll_interval_seconds)
        for name, (request, task_id, _task) in tuple(pending_tasks.items()):
            task = get_task(
                request.endpoint_url,
                task_id,
                request_id=f"{request.request_id}-get",
                timeout=min(timeout_seconds, 60),
            )
            pending_tasks[name] = (request, task_id, task)

    results = []
    for request in requests:
        task_id, task = completed_tasks[request.name]
        results.append(
            TextTaskArtifactResult(
                name=request.name,
                task_id=task_id,
                text=read_task_text_artifact(task),
            )
        )

    return tuple(results)


def send_text_task(
    endpoint_url: str,
    text: str,
    request_id: str = "a2a-task-request",
    timeout: int = 60,
) -> dict[str, object]:
    """Send a JSON-RPC message/send request and return the resulting Task."""
    request_body = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "kind": "text",
                        "text": text,
                    }
                ],
            },
            "configuration": {
                "blocking": False,
            },
        },
    }
    response_data = _post_json_rpc(endpoint_url, request_body, timeout)
    return read_task_result(response_data.get("result"))


def get_task(
    endpoint_url: str,
    task_id: str,
    request_id: str = "a2a-task-get-request",
    timeout: int = 10,
) -> dict[str, object]:
    """Call JSON-RPC tasks/get and return the resulting Task."""
    request_body = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tasks/get",
        "params": {
            "id": task_id,
            "historyLength": 0,
        },
    }
    response_data = _post_json_rpc(endpoint_url, request_body, timeout)
    return read_task_result(response_data.get("result"))


def read_message_text_result(result: object) -> str:
    """Read the first text part from a JSON-RPC message result."""
    if not isinstance(result, dict):
        raise RuntimeError("A2A result must be an object.")

    parts = result.get("parts")
    if not isinstance(parts, list):
        raise RuntimeError("A2A result did not contain parts.")

    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            return str(part["text"])

    raise RuntimeError("A2A result did not contain text.")


def read_task_result(result: object) -> dict[str, object]:
    """Validate and return a JSON-RPC Task result."""
    if not isinstance(result, dict):
        raise RuntimeError("A2A task result must be an object.")
    if result.get("kind") != "task":
        raise RuntimeError("A2A task result must have kind 'task'.")

    _read_task_id(result)
    _read_task_state(result)
    return result


def read_task_text_artifact(task: dict[str, object]) -> str:
    """Read the first text part from an A2A Task artifact."""
    artifacts = task.get("artifacts")
    if not isinstance(artifacts, list):
        raise RuntimeError("A2A task did not contain artifacts.")

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        parts = artifact.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                return str(part["text"])

    raise RuntimeError("A2A task artifacts did not contain text.")


def _post_json_rpc(
    endpoint_url: str,
    request_body: dict[str, object],
    timeout: int,
) -> dict[str, object]:
    request = urllib.request.Request(
        endpoint_url,
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _urlopen_no_proxy(request, timeout=timeout) as response:
        response_data = json.loads(response.read().decode("utf-8"))
    if not isinstance(response_data, dict):
        raise RuntimeError("A2A response must be a JSON object.")
    if "error" in response_data:
        raise RuntimeError(f"A2A error: {response_data['error']}")

    return response_data


def _read_task_id(task: dict[str, object]) -> str:
    task_id = task.get("id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise RuntimeError("A2A task result did not contain an id.")

    return task_id


def _read_task_state(task: dict[str, object]) -> str:
    status = task.get("status")
    if not isinstance(status, dict):
        raise RuntimeError("A2A task result did not contain status.")

    state = status.get("state")
    if not isinstance(state, str) or not state.strip():
        raise RuntimeError("A2A task result did not contain status state.")

    return state


def _read_task_status_message(task: dict[str, object]) -> str:
    status = task.get("status")
    if not isinstance(status, dict):
        return ""

    message = status.get("message")
    if not isinstance(message, dict):
        return ""

    parts = message.get("parts")
    if not isinstance(parts, list):
        return ""

    text_parts = [
        text
        for part in parts
        if isinstance(part, dict) and isinstance((text := part.get("text")), str)
    ]
    return "\n\n".join(text_parts).strip()


def _urlopen_no_proxy(
    url: str | urllib.request.Request,
    timeout: int,
) -> Any:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(url, timeout=timeout)
