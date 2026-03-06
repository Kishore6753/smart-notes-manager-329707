"""
SQLite adapter used by the notes_backend service.

We keep DB access isolated here to avoid scattering SQL across route handlers.

Contract:
- get_db_path(): reads SQLITE_DB env var; falls back to ./myapp.db for local dev.
- connect(): returns sqlite3.Connection with row_factory=Row and foreign keys enabled.
- init_schema(): creates tables/indexes if missing (idempotent).
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)


# PUBLIC_INTERFACE
def get_db_path() -> str:
    """Return the SQLite database file path.

    The database container exposes path via environment variable SQLITE_DB.
    If it's not set, we default to 'myapp.db' in the backend working directory
    (useful for local dev, but production should set SQLITE_DB).
    """
    return os.getenv("SQLITE_DB", "myapp.db")


# PUBLIC_INTERFACE
def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open a SQLite connection with app defaults."""
    path = db_path or get_db_path()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# PUBLIC_INTERFACE
def init_schema(conn: sqlite3.Connection) -> None:
    """Ensure required tables exist (idempotent)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          content TEXT NOT NULL,
          is_favorite INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tags (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS note_tags (
          note_id INTEGER NOT NULL,
          tag_id INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          PRIMARY KEY (note_id, tag_id),
          FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
          FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )
        """
    )

    conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_is_favorite ON notes(is_favorite)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_note_tags_note_id ON note_tags(note_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_note_tags_tag_id ON note_tags(tag_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(title)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_content ON notes(content)")
    logger.info("DB schema ensured (tables/indexes present).")
