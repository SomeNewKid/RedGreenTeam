"""AI agent that classifies bug reports through specialist workers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents import Agent

_OUTPUT_DIRECTORY = Path("/sandbox-output")
_SITE_DIRECTORY = _OUTPUT_DIRECTORY / "site"
_DEFAULT_MODEL = "gpt-4.1-mini"
_AGENT_PROMPT = """
Assess this fictional software bug report:

Users report that after submitting the billing settings form, the page shows a
success toast, but refreshing the page restores the old billing address. The
browser network tab shows a successful 200 response, and the audit log later
shows two address records for the same account.

Call get_parallel_bug_assessments exactly once with the full bug report text.
Treat the response as a JSON object containing frontend, backend, and database
specialist assessments. Each assessment has an area, likelihood_percent, reasons,
and task_id.

Decide the final likely category and priority. Choose one category from:
frontend, backend, database, mixed, or unclear. Choose one priority from:
P0, P1, P2, P3, or P4.

Save the final answer with the save_answer tool. Include the submitted bug
report, each worker's likelihood percentage with short reasons, the final
category, the final priority, and a concise justification. Do not finish until
both tool calls have succeeded.
"""


def create_openai_agent(model: str = _DEFAULT_MODEL) -> Agent:
    """Create the Sandbox Agent bug report manager."""
    from agents import Agent

    from .openai_tools import (
        get_parallel_bug_assessments_tool,
        save_answer_tool,
    )

    return Agent(
        name="Bug Report Manager",
        model=model,
        instructions=(
            "You are a careful bug report triage manager. Use the provided "
            "parallel assessment tool exactly once, synthesize the specialist "
            "opinions, and save the final classification. Do not finish until "
            "both tool calls have succeeded."
        ),
        tools=[
            get_parallel_bug_assessments_tool,
            save_answer_tool,
        ],
    )


def run_html_element_agent(model: str = _DEFAULT_MODEL) -> str:
    """Run the HTML element agent and save its final response."""
    from agents import Runner

    _SITE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    result = Runner.run_sync(
        create_openai_agent(model),
        _AGENT_PROMPT,
        max_turns=14,
    )
    return str(result.final_output)
