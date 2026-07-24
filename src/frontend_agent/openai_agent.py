"""AI agent that assesses frontend relevance for bug reports."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents import Agent

_DEFAULT_MODEL = "gpt-4.1-mini"
_AREA = "web frontend"
_AGENT_NAME = "Frontend Bug Assessor"
_PROMPT_TEMPLATE = """
Review this fictional software bug report from the perspective of a web
frontend specialist.

Bug report:
{bug_report}

Estimate the percentage likelihood that the bug is associated with web
frontend or user-interface code. Consider layout, styling, browser behavior,
client-side state, accessibility, form validation display, routing, rendering,
and user interactions. If the report points elsewhere, say so clearly.

Return only a JSON object with these exact fields:
- area: string, exactly "web frontend"
- likelihood_percent: integer from 0 to 100
- reasons: array of 2 to 5 short strings
"""


def create_frontend_agent(model: str = _DEFAULT_MODEL) -> Agent:
    """Create the Frontend Agent bug assessor."""
    from agents import Agent

    return Agent(
        name=_AGENT_NAME,
        model=model,
        instructions=(
            "You are a web frontend bug assessor. Return only valid JSON with "
            "a calibrated likelihood percentage and concise reasons."
        ),
    )


def run_frontend_agent(
    bug_report: str, model: str = _DEFAULT_MODEL
) -> dict[str, object]:
    """Run the Frontend Agent and return a validated assessment."""
    from agents import Runner

    prompt = _PROMPT_TEMPLATE.format(bug_report=bug_report.strip())
    result = Runner.run_sync(create_frontend_agent(model), prompt, max_turns=4)
    return _read_assessment(str(result.final_output))


def _read_assessment(text: str) -> dict[str, object]:
    data = json.loads(_extract_json_object(text))
    if not isinstance(data, dict):
        raise ValueError("Frontend Agent returned a non-object JSON value.")

    return _normalize_assessment(data)


def _normalize_assessment(data: dict[str, object]) -> dict[str, object]:
    area = data.get("area")
    if area != _AREA:
        raise ValueError(f"Frontend Agent area must be {_AREA!r}.")

    likelihood = data.get("likelihood_percent")
    if not isinstance(likelihood, int) or isinstance(likelihood, bool):
        raise ValueError("Frontend Agent likelihood_percent must be an integer.")
    if likelihood < 0 or likelihood > 100:
        raise ValueError("Frontend Agent likelihood_percent must be 0 to 100.")

    reasons = data.get("reasons")
    if not isinstance(reasons, list):
        raise ValueError("Frontend Agent reasons must be a list.")

    normalized_reasons = []
    for reason in reasons:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Frontend Agent reasons must be non-empty strings.")
        normalized_reasons.append(reason.strip())

    if len(normalized_reasons) < 2 or len(normalized_reasons) > 5:
        raise ValueError("Frontend Agent reasons must contain 2 to 5 entries.")

    return {
        "area": _AREA,
        "likelihood_percent": likelihood,
        "reasons": normalized_reasons,
    }


def _extract_json_object(text: str) -> str:
    stripped_text = text.strip()
    if stripped_text.startswith("{") and stripped_text.endswith("}"):
        return stripped_text

    start_index = stripped_text.find("{")
    end_index = stripped_text.rfind("}")
    if start_index == -1 or end_index == -1 or end_index < start_index:
        raise ValueError("Frontend Agent did not return a JSON object.")

    return stripped_text[start_index : end_index + 1]
