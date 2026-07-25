"""Small A2A-compatible HTTP task server for the Coder Agent."""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from a2a_support.server import (
    build_agent_card,
    build_task,
    build_text_artifact,
    json_rpc_error,
    json_rpc_result,
    read_json_request,
    read_message_text,
    read_task_id,
    write_json_response,
)

from .tools import create_solution_stub, update_solution

_AGENT_NAME = "Coder Agent"
_OUTPUT_DIRECTORY = Path("/sandbox-output")
_RESULT_FILE_NAME = "coder-result.json"
_TASKS: dict[str, dict[str, object]] = {}
_TASK_LOCK = threading.Lock()


def serve_coder_agent(host: str, port: int, public_base_url: str) -> None:
    """Serve the Coder Agent over a small JSON-RPC HTTP surface."""
    handler = _build_handler(public_base_url.rstrip("/"))
    server = ThreadingHTTPServer((host, port), handler)
    server.serve_forever()


def _build_handler(public_base_url: str) -> type[BaseHTTPRequestHandler]:
    class _CoderAgentHandler(BaseHTTPRequestHandler):
        server_version = "CoderAgentA2A/1.0"

        def do_GET(self) -> None:
            """Handle health and Agent Card requests."""
            if self.path == "/health":
                write_json_response(self, {"status": "ok"})
                return
            if self.path == "/.well-known/agent.json":
                write_json_response(self, _build_agent_card(public_base_url))
                return

            self.send_error(404, "Not found")

        def do_POST(self) -> None:
            """Handle JSON-RPC A2A requests."""
            if self.path != "/a2a":
                self.send_error(404, "Not found")
                return

            try:
                request = read_json_request(self)
                response = _handle_json_rpc_request(request)
            except Exception as error:
                response = json_rpc_error(None, -32000, str(error))

            write_json_response(self, response)

        def log_message(self, format: str, *args: object) -> None:
            """Keep supporting-agent logs focused on explicit application output."""
            _ = format
            _ = args

    return _CoderAgentHandler


def _build_agent_card(public_base_url: str) -> dict[str, object]:
    return build_agent_card(
        name=_AGENT_NAME,
        description="Writes Python code into the shared solution.py file.",
        public_base_url=public_base_url,
        skills=[
            {
                "id": "create_solution_stub",
                "name": "Create Solution Stub",
                "description": "Create the initial solution.py stub.",
            },
            {
                "id": "update_solution",
                "name": "Update Solution",
                "description": "Update only the shared solution.py implementation.",
            },
        ],
    )


def _handle_json_rpc_request(request: dict[str, object]) -> dict[str, object]:
    request_id = request.get("id")
    method = request.get("method")
    if method == "message/send":
        return _handle_message_send(request)
    if method == "tasks/get":
        return _handle_tasks_get(request)

    return json_rpc_error(request_id, -32601, "Unsupported method.")


def _handle_message_send(request: dict[str, object]) -> dict[str, object]:
    request_id = request.get("id")
    message = read_message_text(request.get("params"))
    task_id = f"coder-task-{uuid.uuid4()}"
    context_id = f"coder-context-{uuid.uuid4()}"
    task = build_task(
        task_id,
        context_id,
        "TASK_STATE_SUBMITTED",
        message_text="Coder task submitted.",
    )
    _set_task(task_id, task)

    thread = threading.Thread(
        target=_run_coder_task,
        args=(task_id, context_id, message),
        daemon=True,
    )
    thread.start()
    return json_rpc_result(request_id, task)


def _handle_tasks_get(request: dict[str, object]) -> dict[str, object]:
    request_id = request.get("id")
    task_id = read_task_id(request.get("params"))
    task = _get_task(task_id)
    if task is None:
        return json_rpc_error(request_id, -32001, f"Unknown task id: {task_id}")

    return json_rpc_result(request_id, task)


def _run_coder_task(task_id: str, context_id: str, message: str) -> None:
    _set_task(
        task_id,
        build_task(
            task_id,
            context_id,
            "TASK_STATE_WORKING",
            message_text="Coder task is running.",
        ),
    )
    try:
        request = _read_coder_request(message)
        if request["action"] == "create_stub":
            result = create_solution_stub(request["requirement"])
        else:
            result = update_solution(request["requirement"])
        _save_result(result)
    except Exception as error:
        _set_task(
            task_id,
            build_task(
                task_id,
                context_id,
                "TASK_STATE_FAILED",
                message_text=str(error),
            ),
        )
        return

    artifact = build_text_artifact(
        "coder-result",
        "Coder update result",
        json.dumps(result, sort_keys=True),
        mime_type="application/json",
    )
    _set_task(
        task_id,
        build_task(
            task_id,
            context_id,
            "TASK_STATE_COMPLETED",
            message_text="Coder task completed.",
            artifacts=(artifact,),
        ),
    )


def _read_coder_request(message: str) -> dict[str, str]:
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return {
            "action": "update_solution",
            "requirement": message,
        }

    if not isinstance(data, dict):
        raise ValueError("Coder request must be a JSON object.")

    action = data.get("action", "update_solution")
    requirement = data.get("requirement", "")
    if not isinstance(action, str):
        raise ValueError("Coder request action must be text.")
    if not isinstance(requirement, str) or not requirement.strip():
        raise ValueError("Coder request requirement must be non-empty text.")

    normalized_action = action.strip()
    if normalized_action not in {"create_stub", "update_solution"}:
        raise ValueError(f"Unsupported coder action: {normalized_action}")

    return {
        "action": normalized_action,
        "requirement": requirement,
    }


def _save_result(result: dict[str, object]) -> None:
    _OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    result_path = _OUTPUT_DIRECTORY / _RESULT_FILE_NAME
    result_json = json.dumps(result, indent=2, sort_keys=True)
    result_path.write_text(f"{result_json}\n", encoding="utf-8")


def _set_task(task_id: str, task: dict[str, object]) -> None:
    with _TASK_LOCK:
        _TASKS[task_id] = task


def _get_task(task_id: str) -> dict[str, object] | None:
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if task is None:
            return None

        return json.loads(json.dumps(task))
