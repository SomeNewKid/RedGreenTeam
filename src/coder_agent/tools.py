"""Tools used by the Coder Agent."""

from __future__ import annotations

import json
import os
from pathlib import Path

_SHARED_DIRECTORY_ENVIRONMENT_VARIABLE = "SANDBOX_SHARED_DIR"
_DEFAULT_SHARED_DIRECTORY = Path("/sandbox-shared")
_SOLUTION_FILE_NAME = "solution.py"
_TESTS_FILE_NAME = "tests.py"
_TEST_RESULTS_FILE_NAME = "test-results.json"
_DEFAULT_REQUIREMENT = (
    "Implement slugify_title(title: str) -> str so that article titles become "
    "ASCII lowercase URL slugs separated by hyphens. For example, "
    '"Beyoncé’s Music Won’t Age" should become "beyonces-music-wont-age".'
)


def create_solution_stub(
    requirement: str = _DEFAULT_REQUIREMENT,
) -> dict[str, object]:
    """Create the initial not-implemented solution.py stub using the coder LLM."""
    from .openai_agent import generate_solution_text

    normalized_requirement = requirement.strip() or _DEFAULT_REQUIREMENT
    prompt = _build_stub_prompt(normalized_requirement)
    solution_text = generate_solution_text(prompt)
    save_result = save_solution(solution_text)
    if not save_result["success"]:
        return {
            "agent": "coder_agent",
            "status": "error",
            "updated": False,
            "message": save_result["message"],
            "solution_file": _SOLUTION_FILE_NAME,
        }

    return {
        "agent": "coder_agent",
        "status": "stub_created",
        "updated": True,
        "solution_file": _SOLUTION_FILE_NAME,
        "requirement": normalized_requirement,
        "message": "Created solution.py stub.",
    }


def update_solution(requirement: str = _DEFAULT_REQUIREMENT) -> dict[str, object]:
    """Update solution.py using the coder LLM and current shared test context."""
    from .openai_agent import generate_solution_text

    normalized_requirement = requirement.strip() or _DEFAULT_REQUIREMENT
    context = read_coding_context()
    solution_text = generate_solution_text(
        _build_update_prompt(normalized_requirement, context)
    )
    save_result = save_solution(solution_text)
    if not save_result["success"]:
        return {
            "agent": "coder_agent",
            "status": "error",
            "updated": False,
            "message": save_result["message"],
            "solution_file": _SOLUTION_FILE_NAME,
        }

    return {
        "agent": "coder_agent",
        "status": "updated",
        "updated": True,
        "solution_file": _SOLUTION_FILE_NAME,
        "requirement": normalized_requirement,
        "previous_solution_present": bool(context["solution"]),
        "tests_present": bool(context["tests"]),
        "test_results_present": bool(context["test_results"]),
        "message": "Updated solution.py to address the current tests.",
    }


def read_coding_context() -> dict[str, object]:
    """Read the shared artifacts the coder uses to update solution.py."""
    return {
        "solution": _read_optional_shared_file(_SOLUTION_FILE_NAME),
        "tests": _read_optional_shared_file(_TESTS_FILE_NAME),
        "test_results": _read_optional_json_file(_TEST_RESULTS_FILE_NAME),
    }


def read_solution() -> str:
    """Read the shared solution.py file."""
    return read_shared_file(_SOLUTION_FILE_NAME)


def save_solution(file_contents: str) -> dict[str, bool | str]:
    """Save the only implementation file the Coder Agent is allowed to edit."""
    return save_shared_file(_SOLUTION_FILE_NAME, file_contents)


def save_shared_file(file_name: str, file_contents: str) -> dict[str, bool | str]:
    """Save solution.py while rejecting all other shared-file write targets."""
    if file_name != _SOLUTION_FILE_NAME:
        return _failure("save", file_name)

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


def read_shared_file(file_name: str) -> str:
    """Read a UTF-8 text file from the sandbox shared directory."""
    file_path = _resolve_shared_path(file_name)
    return file_path.read_text(encoding="utf-8")


def _read_optional_shared_file(file_name: str) -> str:
    try:
        return read_shared_file(file_name)
    except OSError:
        return ""


def _read_optional_json_file(file_name: str) -> dict[str, object]:
    text = _read_optional_shared_file(file_name)
    if not text:
        return {}

    data = json.loads(text)
    if not isinstance(data, dict):
        return {}

    return data


def _build_stub_prompt(requirement: str) -> str:
    return (
        "Create the initial solution.py file for this requirement.\n\n"
        f"Requirement:\n{requirement}\n\n"
        "Return only Python code for solution.py.\n"
        "Requirements for solution.py:\n"
        "- Include a short module docstring that repeats the requirement.\n"
        "- Define exactly one public function named slugify_title(title: str) -> str.\n"
        "- The function body must raise NotImplementedError.\n"
        "- Do not include tests.\n"
    )


def _build_update_prompt(
    requirement: str,
    context: dict[str, object],
) -> str:
    solution_text = str(context.get("solution", "")).strip() or "# solution.py is empty"
    tests_text = str(context.get("tests", "")).strip() or "# tests.py is missing"
    test_results = json.dumps(context.get("test_results", {}), indent=2, sort_keys=True)
    return (
        "Update solution.py so the implementation satisfies the existing tests.\n\n"
        f"Requirement:\n{requirement}\n\n"
        "Current solution.py:\n"
        "```python\n"
        f"{solution_text}\n"
        "```\n\n"
        "Current tests.py:\n"
        "```python\n"
        f"{tests_text}\n"
        "```\n\n"
        "Latest test-results.json:\n"
        "```json\n"
        f"{test_results}\n"
        "```\n\n"
        "Return only the complete updated solution.py file as Python code.\n"
        "Keep exactly one public function named slugify_title(title: str) -> str.\n"
        "Do not output markdown fences.\n"
    )


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
