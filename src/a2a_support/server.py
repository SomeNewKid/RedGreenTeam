"""Server helpers for small A2A HTTP integrations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler


def build_agent_card(
    name: str,
    description: str,
    public_base_url: str,
    skills: list[dict[str, object]],
    version: str = "1.0.0",
) -> dict[str, object]:
    """Build a small A2A Agent Card."""
    return {
        "name": name,
        "description": description,
        "url": f"{public_base_url.rstrip('/')}/a2a",
        "version": version,
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
        },
        "skills": skills,
    }


def read_json_request(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    """Read a JSON object request body from an HTTP handler."""
    content_length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(content_length)
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("A2A request must be a JSON object.")

    return data


def write_json_response(
    handler: BaseHTTPRequestHandler,
    data: dict[str, object],
) -> None:
    """Write a JSON object response through an HTTP handler."""
    body = json.dumps(data, sort_keys=True).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_message_text(params: object) -> str:
    """Read joined text parts from JSON-RPC message/send params."""
    if not isinstance(params, dict):
        return ""

    message = params.get("message")
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


def read_task_id(params: object) -> str:
    """Read a task id from JSON-RPC tasks/get params."""
    if not isinstance(params, dict):
        raise ValueError("A2A tasks/get params must be an object.")

    task_id = params.get("id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("A2A tasks/get params must include a non-empty id.")

    return task_id.strip()


def build_task(
    task_id: str,
    context_id: str,
    state: str,
    message_text: str | None = None,
    artifacts: tuple[dict[str, object], ...] = (),
) -> dict[str, object]:
    """Build a small A2A Task object."""
    status: dict[str, object] = {
        "state": state,
        "timestamp": _utc_timestamp(),
    }
    if message_text is not None:
        status["message"] = {
            "kind": "message",
            "messageId": f"{task_id}-status",
            "role": "agent",
            "parts": [
                {
                    "kind": "text",
                    "text": message_text,
                }
            ],
        }

    task: dict[str, object] = {
        "kind": "task",
        "id": task_id,
        "contextId": context_id,
        "status": status,
    }
    if artifacts:
        task["artifacts"] = list(artifacts)

    return task


def build_text_artifact(
    artifact_id: str,
    name: str,
    text: str,
    mime_type: str = "text/plain",
) -> dict[str, object]:
    """Build a small A2A text artifact."""
    return {
        "artifactId": artifact_id,
        "name": name,
        "parts": [
            {
                "kind": "text",
                "text": text,
                "metadata": {
                    "mimeType": mime_type,
                },
            }
        ],
    }


def json_rpc_result(
    request_id: object,
    result: dict[str, object],
) -> dict[str, object]:
    """Build a JSON-RPC success response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def json_rpc_text_result(
    request_id: object,
    text: str,
    mime_type: str = "text/plain",
) -> dict[str, object]:
    """Build a JSON-RPC response containing one A2A text part."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "role": "agent",
            "parts": [
                {
                    "kind": "text",
                    "text": text,
                    "metadata": {
                        "mimeType": mime_type,
                    },
                }
            ],
        },
    }


def json_rpc_error(
    request_id: object,
    code: int,
    message: str,
) -> dict[str, object]:
    """Build a JSON-RPC error response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
