from __future__ import annotations

import sqlite3
from typing import Generator
from discover.config import Settings
from discover.db import _sqlite_path_from_url


def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    settings = Settings.from_env()
    path = _sqlite_path_from_url(settings.database_url)
    if path is None:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
    else:
        conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
