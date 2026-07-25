"""Tests for Coder Agent shared solution tools."""

from __future__ import annotations

import json
from pathlib import Path

from coder_agent.tools import (
    create_solution_stub,
    read_coding_context,
    read_solution,
    save_shared_file,
    save_solution,
    update_solution,
)


def test_create_solution_stub_writes_only_solution_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify coder_agent can create the initial solution.py stub."""
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(tmp_path))
    monkeypatch.setattr(
        "coder_agent.openai_agent.generate_solution_text",
        lambda prompt, model="gpt-4.1-mini": (
            '"""Solution."""\n\n'
            "def slugify_title(title: str) -> str:\n"
            "    raise NotImplementedError('not yet')\n"
        ),
    )

    result = create_solution_stub("Implement slugify_title(title: str) -> str.")

    assert result["agent"] == "coder_agent"
    assert result["status"] == "stub_created"
    assert result["updated"] is True
    solution_text = read_solution()
    assert "def slugify_title(title: str) -> str:" in solution_text
    assert "raise NotImplementedError" in solution_text


def test_update_solution_writes_only_solution_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify coder_agent writes a working solution.py implementation."""
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(tmp_path))
    (tmp_path / "solution.py").write_text(
        (
            "def slugify_title(title: str) -> str:\n"
            "    raise NotImplementedError('not yet')\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "tests.py").write_text(
        (
            "def run_tests() -> dict[str, object]:\n"
            "    return {\n"
            "        'passed': False,\n"
            "        'case_count': 1,\n"
            "        'failures': [{'title': 'Hello World'}],\n"
            "    }\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "test-results.json").write_text(
        json.dumps(
            {
                "passed": False,
                "test_summary": {
                    "failures": [{"title": "Hello World"}],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "coder_agent.openai_agent.generate_solution_text",
        lambda prompt, model="gpt-4.1-mini": (
            '"""Solution."""\n\n'
            "def slugify_title(title: str) -> str:\n"
            "    return 'hello-world'\n"
        ),
    )

    result = update_solution("Implement slugify_title(title: str) -> str.")

    assert result["agent"] == "coder_agent"
    assert result["status"] == "updated"
    assert result["updated"] is True
    assert result["solution_file"] == "solution.py"
    assert result["previous_solution_present"] is True
    assert result["tests_present"] is True
    assert result["test_results_present"] is True
    solution_text = read_solution()
    assert "def slugify_title(title: str) -> str:" in solution_text
    assert "return 'hello-world'" in solution_text


def test_save_solution_round_trips_solution_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify coder_agent can save and read solution.py."""
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(tmp_path))

    result = save_solution("def slugify_title(title: str) -> str:\n    return 'ok'\n")

    assert result == {
        "success": True,
        "message": "Created solution.py",
    }
    assert read_solution() == "def slugify_title(title: str) -> str:\n    return 'ok'\n"


def test_save_shared_file_rejects_non_solution_targets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify coder_agent cannot write tests or metadata artifacts."""
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(tmp_path))

    tests_result = save_shared_file("tests.py", "assert False\n")
    state_result = save_shared_file("red-green-state.json", "{}\n")

    assert tests_result == {
        "success": False,
        "message": "Failed to save `tests.py",
    }
    assert state_result == {
        "success": False,
        "message": "Failed to save `red-green-state.json",
    }
    assert not (tmp_path / "tests.py").exists()
    assert not (tmp_path / "red-green-state.json").exists()


def test_save_shared_file_rejects_parent_escape(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify coder_agent cannot escape the shared directory while saving."""
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(tmp_path / "shared"))

    result = save_shared_file("../solution.py", "bad = True\n")

    assert result == {
        "success": False,
        "message": "Failed to save `../solution.py",
    }
    assert not (tmp_path / "solution.py").exists()


def test_read_coding_context_tolerates_missing_optional_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Verify missing tests and test results do not block context loading."""
    monkeypatch.setenv("SANDBOX_SHARED_DIR", str(tmp_path))
    (tmp_path / "solution.py").write_text("# stub\n", encoding="utf-8")

    context = read_coding_context()

    assert context == {
        "solution": "# stub\n",
        "tests": "",
        "test_results": {},
    }
