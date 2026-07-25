"""Bootstrap the coder agent command-line application."""

from . import cli


def main() -> None:
    """Run the coder agent command-line application."""
    raise SystemExit(cli.main())


if __name__ == "__main__":
    main()
