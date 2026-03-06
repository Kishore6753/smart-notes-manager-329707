"""
Filesystem adapter for manual note version history.

Design:
- Each note has its own JSON file on disk (local-first, easy to inspect/backup).
- The store is append-only (versions are never mutated; restore creates a new version).
- All writes are atomic (write temp file then replace) to reduce risk of corruption.

File layout (default):
  <VERSIONS_DIR>/note_<note_id>.json

Environment:
- NOTES_VERSIONS_DIR (optional): directory where version files are stored.
  If unset, defaults to ./data/note_versions relative to backend working directory.

Contract:
- save_version(note_id, snapshot, message) -> VersionRecord
- list_versions(note_id) -> List[VersionRecord] (newest first)
- get_version(note_id, version_id) -> VersionRecord | None

Failure modes:
- Permission/IO errors when creating directories or writing files (raised with context).
- Corrupted JSON (raised with context; caller maps to HTTP 500 with detail).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VersionRecord:
    """A single note snapshot version record."""

    version_id: str
    created_at: str  # ISO 8601 UTC
    message: str
    snapshot: Dict[str, Any]


def _utc_now_iso() -> str:
    """Return ISO8601 timestamp in UTC with 'Z' suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# PUBLIC_INTERFACE
def get_versions_dir() -> Path:
    """Return the base directory for version files.

    Reads NOTES_VERSIONS_DIR environment variable, defaults to ./data/note_versions.
    """
    base = os.getenv("NOTES_VERSIONS_DIR", os.path.join("data", "note_versions"))
    return Path(base)


def _note_file_path(note_id: int) -> Path:
    """Return filesystem path for a note's version JSON file."""
    # Keep the naming stable and human searchable.
    return get_versions_dir() / f"note_{note_id}.json"


def _ensure_parent_dir(path: Path) -> None:
    """Ensure parent directory exists."""
    path.parent.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, obj: Dict[str, Any]) -> None:
    """Atomically write JSON to path (temp + replace).

    This minimizes the chance of a partially written file being observed.
    """
    _ensure_parent_dir(path)
    tmp_path = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{int(time.time() * 1000)}")
    data = json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False)
    try:
        tmp_path.write_text(data, encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        # Best-effort cleanup if replace fails before overwrite.
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def _load_note_versions_file(path: Path) -> Tuple[List[VersionRecord], Dict[str, Any]]:
    """Load the underlying JSON file, returning (records, raw_obj)."""
    if not path.exists():
        return ([], {"note_id": None, "versions": []})

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - boundary adds context
        raise RuntimeError(f"Failed to parse versions JSON file at {path}") from e

    versions_raw = raw.get("versions", [])
    records: List[VersionRecord] = []
    for v in versions_raw:
        # Defensive parsing: raise with context if shape is wrong.
        if not isinstance(v, dict):
            raise RuntimeError(f"Invalid version record shape in {path}: expected object, got {type(v)}")
        if "version_id" not in v or "created_at" not in v or "snapshot" not in v:
            raise RuntimeError(f"Invalid version record missing fields in {path}: keys={list(v.keys())}")
        records.append(
            VersionRecord(
                version_id=str(v["version_id"]),
                created_at=str(v["created_at"]),
                message=str(v.get("message", "")),
                snapshot=dict(v["snapshot"]),
            )
        )

    return (records, raw)


def _make_version_id(note_id: int) -> str:
    """Generate a stable, unique-ish version id."""
    # Keep it easy to debug: include note id + epoch millis.
    return f"v{note_id}_{int(time.time() * 1000)}"


# PUBLIC_INTERFACE
def save_version(note_id: int, snapshot: Dict[str, Any], message: str = "") -> VersionRecord:
    """Append a new snapshot version to the note's JSON version file.

    Inputs:
    - note_id: existing note id.
    - snapshot: dict capturing the note state (id/title/content/tags/is_favorite/created_at/updated_at).
    - message: optional user message (e.g., "Before big rewrite").

    Outputs:
    - VersionRecord for the created version.

    Side effects:
    - Writes/creates <VERSIONS_DIR>/note_<note_id>.json atomically.

    Errors:
    - Raises RuntimeError with context on IO/JSON failures.
    """
    path = _note_file_path(note_id)
    logger.info("VersionStore.save_version start note_id=%s path=%s", note_id, str(path))

    records, raw = _load_note_versions_file(path)
    version = VersionRecord(
        version_id=_make_version_id(note_id),
        created_at=_utc_now_iso(),
        message=(message or "").strip(),
        snapshot=snapshot,
    )

    # Maintain raw structure for forward compatibility.
    raw_note_id = raw.get("note_id")
    raw["note_id"] = note_id if raw_note_id in (None, note_id) else note_id
    raw.setdefault("versions", [])
    raw["versions"].append(asdict(version))

    try:
        _atomic_write_json(path, raw)
    except Exception as e:  # noqa: BLE001 - boundary adds context
        raise RuntimeError(f"Failed to write versions file for note_id={note_id} at {path}") from e

    logger.info(
        "VersionStore.save_version success note_id=%s version_id=%s versions_total=%s",
        note_id,
        version.version_id,
        len(raw["versions"]),
    )
    return version


# PUBLIC_INTERFACE
def list_versions(note_id: int) -> List[VersionRecord]:
    """List all saved versions for a note (newest first)."""
    path = _note_file_path(note_id)
    records, _raw = _load_note_versions_file(path)
    # Newest first for UI convenience.
    return list(reversed(records))


# PUBLIC_INTERFACE
def get_version(note_id: int, version_id: str) -> Optional[VersionRecord]:
    """Fetch a specific version by version_id, or None if not found."""
    path = _note_file_path(note_id)
    records, _raw = _load_note_versions_file(path)
    for r in records:
        if r.version_id == version_id:
            return r
    return None
