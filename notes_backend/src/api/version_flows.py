"""
Flows for manual note version history.

Flow: NoteVersionsFlow
Entry points:
- save_version(note_id, message) -> VersionRecord-like dict
- list_versions(note_id) -> list of VersionSummary dicts
- restore_version(note_id, version_id) -> restored Note dict

Contract notes:
- Save version snapshots the *current* note state from SQLite.
- Restore applies snapshot fields back into SQLite via NotesFlow.update_note (tags included),
  and also saves a new version that captures the post-restore state with message "Restored from <version_id>".
- All callers (API routes) go through this flow to avoid patchy logic in route handlers.

Failure modes:
- Note not found -> None/False style returns; API layer maps to 404.
- Version file missing/version_id not found -> None; API maps to 404.
- IO/JSON parse error -> RuntimeError; API maps to 500 with detail.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List, Optional

from .flows import NotesFlow
from .version_store import VersionRecord, get_version, list_versions, save_version

logger = logging.getLogger(__name__)


def _note_to_snapshot(note: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a Note dict to a stable snapshot dict."""
    # Keep snapshot close to API NoteOut shape; values are JSON-serializable.
    return {
        "id": int(note["id"]),
        "title": note.get("title") or "",
        "content": note.get("content") or "",
        "tags": list(note.get("tags") or []),
        "is_favorite": bool(note.get("is_favorite", False)),
        "created_at": note.get("created_at").isoformat() if hasattr(note.get("created_at"), "isoformat") else note.get("created_at"),
        "updated_at": note.get("updated_at").isoformat() if hasattr(note.get("updated_at"), "isoformat") else note.get("updated_at"),
    }


class NoteVersionsFlow:
    """Orchestration layer for note version history (filesystem-backed)."""

    def __init__(self, conn: sqlite3.Connection):
        self._notes = NotesFlow(conn)

    # PUBLIC_INTERFACE
    def save_version(self, note_id: int, message: str = "") -> Optional[Dict[str, Any]]:
        """Save a manual version snapshot for a note.

        Returns created version dict or None if note doesn't exist.
        """
        logger.info("NoteVersionsFlow.save_version start note_id=%s", note_id)
        note = self._notes.get_note(note_id)
        if not note:
            return None

        version = save_version(note_id=note_id, snapshot=_note_to_snapshot(note), message=message or "")
        return {
            "note_id": note_id,
            "version_id": version.version_id,
            "created_at": version.created_at,
            "message": version.message,
        }

    # PUBLIC_INTERFACE
    def list_versions(self, note_id: int) -> Optional[List[Dict[str, Any]]]:
        """List versions (newest first) for a note.

        Returns None if note doesn't exist (keeps API semantics consistent with /notes/{id}).
        """
        logger.info("NoteVersionsFlow.list_versions start note_id=%s", note_id)
        note = self._notes.get_note(note_id)
        if not note:
            return None

        versions = list_versions(note_id=note_id)
        return [
            {
                "note_id": note_id,
                "version_id": v.version_id,
                "created_at": v.created_at,
                "message": v.message,
            }
            for v in versions
        ]

    # PUBLIC_INTERFACE
    def restore_version(self, note_id: int, version_id: str) -> Optional[Dict[str, Any]]:
        """Restore a saved version snapshot into the current note.

        Returns restored Note dict, or None if note/version not found.
        Side effects:
        - Updates SQLite note fields via NotesFlow.update_note
        - Appends a new version capturing the state after restore.
        """
        logger.info("NoteVersionsFlow.restore_version start note_id=%s version_id=%s", note_id, version_id)

        note = self._notes.get_note(note_id)
        if not note:
            return None

        version: Optional[VersionRecord] = get_version(note_id=note_id, version_id=version_id)
        if not version:
            return None

        snap = version.snapshot or {}
        restored = self._notes.update_note(
            note_id=note_id,
            title=str(snap.get("title")) if "title" in snap else None,
            content=str(snap.get("content")) if "content" in snap else None,
            tags=list(snap.get("tags")) if "tags" in snap else None,
            is_favorite=bool(snap.get("is_favorite")) if "is_favorite" in snap else None,
        )
        if not restored:
            return None

        # Record that a restore occurred, for auditability.
        save_version(
            note_id=note_id,
            snapshot=_note_to_snapshot(restored),
            message=f"Restored from {version_id}",
        )
        logger.info("NoteVersionsFlow.restore_version success note_id=%s version_id=%s", note_id, version_id)
        return restored
