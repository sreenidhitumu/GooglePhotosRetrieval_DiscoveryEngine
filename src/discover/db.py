from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from discover.config import project_root

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = project_root() / "migrations"


def get_engine(database_url: str) -> Engine:
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(database_url, connect_args=connect_args)


def _sqlite_path_from_url(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite:///"):
        return None
    path = database_url.removeprefix("sqlite:///")
    if path == ":memory:":
        return None
    return Path(path)


def ensure_sqlite_parent_dir(database_url: str) -> None:
    path = _sqlite_path_from_url(database_url)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)


def list_migration_files() -> list[Path]:
    if not MIGRATIONS_DIR.is_dir():
        return []
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def applied_versions(conn: sqlite3.Connection | Engine) -> set[str]:
    if isinstance(conn, Engine):
        with conn.connect() as c:
            return _applied_versions_sqlalchemy(c)
    return _applied_versions_sqlite(conn)


def _table_exists_sqlite(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _applied_versions_sqlite(conn: sqlite3.Connection) -> set[str]:
    if not _table_exists_sqlite(conn, "schema_migrations"):
        return set()
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {r[0] for r in rows}


def _applied_versions_sqlalchemy(connection) -> set[str]:
    result = connection.execute(
        text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        )
    ).fetchone()
    if not result:
        return set()
    rows = connection.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {r[0] for r in rows}


def _split_sql_statements(script: str) -> list[str]:
    """Split SQL file on semicolons outside of simple string literals."""
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    i = 0
    while i < len(script):
        ch = script[i]
        if ch == "'" and not in_single:
            in_single = True
            current.append(ch)
        elif ch == "'" and in_single:
            if i + 1 < len(script) and script[i + 1] == "'":
                current.append("''")
                i += 1
            else:
                in_single = False
                current.append(ch)
        elif ch == ";" and not in_single:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
        else:
            current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def migration_version(path: Path) -> str:
    match = re.match(r"^(\d+)_", path.name)
    return match.group(1) if match else path.stem


def run_migrations(engine: Engine) -> list[str]:
    """Apply pending SQL migrations. Returns list of applied version ids."""
    ensure_sqlite_parent_dir(str(engine.url))
    applied: list[str] = []

    raw_url = str(engine.url)
    if raw_url.startswith("sqlite"):
        return _run_migrations_sqlite(engine, applied)

    return _run_migrations_sqlalchemy(engine, applied)


def _run_migrations_sqlalchemy(engine: Engine, applied: list[str]) -> list[str]:
    with engine.begin() as conn:
        existing = _applied_versions_sqlalchemy(conn)
        for path in list_migration_files():
            version = migration_version(path)
            if version in existing:
                continue
            script = path.read_text(encoding="utf-8")
            for stmt in _split_sql_statements(script):
                conn.execute(text(stmt))
            conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:v)"),
                {"v": version},
            )
            applied.append(version)
            logger.info("Applied migration %s (%s)", version, path.name)
    return applied


def _run_migrations_sqlite(engine: Engine, applied: list[str]) -> list[str]:
    path = _sqlite_path_from_url(str(engine.url))
    if path is None:
        conn = sqlite3.connect(":memory:")
    else:
        conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        existing = _applied_versions_sqlite(conn)
        for mig_path in list_migration_files():
            version = migration_version(mig_path)
            if version in existing:
                continue
            script = mig_path.read_text(encoding="utf-8")
            for stmt in _split_sql_statements(script):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)",
                (version,),
            )
            applied.append(version)
            logger.info("Applied migration %s (%s)", version, mig_path.name)
        conn.commit()
    finally:
        conn.close()
    return applied


def migration_status(engine: Engine) -> Iterator[tuple[str, str, bool]]:
    """Yield (version, filename, applied) for each migration file."""
    if str(engine.url).startswith("sqlite"):
        path = _sqlite_path_from_url(str(engine.url))
        if path is None or not path.is_file():
            existing: set[str] = set()
        else:
            conn = sqlite3.connect(path)
            try:
                existing = _applied_versions_sqlite(conn)
            finally:
                conn.close()
    else:
        with engine.connect() as c:
            existing = _applied_versions_sqlalchemy(c)

    for mig_path in list_migration_files():
        version = migration_version(mig_path)
        yield version, mig_path.name, version in existing
