"""Alembic migration-state inspection helpers."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


def alembic_config() -> Config:
    """Build an Alembic configuration rooted at the installed project."""
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def migration_head() -> str:
    """Return the single expected migration head revision."""
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("No Alembic migration head exists.")
    return head


async def current_revision(connection: AsyncConnection) -> str | None:
    """Return the database revision, or none for an unmigrated database."""
    result = await connection.execute(
        text("SELECT to_regclass('public.alembic_version')")
    )
    if result.scalar_one_or_none() is None:
        return None
    revision_result = await connection.execute(
        text("SELECT version_num FROM alembic_version")
    )
    return revision_result.scalar_one_or_none()
