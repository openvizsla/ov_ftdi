"""SQLite connection + migration runner for ovweb sessions."""

from __future__ import annotations

import importlib.resources
import sqlite3
from pathlib import Path

_MIGRATIONS_PKG = "ovweb.migrations"


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open (or create) a session database, apply pending migrations, and
    enable WAL mode. Returns a live connection.

    WAL is mandatory: concurrent reads during live capture ingest are a real
    workload (see CLAUDE.md hard constraints)."""
    con = sqlite3.connect(str(path), isolation_level=None)  # autocommit
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL;")
    con.execute("PRAGMA foreign_keys = ON;")
    con.execute("PRAGMA synchronous = NORMAL;")  # WAL-safe relaxation
    _apply_migrations(con)
    return con


def _apply_migrations(con: sqlite3.Connection) -> None:
    resources = importlib.resources.files(_MIGRATIONS_PKG)
    scripts = sorted(r for r in resources.iterdir() if r.name.endswith(".sql"))
    for script in scripts:
        sql = script.read_text(encoding="utf-8")
        con.executescript(sql)
