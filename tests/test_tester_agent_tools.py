"""Tests for Tester Agent shared-file and execution tools."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from code_sidecar.server import run_python_script as run_code_sidecar_script
from tester_agent.tools import (
    build_test_execution_script,
    create_tests,
    read_shared_file,
    run_solution_tests,
    save_shared_file,
)


def test_generate_tests_text_removes_solution_imports(monkeypatch) -> None:
    """Verify generated tests are adapted to the concatenated execution model."""
    from types import SimpleNamespace

    from tester_agent.openai_agent import generate_tests_text

    class _FakeRunner:
        @staticmethod
        def run_sync(agent, prompt: str, max_turns: int) -> SimpleNamespace:
            _ = agent
            assert "Do not import solution" in prompt
            assert max_turns == 1
            return SimpleNamespace(
                final_output=(
                    "from solution import slugify_title\n\n"
                    "def run_tests() -> dict[str, object]:\n"
                    "    result = solution.slugify_title('Hello World')\n"
                    "    return {'passed': result == 'hello-world', "
                    "'case_count': 1, 'failures': []}\n"
                )
            )

    class _FakeAgent:
        def __init__(self, **kwargs: Any) -> None:
            _ = kwargs

    monkeypatch.setitem(
        sys.modules,
        "agents",
        SimpleNamespace(Agent=_FakeAgent, Runner=_FakeRunner),
    )

    tests_text = generate_tests_text("Implement slugify_title.", "")

    assert "from solution import" not in tests_text
    assert "solution.slugify_title" not in tests_text
    assert "slugify_title('Hello World')" in tests_text


def test_create_tests_writes_generated_tests_file(tmp_path: Path, monkeypatch) -> None:
    """Verify tester_agent can generate and save tests.py once for a requirement."""
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(tmp_path))
    save_shared_file(
        "solution.py",
        "def slugify_title(title: str) -> str:\n    raise NotImplementedError\n",
    )
    monkeypatch.setattr(
        "tester_agent.openai_agent.generate_tests_text",
        lambda requirement, solution_text, model="gpt-4.1-mini": (
            "def run_tests() -> dict[str, object]:\n"
            "    return {'passed': True, 'case_count': 1, 'failures': []}\n"
        ),
    )

    result = create_tests("Implement slugify_title(title: str) -> str.")

    assert result["agent"] == "tester_agent"
    assert result["status"] == "created"
    assert result["created"] is True
    tests_text = read_shared_file("tests.py")
    assert "def run_tests() -> dict[str, object]:" in tests_text
    assert "'case_count': 1" in tests_text


def test_build_test_execution_script_combines_solution_and_tests() -> None:
    """Verify the tester builds one code-sidecar-compatible script payload."""
    solution_text = "def is_even(number: int) -> bool:\n    return number % 2 == 0\n"
    tests_text = "def run_tests() -> dict[str, object]:\n    return {'passed': True}\n"

    script = build_test_execution_script(solution_text, tests_text)

    assert "import json" in script
    assert "# --- solution.py ---" in script
    assert "def is_even(number: int) -> bool:" in script
    assert "# --- tests.py ---" in script
    assert "def run_tests() -> dict[str, object]:" in script
    assert "def main(argv: list[str]) -> int:" in script


def test_run_solution_tests_reports_failure_for_skeleton(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify the default solution skeleton produces a red test result."""
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(tmp_path))
    save_shared_file(
        "solution.py",
        "\n".join(
            [
                "def slugify_title(title: str) -> str:",
                "    raise NotImplementedError('not yet')",
                "",
            ]
        ),
    )
    save_shared_file(
        "tests.py",
        "\n".join(
            [
                "def run_tests() -> dict[str, object]:",
                "    cases = [('Hello World', 'hello-world')]",
                "    failures = []",
                "    for title, expected in cases:",
                "        try:",
                "            actual = slugify_title(title)",
                "        except Exception as error:",
                "            failures.append({'title': title, 'error': str(error)})",
                "            continue",
                "        if actual != expected:",
                "            failures.append(",
                "                {",
                "                    'title': title,",
                "                    'expected': expected,",
                "                    'actual': actual,",
                "                }",
                "            )",
                "    return {",
                "        'passed': not failures,",
                "        'case_count': len(cases),",
                "        'failures': failures,",
                "    }",
                "",
            ]
        ),
    )
    _patch_code_sidecar_execution(monkeypatch, tmp_path)

    result = run_solution_tests()

    assert result["agent"] == "tester_agent"
    assert result["status"] == "failed"
    assert result["passed"] is False
    test_summary = result["test_summary"]
    assert isinstance(test_summary, dict)
    assert test_summary["case_count"] == 1
    assert len(test_summary["failures"]) == 1
    saved_result = json.loads((tmp_path / "test-results.json").read_text())
    assert saved_result["status"] == "failed"
    assert read_shared_file("tests.py").startswith("def run_tests()")


def test_run_solution_tests_reports_success_for_working_solution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify a correct is_even implementation produces a green test result."""
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(tmp_path))
    save_shared_file(
        "solution.py",
        "\n".join(
            [
                "def slugify_title(title: str) -> str:",
                "    return 'hello-world'",
                "",
            ]
        ),
    )
    save_shared_file(
        "tests.py",
        "\n".join(
            [
                "def run_tests() -> dict[str, object]:",
                "    cases = [('Hello World', 'hello-world')]",
                "    failures = []",
                "    for title, expected in cases:",
                "        actual = slugify_title(title)",
                "        if actual != expected:",
                "            failures.append(",
                "                {",
                "                    'title': title,",
                "                    'expected': expected,",
                "                    'actual': actual,",
                "                }",
                "            )",
                "    return {",
                "        'passed': not failures,",
                "        'case_count': len(cases),",
                "        'failures': failures,",
                "    }",
                "",
            ]
        ),
    )
    _patch_code_sidecar_execution(monkeypatch, tmp_path)

    result = run_solution_tests()

    assert result["agent"] == "tester_agent"
    assert result["status"] == "passed"
    assert result["passed"] is True
    test_summary = result["test_summary"]
    assert isinstance(test_summary, dict)
    assert test_summary["case_count"] == 1
    assert test_summary["failures"] == []
    saved_result = json.loads((tmp_path / "test-results.json").read_text())
    assert saved_result["status"] == "passed"


def test_run_solution_tests_records_exception_group_details(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify nested tester execution errors are saved for diagnosis."""
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(tmp_path))
    save_shared_file(
        "solution.py",
        "def slugify_title(title: str) -> str:\n    return 'hello-world'\n",
    )
    save_shared_file(
        "tests.py",
        (
            "def run_tests() -> dict[str, object]:\n"
            "    return {'passed': True, 'case_count': 1, 'failures': []}\n"
        ),
    )

    def fake_run_python_script(
        script: str,
        args: list[str] | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        _ = script
        _ = args
        _ = timeout_seconds
        raise ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [RuntimeError("MCP sidecar connection failed")],
        )

    monkeypatch.setattr("tester_agent.tools.run_python_script", fake_run_python_script)

    result = run_solution_tests()

    assert result["status"] == "error"
    assert result["passed"] is False
    assert result["error_type"] == "ExceptionGroup"
    error = result["error"]
    assert isinstance(error, dict)
    children = error["children"]
    assert isinstance(children, list)
    assert children[0]["type"] == "RuntimeError"
    assert children[0]["message"] == "MCP sidecar connection failed"
    saved_result = json.loads((tmp_path / "test-results.json").read_text())
    assert saved_result["error"]["children"][0]["message"] == (
        "MCP sidecar connection failed"
    )


def _patch_code_sidecar_execution(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CODE_SIDECAR_OUTPUT_DIRECTORY", str(tmp_path / "code-sidecar"))
    monkeypatch.setattr("code_sidecar.server._clean_tmp_directory", lambda: None)

    def fake_run_python_script(
        script: str,
        args: list[str] | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        result = run_code_sidecar_script(
            script,
            args=args,
            timeout_seconds=timeout_seconds,
        )
        return json.dumps(asdict(result), sort_keys=True)

    monkeypatch.setattr("tester_agent.tools.run_python_script", fake_run_python_script)
