"""AI coordinator that starts the RedGreenTeam TDD workflow."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents import Agent

_OUTPUT_DIRECTORY = Path("/sandbox-output")
_SITE_DIRECTORY = _OUTPUT_DIRECTORY / "site"
_DEFAULT_MODEL = "gpt-4.1-mini"
_SOFTWARE_REQUIREMENT = (
    "Implement slugify_title(title: str) -> str so that article titles become "
    "ASCII lowercase URL slugs separated by hyphens. For example, "
    '"Beyoncé’s Music Won’t Age" should become "beyonces-music-wont-age".'
)
_AGENT_PROMPT = """
Coordinate the RedGreenTeam test-driven development workflow.

Software requirement:
Implement slugify_title(title: str) -> str so that article titles become ASCII
lowercase URL slugs separated by hyphens. For example, "Beyoncé’s Music Won’t Age"
should become "beyonces-music-wont-age".

Call run_red_green_loop exactly once with this requirement and max_iterations=10.

The loop asks coder_agent to create the initial stub in /sandbox-shared/solution.py,
asks tester_agent to create /sandbox-shared/tests.py once, asks coder_agent for an
initial implementation, then repeatedly asks tester_agent to run the existing tests
and asks coder_agent to update only /sandbox-shared/solution.py when tests fail.
When tests pass, save answer.txt with the final successful solution and tests.

After run_red_green_loop succeeds, summarize whether the final test assessment
passed, how many attempts were made, and where the final solution was written.
Do not call any other tool unless run_red_green_loop fails and you need to
inspect shared files.
"""


def create_openai_agent(model: str = _DEFAULT_MODEL) -> Agent:
    """Create the RedGreenTeam coordinator agent."""
    from agents import Agent

    from .openai_tools import (
        create_solution_skeleton_tool,
        get_test_assessment_tool,
        read_shared_file_tool,
        request_code_update_tool,
        request_solution_stub_tool,
        request_test_creation_tool,
        run_red_green_loop_tool,
        save_answer_tool,
        save_shared_file_tool,
    )

    return Agent(
        name="RedGreenTeam Coordinator",
        model=model,
        instructions=(
            "You are the RedGreenTeam coordinator. Start with the supplied "
            "software requirement, run the tester/coder red-green loop, and "
            "ensure answer.txt is saved with the final result."
        ),
        tools=[
            create_solution_skeleton_tool,
            get_test_assessment_tool,
            read_shared_file_tool,
            request_code_update_tool,
            request_solution_stub_tool,
            request_test_creation_tool,
            run_red_green_loop_tool,
            save_answer_tool,
            save_shared_file_tool,
        ],
    )


def run_red_green_coordinator(model: str = _DEFAULT_MODEL) -> str:
    """Run the RedGreenTeam coordinator agent and return its final response."""
    from agents import Runner

    _SITE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    result = Runner.run_sync(
        create_openai_agent(model),
        _AGENT_PROMPT,
        max_turns=14,
    )
    return str(result.final_output)
