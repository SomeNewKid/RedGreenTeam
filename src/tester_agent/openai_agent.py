"""OpenAI-backed test generator for the Tester Agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents import Agent

_DEFAULT_MODEL = "gpt-4.1-mini"


def create_openai_agent(model: str = _DEFAULT_MODEL) -> Agent:
    """Create the Tester Agent used to generate realistic unit tests."""
    from agents import Agent

    return Agent(
        name="RedGreenTeam Tester Agent",
        model=model,
        instructions=(
            "You write Python unit-test files for a single shared solution.py file. "
            "Return only the complete contents of tests.py with no markdown fences. "
            "The file must define run_tests() -> dict[str, object]. "
            "run_tests must execute deterministic assertions and return a JSON-safe "
            "summary with passed, case_count, and failures fields. "
            "Each failure entry should clearly identify the case that failed."
        ),
    )


def generate_tests_text(
    requirement: str,
    solution_text: str,
    model: str = _DEFAULT_MODEL,
) -> str:
    """Generate the complete tests.py file for the current requirement."""
    from agents import Runner

    prompt = _build_generate_tests_prompt(requirement, solution_text)
    result = Runner.run_sync(
        create_openai_agent(model),
        prompt,
        max_turns=1,
    )
    tests_text = _normalize_python_file_text(str(result.final_output))
    return _remove_solution_imports(tests_text)


def _build_generate_tests_prompt(requirement: str, solution_text: str) -> str:
    solution_section = solution_text.strip() or "# solution.py is currently empty"
    return (
        "Create tests.py for this software requirement.\n\n"
        f"Requirement:\n{requirement}\n\n"
        "Current solution.py:\n"
        "```python\n"
        f"{solution_section}\n"
        "```\n\n"
        "Requirements for tests.py:\n"
        "- Return only Python code.\n"
        "- Define run_tests() -> dict[str, object].\n"
        "- Assume solution.py defines slugify_title(title: str) -> str.\n"
        "- Do not import solution or use solution.slugify_title; tests.py will be "
        "concatenated after solution.py, so call slugify_title directly.\n"
        "- Include realistic edge cases for punctuation, accents, apostrophes, "
        "whitespace, repeated separators, and casing.\n"
        "- The returned 'passed' field must be a bool, not a count.\n"
        "- If the implementation raises an exception for a case, capture that in "
        "the failures list instead of crashing the whole test run.\n"
        "- Do not import third-party packages.\n"
    )


def _normalize_python_file_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return f"{stripped}\n"


def _remove_solution_imports(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("from solution import "):
            continue
        if stripped == "import solution":
            continue

        lines.append(line.replace("solution.slugify_title", "slugify_title"))

    stripped_text = "\n".join(lines).strip()
    return f"{stripped_text}\n"
