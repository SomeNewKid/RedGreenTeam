"""AI agent that assesses backend relevance for bug reports."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents import Agent

_DEFAULT_MODEL = "gpt-4.1-mini"
_AREA = "web server backend"
_AGENT_NAME = "Backend Bug Assessor"
_PROMPT_TEMPLATE = """
Review this fictional software bug report from the perspective of a web server
backend specialist.

Bug report:
{bug_report}

Estimate the percentage likelihood that the bug is associated with web server
backend behavior. Consider APIs, request handling, authentication,
authorization, background jobs, integrations, server errors, business logic,
validation, and service-to-service communication. If the report points
elsewhere, say so clearly.

Return only a JSON object with these exact fields:
- area: string, exactly "web server backend"
- likelihood_percent: integer from 0 to 100
- reasons: array of 2 to 5 short strings
"""


def create_backend_agent(model: str = _DEFAULT_MODEL) -> Agent:
    """Create the Backend Agent bug assessor."""
    from agents import Agent

    return Agent(
        name=_AGENT_NAME,
        model=model,
        instructions=(
            "You are a web server backend bug assessor. Return only valid JSON "
            "with a calibrated likelihood percentage and concise reasons."
        ),
    )


def run_backend_agent(
    bug_report: str, model: str = _DEFAULT_MODEL
) -> dict[str, object]:
    """Run the Backend Agent and return a validated assessment."""
    from agents import Runner

    prompt = _PROMPT_TEMPLATE.format(bug_report=bug_report.strip())
    result = Runner.run_sync(create_backend_agent(model), prompt, max_turns=4)
    return _read_assessment(str(result.final_output))


def _read_assessment(text: str) -> dict[str, object]:
    data = json.loads(_extract_json_object(text))
    if not isinstance(data, dict):
        raise ValueError("Backend Agent returned a non-object JSON value.")

    return _normalize_assessment(data)


def _normalize_assessment(data: dict[str, object]) -> dict[str, object]:
    area = data.get("area")
    if area != _AREA:
        raise ValueError(f"Backend Agent area must be {_AREA!r}.")

    likelihood = data.get("likelihood_percent")
    if not isinstance(likelihood, int) or isinstance(likelihood, bool):
        raise ValueError("Backend Agent likelihood_percent must be an integer.")
    if likelihood < 0 or likelihood > 100:
        raise ValueError("Backend Agent likelihood_percent must be 0 to 100.")

    reasons = data.get("reasons")
    if not isinstance(reasons, list):
        raise ValueError("Backend Agent reasons must be a list.")

    normalized_reasons = []
    for reason in reasons:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Backend Agent reasons must be non-empty strings.")
        normalized_reasons.append(reason.strip())

    if len(normalized_reasons) < 2 or len(normalized_reasons) > 5:
        raise ValueError("Backend Agent reasons must contain 2 to 5 entries.")

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
        raise ValueError("Backend Agent did not return a JSON object.")

    return stripped_text[start_index : end_index + 1]
