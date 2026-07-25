"""Tools used by the Tester Agent."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_SHARED_DIRECTORY_ENVIRONMENT_VARIABLE = "SANDBOX_SHARED_DIR"
_DEFAULT_SHARED_DIRECTORY = Path("/sandbox-shared")
_MCP_SIDECAR_URL_ENVIRONMENT_VARIABLE = "MCP_SIDECAR_URL"
_MCP_RUN_PYTHON_SCRIPT_TOOL_NAME = "run_python_script"
_SOLUTION_FILE_NAME = "solution.py"
_TESTS_FILE_NAME = "tests.py"
_TEST_RESULTS_FILE_NAME = "test-results.json"
_DEFAULT_TIMEOUT_SECONDS = 10


def run_solution_tests() -> dict[str, object]:
    """Execute the existing tests.py file against solution.py and save results."""
    try:
        solution_text = read_shared_file(_SOLUTION_FILE_NAME)
        tests_text = read_shared_file(_TESTS_FILE_NAME)
        script = build_test_execution_script(solution_text, tests_text)
        execution_text = run_python_script(
            script,
            timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
        )
        execution = _read_execution_result(execution_text)
        test_summary = _read_test_summary(execution)
    except Exception as error:
        result = _build_error_result(error)
        _save_test_results(result)
        return result

    passed = bool(test_summary.get("passed")) and execution.get("exit_code") == 0
    result = {
        "agent": "tester_agent",
        "status": "passed" if passed else "failed",
        "passed": passed,
        "solution_file": _SOLUTION_FILE_NAME,
        "tests_file": _TESTS_FILE_NAME,
        "test_summary": test_summary,
        "execution": execution,
    }
    _save_test_results(result)
    return result


def create_tests(requirement: str) -> dict[str, object]:
    """Use the tester LLM to create tests.py for the current requirement."""
    from .openai_agent import generate_tests_text

    normalized_requirement = requirement.strip()
    if not normalized_requirement:
        raise ValueError("requirement must not be empty.")

    solution_text = _read_optional_shared_file(_SOLUTION_FILE_NAME)
    tests_text = generate_tests_text(normalized_requirement, solution_text)
    save_result = save_shared_file(_TESTS_FILE_NAME, tests_text)
    if not save_result["success"]:
        return {
            "agent": "tester_agent",
            "status": "error",
            "created": False,
            "message": save_result["message"],
            "tests_file": _TESTS_FILE_NAME,
        }

    return {
        "agent": "tester_agent",
        "status": "created",
        "created": True,
        "tests_file": _TESTS_FILE_NAME,
        "requirement": normalized_requirement,
        "solution_present": bool(solution_text),
        "message": "Created tests.py for the current requirement.",
    }


def build_test_execution_script(solution_text: str, tests_text: str) -> str:
    """Build the single script payload submitted to the code-execution sidecar."""
    return "\n\n".join(
        (
            '"""Generated tester_agent execution wrapper."""',
            "import json",
            "# --- solution.py ---",
            solution_text.rstrip(),
            "# --- tests.py ---",
            tests_text.rstrip(),
            _WRAPPER_MAIN,
            "",
        )
    )


def read_shared_file(file_name: str) -> str:
    """Read a UTF-8 text file from the sandbox shared directory."""
    file_path = _resolve_shared_path(file_name)
    return file_path.read_text(encoding="utf-8")


def _read_optional_shared_file(file_name: str) -> str:
    try:
        return read_shared_file(file_name)
    except OSError:
        return ""


def save_shared_file(file_name: str, file_contents: str) -> dict[str, bool | str]:
    """Save a UTF-8 text file inside the sandbox shared directory."""
    try:
        file_path = _resolve_shared_path(file_name)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(file_contents, encoding="utf-8")
    except OSError:
        return _failure("save", file_name)

    if not file_path.exists():
        return _failure("save", file_name)

    return {
        "success": True,
        "message": f"Created {file_name}",
    }


def run_python_script(
    script: str,
    args: list[str] | None = None,
    timeout_seconds: int | None = None,
) -> str:
    """Run a small Python script through the MCP code-execution sidecar tool."""
    arguments: dict[str, object] = {"script": script}
    if args is not None:
        arguments["args"] = args
    if timeout_seconds is not None:
        arguments["timeout_seconds"] = timeout_seconds

    return _call_mcp_sidecar_tool(_MCP_RUN_PYTHON_SCRIPT_TOOL_NAME, arguments)


_WRAPPER_MAIN = '''def main(argv: list[str]) -> int:
    """Run generated tests and emit a JSON result."""
    _ = argv
    result = run_tests()
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("passed") else 1
'''


def _save_test_results(result: dict[str, object]) -> None:
    result_path = _resolve_shared_path(_TEST_RESULTS_FILE_NAME)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_json = json.dumps(result, indent=2, sort_keys=True)
    result_path.write_text(f"{result_json}\n", encoding="utf-8")


def _build_error_result(error: BaseException | str) -> dict[str, object]:
    details = _format_error_details(error)
    return {
        "agent": "tester_agent",
        "status": "error",
        "passed": False,
        "message": str(details["message"]),
        "error_type": details["type"],
        "error": details,
        "solution_file": _SOLUTION_FILE_NAME,
        "tests_file": _TESTS_FILE_NAME,
    }


def _format_error_details(error: BaseException | str) -> dict[str, object]:
    if isinstance(error, str):
        return {
            "type": "Error",
            "message": error,
            "children": [],
        }

    children = []
    if isinstance(error, BaseExceptionGroup):
        children = [_format_error_details(child) for child in error.exceptions]

    return {
        "type": type(error).__name__,
        "message": str(error),
        "children": children,
    }


def _read_execution_result(execution_text: str) -> dict[str, object]:
    data = json.loads(execution_text)
    if not isinstance(data, dict):
        raise ValueError("Code execution result must be a JSON object.")

    return data


def _read_test_summary(execution: dict[str, object]) -> dict[str, object]:
    stdout = execution.get("stdout")
    if not isinstance(stdout, str) or not stdout.strip():
        return {
            "passed": False,
            "case_count": 0,
            "failures": [
                {
                    "error": "Code execution did not produce test summary JSON.",
                }
            ],
        }

    data = json.loads(stdout)
    if not isinstance(data, dict):
        raise ValueError("Test summary must be a JSON object.")

    return data


def _call_mcp_sidecar_tool(tool_name: str, arguments: Mapping[str, object]) -> str:
    sidecar_url = _get_mcp_sidecar_url()
    return _call_mcp_tool(sidecar_url, tool_name, arguments)


def _get_mcp_sidecar_url() -> str:
    sidecar_url = os.environ.get(_MCP_SIDECAR_URL_ENVIRONMENT_VARIABLE)
    if not sidecar_url:
        raise RuntimeError("MCP_SIDECAR_URL is not configured.")

    return sidecar_url


def _call_mcp_tool(
    sidecar_url: str,
    tool_name: str,
    arguments: Mapping[str, object],
) -> str:
    import anyio

    return anyio.run(_call_mcp_tool_async, sidecar_url, tool_name, arguments)


async def _call_mcp_tool_async(
    sidecar_url: str,
    tool_name: str,
    arguments: Mapping[str, object],
) -> str:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(sidecar_url) as (
        read_stream,
        write_stream,
        _get_session_id,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, dict(arguments))

    return _read_mcp_tool_text_result(result)


def _read_mcp_tool_text_result(result: Any) -> str:
    structured_content = getattr(result, "structuredContent", None)
    if isinstance(structured_content, dict):
        value = structured_content.get("result")
        if isinstance(value, str):
            return value
        if value is not None:
            return json.dumps(value, indent=2)
        return json.dumps(structured_content, indent=2)

    content_blocks = getattr(result, "content", ())
    for block in content_blocks:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            return text

    raise RuntimeError("MCP tool did not return a text result.")


def _resolve_shared_path(file_name: str) -> Path:
    shared_directory = Path(
        os.environ.get(
            _SHARED_DIRECTORY_ENVIRONMENT_VARIABLE,
            str(_DEFAULT_SHARED_DIRECTORY),
        )
    )
    return _resolve_child_path(shared_directory, file_name)


def _resolve_child_path(parent: Path, child_name: str) -> Path:
    child_path = parent / child_name
    resolved_parent = parent.resolve(strict=False)
    resolved_child = child_path.resolve(strict=False)
    if not _is_relative_to(resolved_child, resolved_parent):
        raise OSError(f"Refusing to write outside {resolved_parent}: {child_name}")

    return resolved_child


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False

    return True


def _failure(action: str, file_name: str) -> dict[str, bool | str]:
    return {
        "success": False,
        "message": f"Failed to {action} `{file_name}",
    }
