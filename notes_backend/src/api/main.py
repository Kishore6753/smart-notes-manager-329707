"""
notes_backend FastAPI application.

Provides REST APIs for a local-first notes application:
- Notes CRUD
- Search
- Tags
- Favorites

Environment:
- SQLITE_DB: path to SQLite database file (provided by notes_database container).

The API is designed for a single-user local app (no auth in this template).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .db import connect
from .flows import NotesFlow
from .models import (
    FavoriteToggleIn,
    FavoriteToggleOut,
    NoteCreate,
    NoteOut,
    NotesListOut,
    NoteUpdate,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("notes_backend")

openapi_tags = [
    {"name": "Health", "description": "Service health and debugging helpers."},
    {"name": "Notes", "description": "Create, list, update, delete notes."},
    {"name": "Search", "description": "Search notes by content/title, with optional filters."},
    {"name": "Tags", "description": "List tags and their usage."},
    {"name": "Favorites", "description": "Pin/favorite notes for quick access."},
]

app = FastAPI(
    title="Smart Notes Manager API",
    description="FastAPI backend for a local-first notes application (CRUD, search, tags, favorites).",
    version="0.1.0",
    openapi_tags=openapi_tags,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _flow() -> NotesFlow:
    """Create a NotesFlow with a fresh DB connection (simple, safe for SQLite)."""
    conn = connect()
    return NotesFlow(conn)


@app.get("/", tags=["Health"], summary="Health check", operation_id="health_check")
def health_check():
    """Service health check."""
    return {"message": "Healthy"}


@app.get(
    "/notes",
    tags=["Notes"],
    response_model=NotesListOut,
    summary="List notes",
    operation_id="list_notes",
)
def list_notes(
    tag: Optional[str] = Query(None, description="Filter by tag name (case-insensitive)."),
    favorites_only: bool = Query(False, description="If true, only return favorited notes."),
    limit: int = Query(100, ge=1, le=500, description="Max number of notes to return."),
):
    """List notes (optionally filtered by tag and/or favorites)."""
    flow = _flow()
    items, total = flow.list_notes(tag=tag, favorites_only=favorites_only, limit=limit)
    return {"items": items, "total": total}


@app.post(
    "/notes",
    tags=["Notes"],
    response_model=NoteOut,
    summary="Create a note",
    operation_id="create_note",
)
def create_note(payload: NoteCreate):
    """Create a note and assign tags."""
    flow = _flow()
    created = flow.create_note(title=payload.title, content=payload.content, tags=payload.tags)
    return created


@app.get(
    "/notes/{note_id}",
    tags=["Notes"],
    response_model=NoteOut,
    summary="Get a note",
    operation_id="get_note",
)
def get_note(note_id: int):
    """Get a single note by id."""
    flow = _flow()
    note = flow.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@app.put(
    "/notes/{note_id}",
    tags=["Notes"],
    response_model=NoteOut,
    summary="Update a note",
    operation_id="update_note",
)
def update_note(note_id: int, payload: NoteUpdate):
    """Update a note; fields omitted are left unchanged.

    If `tags` is provided, it replaces the existing tag set.
    """
    flow = _flow()
    updated = flow.update_note(
        note_id=note_id,
        title=payload.title,
        content=payload.content,
        tags=payload.tags,
        is_favorite=payload.is_favorite,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Note not found")
    return updated


@app.delete(
    "/notes/{note_id}",
    tags=["Notes"],
    summary="Delete a note",
    operation_id="delete_note",
)
def delete_note(note_id: int):
    """Delete a note by id."""
    flow = _flow()
    ok = flow.delete_note(note_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"deleted": True}


@app.get(
    "/notes/search",
    tags=["Search"],
    response_model=NotesListOut,
    summary="Search notes",
    operation_id="search_notes",
)
def search_notes(
    q: str = Query(..., min_length=1, description="Search query applied to title and content."),
    tag: Optional[str] = Query(None, description="Optional tag filter."),
    favorites_only: bool = Query(False, description="If true, only return favorited notes."),
    limit: int = Query(100, ge=1, le=500, description="Max number of notes to return."),
):
    """Search notes by a simple LIKE match against title/content."""
    flow = _flow()
    items, total = flow.search_notes(q=q, tag=tag, favorites_only=favorites_only, limit=limit)
    return {"items": items, "total": total}


@app.get(
    "/tags",
    tags=["Tags"],
    summary="List tags",
    operation_id="list_tags",
)
def list_tags():
    """List all tags with usage counts."""
    flow = _flow()
    return {"items": flow.list_tags()}


@app.put(
    "/favorites/{note_id}",
    tags=["Favorites"],
    response_model=FavoriteToggleOut,
    summary="Set favorite state for a note",
    operation_id="set_favorite",
)
def set_favorite(note_id: int, payload: FavoriteToggleIn):
    """Set (not toggle) favorite state for a note."""
    flow = _flow()
    updated = flow.set_favorite(note_id=note_id, is_favorite=payload.is_favorite)
    if not updated:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"id": updated["id"], "is_favorite": updated["is_favorite"]}
