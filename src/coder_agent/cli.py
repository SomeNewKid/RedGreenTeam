"""Command-line interface for the Coder Agent."""

from __future__ import annotations

import argparse
import json

from .a2a_server import serve_coder_agent
from .tools import create_solution_stub, update_solution


def main(argv: list[str] | None = None) -> int:
    """Run the Coder Agent CLI or A2A service."""
    arguments = _parse_arguments(argv)
    if arguments.serve:
        serve_coder_agent(
            host=arguments.host,
            port=arguments.port,
            public_base_url=arguments.public_base_url,
        )
        return 0

    if arguments.action == "create_stub":
        result = create_solution_stub(arguments.message)
    else:
        result = update_solution(arguments.message)
    print(json.dumps(result, sort_keys=True))
    return 0


def _parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Coder Agent.")
    parser.add_argument("--serve", action="store_true", help="Start the A2A server.")
    parser.add_argument("--host", default="127.0.0.1", help="A2A bind host.")
    parser.add_argument("--port", type=int, default=8080, help="A2A bind port.")
    parser.add_argument(
        "--public-base-url",
        default="http://coder-agent:8080",
        help="Public base URL advertised in the Agent Card.",
    )
    parser.add_argument(
        "--message",
        default=(
            "Implement slugify_title(title: str) -> str so that article titles "
            "become ASCII lowercase URL slugs separated by hyphens."
        ),
        help="Requirement text used when not serving A2A requests.",
    )
    parser.add_argument(
        "--action",
        choices=("create_stub", "update_solution"),
        default="update_solution",
        help="Coder action to run when not serving A2A requests.",
    )
    return parser.parse_args(argv)
