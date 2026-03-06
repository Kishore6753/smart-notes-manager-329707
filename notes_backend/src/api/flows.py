"""
Reusable flows (use-cases) for notes_backend.

We keep API handlers thin; all business logic + SQL orchestration is centralized here.

Flow: NotesFlow
Entry points:
- create_note
- get_note
- list_notes
- update_note
- delete_note
- search_notes
- list_tags
- set_favorite
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .db import init_schema

logger = logging.getLogger(__name__)


def _row_to_note(conn: sqlite3.Connection, note_row: sqlite3.Row) -> Dict:
    """Build note dict with tags list."""
    note_id = int(note_row["id"])
    tags = [
        r["name"]
        for r in conn.execute(
            """
            SELECT t.name
            FROM tags t
            JOIN note_tags nt ON nt.tag_id = t.id
            WHERE nt.note_id = ?
            ORDER BY t.name
            """,
            (note_id,),
        ).fetchall()
    ]
    created_at = datetime.fromisoformat(note_row["created_at"].replace("Z", "")) if isinstance(note_row["created_at"], str) else note_row["created_at"]
    updated_at = datetime.fromisoformat(note_row["updated_at"].replace("Z", "")) if isinstance(note_row["updated_at"], str) else note_row["updated_at"]

    return {
        "id": note_id,
        "title": note_row["title"],
        "content": note_row["content"],
        "tags": tags,
        "is_favorite": bool(note_row["is_favorite"]),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _ensure_tags(conn: sqlite3.Connection, tag_names: List[str]) -> List[int]:
    """Ensure tag rows exist for each name; return tag_ids in same order as input (deduped)."""
    normalized = []
    seen = set()
    for t in tag_names:
        name = (t or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(name)

    tag_ids: List[int] = []
    for name in normalized:
        conn.execute("INSERT OR IGNORE INTO tags(name) VALUES(?)", (name,))
        row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        tag_ids.append(int(row["id"]))
    return tag_ids


def _replace_note_tags(conn: sqlite3.Connection, note_id: int, tag_names: List[str]) -> None:
    """Replace note's tag set with provided tag_names."""
    conn.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
    tag_ids = _ensure_tags(conn, tag_names)
    for tag_id in tag_ids:
        conn.execute(
            "INSERT OR IGNORE INTO note_tags(note_id, tag_id) VALUES(?, ?)",
            (note_id, tag_id),
        )


def _build_filters(tag: Optional[str], favorites_only: bool) -> Tuple[str, List]:
    """Return SQL WHERE clause and params for tag/favorites filters."""
    where_parts: List[str] = []
    params: List = []

    if favorites_only:
        where_parts.append("n.is_favorite = 1")

    if tag:
        where_parts.append(
            """
            EXISTS (
              SELECT 1
              FROM note_tags nt
              JOIN tags t ON t.id = nt.tag_id
              WHERE nt.note_id = n.id AND lower(t.name) = lower(?)
            )
            """
        )
        params.append(tag.strip())

    where_sql = "WHERE " + " AND ".join(f"({p})" for p in where_parts) if where_parts else ""
    return where_sql, params


class NotesFlow:
    """Orchestration layer for all note-related use cases."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        init_schema(self._conn)

    # PUBLIC_INTERFACE
    def create_note(self, title: str, content: str, tags: List[str]) -> Dict:
        """Create a note and assign tags."""
        logger.info("NotesFlow.create_note start title_len=%s content_len=%s", len(title), len(content))
        with self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO notes(title, content, is_favorite, created_at, updated_at)
                VALUES(?, ?, 0, datetime('now'), datetime('now'))
                """,
                (title, content),
            )
            note_id = int(cur.lastrowid)
            _replace_note_tags(self._conn, note_id, tags)
            row = self._conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        logger.info("NotesFlow.create_note success id=%s", note_id)
        return _row_to_note(self._conn, row)

    # PUBLIC_INTERFACE
    def get_note(self, note_id: int) -> Optional[Dict]:
        """Get a single note by id."""
        row = self._conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if not row:
            return None
        return _row_to_note(self._conn, row)

    # PUBLIC_INTERFACE
    def delete_note(self, note_id: int) -> bool:
        """Delete a note. Returns True if deleted."""
        with self._conn:
            cur = self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return cur.rowcount > 0

    # PUBLIC_INTERFACE
    def update_note(
        self,
        note_id: int,
        title: Optional[str],
        content: Optional[str],
        tags: Optional[List[str]],
        is_favorite: Optional[bool],
    ) -> Optional[Dict]:
        """Update note fields; returns updated note or None if not found."""
        existing = self._conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if not existing:
            return None

        new_title = title if title is not None else existing["title"]
        new_content = content if content is not None else existing["content"]
        new_is_favorite = int(is_favorite) if is_favorite is not None else int(existing["is_favorite"])

        with self._conn:
            self._conn.execute(
                """
                UPDATE notes
                SET title = ?, content = ?, is_favorite = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (new_title, new_content, new_is_favorite, note_id),
            )
            if tags is not None:
                _replace_note_tags(self._conn, note_id, tags)
            row = self._conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()

        return _row_to_note(self._conn, row)

    # PUBLIC_INTERFACE
    def list_notes(
        self,
        tag: Optional[str],
        favorites_only: bool,
        limit: int,
    ) -> Tuple[List[Dict], int]:
        """List notes with optional filters. Returns (items, total)."""
        where_sql, params = _build_filters(tag, favorites_only)

        total = int(
            self._conn.execute(
                f"SELECT COUNT(*) AS c FROM notes n {where_sql}",
                params,
            ).fetchone()["c"]
        )

        rows = self._conn.execute(
            f"""
            SELECT n.*
            FROM notes n
            {where_sql}
            ORDER BY n.updated_at DESC, n.id DESC
            LIMIT ?
            """,
            [*params, limit],
        ).fetchall()

        return ([_row_to_note(self._conn, r) for r in rows], total)

    # PUBLIC_INTERFACE
    def search_notes(
        self,
        q: str,
        tag: Optional[str],
        favorites_only: bool,
        limit: int,
    ) -> Tuple[List[Dict], int]:
        """Search notes by LIKE match on title/content, with optional filters."""
        where_sql, params = _build_filters(tag, favorites_only)
        q_like = f"%{q.strip()}%"
        search_clause = "(n.title LIKE ? OR n.content LIKE ?)"
        params2 = [q_like, q_like]

        combined_where = "WHERE " + " AND ".join(
            p for p in [search_clause, where_sql.replace("WHERE ", "", 1).strip()] if p
        )
        combined_params = [*params2, *params]

        total = int(
            self._conn.execute(
                f"SELECT COUNT(*) AS c FROM notes n {combined_where}",
                combined_params,
            ).fetchone()["c"]
        )

        rows = self._conn.execute(
            f"""
            SELECT n.*
            FROM notes n
            {combined_where}
            ORDER BY n.updated_at DESC, n.id DESC
            LIMIT ?
            """,
            [*combined_params, limit],
        ).fetchall()

        return ([_row_to_note(self._conn, r) for r in rows], total)

    # PUBLIC_INTERFACE
    def list_tags(self) -> List[Dict]:
        """Return tags with counts (for UI filter)."""
        rows = self._conn.execute(
            """
            SELECT t.id, t.name, COUNT(nt.note_id) AS note_count
            FROM tags t
            LEFT JOIN note_tags nt ON nt.tag_id = t.id
            GROUP BY t.id, t.name
            ORDER BY lower(t.name)
            """
        ).fetchall()
        return [{"id": int(r["id"]), "name": r["name"], "note_count": int(r["note_count"])} for r in rows]

    # PUBLIC_INTERFACE
    def set_favorite(self, note_id: int, is_favorite: bool) -> Optional[Dict]:
        """Set favorite state; returns updated note or None if not found."""
        row = self._conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if not row:
            return None
        with self._conn:
            self._conn.execute(
                "UPDATE notes SET is_favorite = ?, updated_at = datetime('now') WHERE id = ?",
                (1 if is_favorite else 0, note_id),
            )
            row2 = self._conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        return _row_to_note(self._conn, row2)
