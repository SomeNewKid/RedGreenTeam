"""Command-line interface for the Database Agent."""

from __future__ import annotations

import argparse
import json

from .a2a_server import serve_database_agent
from .openai_agent import run_database_agent


def main(argv: list[str] | None = None) -> int:
    """Run the Database Agent CLI or A2A service."""
    arguments = _parse_arguments(argv)
    if arguments.serve:
        serve_database_agent(
            host=arguments.host,
            port=arguments.port,
            public_base_url=arguments.public_base_url,
        )
        return 0

    assessment = run_database_agent(arguments.bug_report)
    print(json.dumps(assessment, sort_keys=True))
    return 0


def _parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Database Agent.")
    parser.add_argument("--serve", action="store_true", help="Start the A2A server.")
    parser.add_argument("--host", default="127.0.0.1", help="A2A bind host.")
    parser.add_argument("--port", type=int, default=8080, help="A2A bind port.")
    parser.add_argument(
        "--public-base-url",
        default="http://database-agent:8080",
        help="Public base URL advertised in the Agent Card.",
    )
    parser.add_argument(
        "--bug-report",
        default=(
            "Saved profile changes disappear after refresh, and reports show "
            "duplicate customer records created minutes apart."
        ),
        help="Bug report text to assess.",
    )
    return parser.parse_args(argv)
