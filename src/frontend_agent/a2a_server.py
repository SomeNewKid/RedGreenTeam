"""Small A2A-compatible HTTP task server for the Frontend Agent."""

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

from .openai_agent import run_frontend_agent

_AGENT_NAME = "Frontend Agent"
_DEFAULT_BUG_REPORT = (
    "The submit button overlaps the error banner on mobile Safari, and clicking "
    "it does not show any visible loading state."
)
_OUTPUT_DIRECTORY = Path("/sandbox-output")
_ASSESSMENT_FILE_NAME = "assessment.json"
_TASKS: dict[str, dict[str, object]] = {}
_TASK_LOCK = threading.Lock()


def serve_frontend_agent(host: str, port: int, public_base_url: str) -> None:
    """Serve the Frontend Agent over a small JSON-RPC HTTP surface."""
    handler = _build_handler(public_base_url.rstrip("/"))
    server = ThreadingHTTPServer((host, port), handler)
    server.serve_forever()


def _build_handler(public_base_url: str) -> type[BaseHTTPRequestHandler]:
    class _FrontendAgentHandler(BaseHTTPRequestHandler):
        server_version = "FrontendAgentA2A/1.0"

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

    return _FrontendAgentHandler


def _build_agent_card(public_base_url: str) -> dict[str, object]:
    return build_agent_card(
        name=_AGENT_NAME,
        description="Assesses whether a bug report indicates a web frontend issue.",
        public_base_url=public_base_url,
        skills=[
            {
                "id": "assess_frontend_bug",
                "name": "Assess Frontend Bug",
                "description": (
                    "Return a frontend likelihood percentage and concise reasons."
                ),
            }
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
    bug_report = read_message_text(request.get("params"))
    task_id = f"frontend-task-{uuid.uuid4()}"
    context_id = f"frontend-context-{uuid.uuid4()}"
    task = build_task(
        task_id,
        context_id,
        "TASK_STATE_SUBMITTED",
        message_text="Frontend assessment task submitted.",
    )
    _set_task(task_id, task)

    thread = threading.Thread(
        target=_run_frontend_task,
        args=(task_id, context_id, bug_report or _DEFAULT_BUG_REPORT),
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


def _run_frontend_task(task_id: str, context_id: str, bug_report: str) -> None:
    _set_task(
        task_id,
        build_task(
            task_id,
            context_id,
            "TASK_STATE_WORKING",
            message_text="Frontend assessment task is running.",
        ),
    )
    try:
        assessment = run_frontend_agent(bug_report)
        _save_assessment(assessment)
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
        "frontend-assessment",
        "Frontend bug assessment",
        json.dumps(assessment, sort_keys=True),
        mime_type="application/json",
    )
    _set_task(
        task_id,
        build_task(
            task_id,
            context_id,
            "TASK_STATE_COMPLETED",
            message_text="Frontend assessment task completed.",
            artifacts=(artifact,),
        ),
    )


def _save_assessment(assessment: dict[str, object]) -> None:
    _OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    assessment_path = _OUTPUT_DIRECTORY / _ASSESSMENT_FILE_NAME
    assessment_json = json.dumps(assessment, indent=2, sort_keys=True)
    assessment_path.write_text(f"{assessment_json}\n", encoding="utf-8")


def _set_task(task_id: str, task: dict[str, object]) -> None:
    with _TASK_LOCK:
        _TASKS[task_id] = task


def _get_task(task_id: str) -> dict[str, object] | None:
    with _TASK_LOCK:
        task = _TASKS.get(task_id)
        if task is None:
            return None

        return json.loads(json.dumps(task))
