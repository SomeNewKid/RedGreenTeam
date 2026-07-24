"""Command-line interface for the Backend Agent."""

from __future__ import annotations

import argparse
import json

from .a2a_server import serve_backend_agent
from .openai_agent import run_backend_agent


def main(argv: list[str] | None = None) -> int:
    """Run the Backend Agent CLI or A2A service."""
    arguments = _parse_arguments(argv)
    if arguments.serve:
        serve_backend_agent(
            host=arguments.host,
            port=arguments.port,
            public_base_url=arguments.public_base_url,
        )
        return 0

    assessment = run_backend_agent(arguments.bug_report)
    print(json.dumps(assessment, sort_keys=True))
    return 0


def _parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Backend Agent.")
    parser.add_argument("--serve", action="store_true", help="Start the A2A server.")
    parser.add_argument("--host", default="127.0.0.1", help="A2A bind host.")
    parser.add_argument("--port", type=int, default=8080, help="A2A bind port.")
    parser.add_argument(
        "--public-base-url",
        default="http://backend-agent:8080",
        help="Public base URL advertised in the Agent Card.",
    )
    parser.add_argument(
        "--bug-report",
        default=(
            "The checkout API returns HTTP 500 after payment authorization, "
            "but the browser console shows no client-side errors."
        ),
        help="Bug report text to assess.",
    )
    return parser.parse_args(argv)
