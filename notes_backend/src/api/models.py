"""Pydantic models for notes_backend API."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class TagOut(BaseModel):
    """A tag returned by the API."""

    id: int = Field(..., description="Tag id.")
    name: str = Field(..., description="Unique tag name.")


class NoteBase(BaseModel):
    """Base note fields."""

    title: str = Field(..., min_length=1, max_length=200, description="Note title.")
    content: str = Field(..., min_length=1, description="Note content (markdown/plain text).")
    tags: List[str] = Field(default_factory=list, description="List of tag names assigned to this note.")


class NoteCreate(NoteBase):
    """Payload to create a note."""
    pass


class NoteUpdate(BaseModel):
    """Payload to update a note; any field may be omitted."""

    title: Optional[str] = Field(None, min_length=1, max_length=200, description="Updated title.")
    content: Optional[str] = Field(None, min_length=1, description="Updated content.")
    tags: Optional[List[str]] = Field(
        None, description="If provided, replaces the note's tag set with this list."
    )
    is_favorite: Optional[bool] = Field(None, description="If provided, updates favorite state.")


class NoteOut(BaseModel):
    """Note returned by the API."""

    id: int = Field(..., description="Note id.")
    title: str = Field(..., description="Note title.")
    content: str = Field(..., description="Note content.")
    tags: List[str] = Field(default_factory=list, description="Tag names associated with this note.")
    is_favorite: bool = Field(..., description="Whether note is favorited.")
    created_at: datetime = Field(..., description="Creation timestamp (UTC).")
    updated_at: datetime = Field(..., description="Last update timestamp (UTC).")


class NotesListOut(BaseModel):
    """Paginated-ish list response (simple, limit-based)."""

    items: List[NoteOut] = Field(..., description="Notes returned.")
    total: int = Field(..., ge=0, description="Total matching notes (ignores limit).")


class SearchQuery(BaseModel):
    """Search request parameters (also used via query params)."""

    q: str = Field(..., min_length=1, description="Search query applied to title and content.")
    tag: Optional[str] = Field(None, description="Optional tag filter (tag name).")
    favorites_only: bool = Field(False, description="If true, only return favorited notes.")
    limit: int = Field(100, ge=1, le=500, description="Max number of notes to return.")


class FavoriteToggleIn(BaseModel):
    """Request to set favorite state."""

    is_favorite: bool = Field(..., description="Desired favorite state for the note.")


class FavoriteToggleOut(BaseModel):
    """Response after toggling favorite."""

    id: int = Field(..., description="Note id.")
    is_favorite: bool = Field(..., description="New favorite state.")


class NoteVersionSaveIn(BaseModel):
    """Request payload to manually save a note version snapshot."""

    message: Optional[str] = Field(
        None,
        max_length=200,
        description="Optional message describing why this version was saved.",
    )


class NoteVersionSummaryOut(BaseModel):
    """A lightweight version entry for listing and selection."""

    note_id: int = Field(..., description="Note id this version belongs to.")
    version_id: str = Field(..., description="Version identifier.")
    created_at: str = Field(..., description="When the version was created (ISO8601 UTC).")
    message: str = Field("", description="Optional message for the version.")


class NoteVersionsListOut(BaseModel):
    """List response for note versions."""

    items: List[NoteVersionSummaryOut] = Field(..., description="Versions for the note (newest first).")


class NoteVersionRestoreOut(BaseModel):
    """Response after restoring a version (returns the updated note)."""

    note: NoteOut = Field(..., description="Note after applying the restored snapshot.")
