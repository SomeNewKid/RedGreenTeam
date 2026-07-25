"""OpenAI-backed code generator for the Coder Agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents import Agent

_DEFAULT_MODEL = "gpt-4.1-mini"


def create_openai_agent(model: str = _DEFAULT_MODEL) -> Agent:
    """Create the Coder Agent used to generate solution.py content."""
    from agents import Agent

    return Agent(
        name="RedGreenTeam Coder Agent",
        model=model,
        instructions=(
            "You write the complete contents of a single solution.py file. "
            "Return only Python code with no markdown fences. "
            "Preserve the requirement in the module docstring when one is present. "
            "Do not create helper files, tests, or explanations."
        ),
    )


def generate_solution_text(prompt: str, model: str = _DEFAULT_MODEL) -> str:
    """Generate the complete solution.py file for the current coding task."""
    from agents import Runner

    result = Runner.run_sync(
        create_openai_agent(model),
        prompt,
        max_turns=1,
    )
    return _normalize_python_file_text(str(result.final_output))


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
