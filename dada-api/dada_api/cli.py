"""Operational command-line entrypoints for the DADA API."""

import argparse
import asyncio
import json
import sys
from getpass import getpass
from pathlib import Path

from dada_api.core.config import get_settings
from dada_api.db.session import async_session_factory, close_database
from dada_api.main import create_app
from dada_api.services.bootstrap import (
    BootstrapError,
    bootstrap_administrator,
    replace_bootstrap_administrator,
)


def export_openapi(output: Path) -> None:
    """Write the generated OpenAPI contract deterministically.

    Args:
        output: Destination JSON path.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def resolve_bootstrap_identity() -> tuple[str, str, str]:
    """Resolve the bootstrap identity from settings, prompting for what is missing.

    Returns:
        The username, display name, and plaintext password.

    Raises:
        BootstrapError: When any part of the identity is empty.
    """
    settings = get_settings()
    username = settings.seed_admin_username or input("Administrator username: ")
    display_name = settings.seed_admin_display_name or input("Display name: ")
    password = (
        settings.seed_admin_password.get_secret_value()
        if settings.seed_admin_password is not None
        else getpass("Password: ")
    )

    username, display_name = username.strip(), display_name.strip()
    if not username or not display_name or not password:
        raise BootstrapError(
            "Username, display name, and password are all required. Set "
            "DADA_SEED_ADMIN_USERNAME, DADA_SEED_ADMIN_DISPLAY_NAME, and "
            "DADA_SEED_ADMIN_PASSWORD, or supply them interactively."
        )
    return username, display_name, password


async def run_bootstrap(replace: bool) -> str:
    """Create or replace the bootstrap administrator.

    Args:
        replace: Whether to repoint the bootstrap record at a new identity.

    Returns:
        A message describing what happened, never containing the password.
    """
    username, display_name, password = resolve_bootstrap_identity()
    try:
        async with async_session_factory() as session:
            if replace:
                user = await replace_bootstrap_administrator(
                    session, username, display_name, password
                )
                return f"Bootstrap administrator replaced with {user.username!r}."

            user, created = await bootstrap_administrator(
                session, username, display_name, password
            )
            if created:
                return f"Bootstrap administrator {user.username!r} created."
            return f"Bootstrap administrator {user.username!r} already exists."
    finally:
        await close_database()


def main() -> None:
    """Dispatch operational commands."""
    parser = argparse.ArgumentParser(prog="dada-api")
    subparsers = parser.add_subparsers(dest="command", required=True)
    openapi_parser = subparsers.add_parser("export-openapi")
    openapi_parser.add_argument(
        "--output", type=Path, default=Path("openapi.json"), help="Output JSON path."
    )
    subparsers.add_parser(
        "bootstrap-admin",
        help="Create the initial administrator. Safe to rerun.",
    )
    subparsers.add_parser(
        "replace-bootstrap-admin",
        help="Explicitly change which identity is the bootstrap administrator.",
    )
    arguments = parser.parse_args()

    if arguments.command == "export-openapi":
        export_openapi(arguments.output)
        return

    replace = arguments.command == "replace-bootstrap-admin"
    try:
        print(asyncio.run(run_bootstrap(replace)))
    except BootstrapError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
