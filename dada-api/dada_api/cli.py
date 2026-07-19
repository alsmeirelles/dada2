"""Operational command-line entrypoints for the DADA API."""

import argparse
import json
from pathlib import Path

from dada_api.main import create_app


def export_openapi(output: Path) -> None:
    """Write the generated OpenAPI contract deterministically."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """Dispatch operational commands."""
    parser = argparse.ArgumentParser(prog="dada-api")
    subparsers = parser.add_subparsers(dest="command", required=True)
    openapi_parser = subparsers.add_parser("export-openapi")
    openapi_parser.add_argument(
        "--output", type=Path, default=Path("openapi.json"), help="Output JSON path."
    )
    arguments = parser.parse_args()
    if arguments.command == "export-openapi":
        export_openapi(arguments.output)
