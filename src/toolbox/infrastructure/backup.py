"""SQLite backup operations kept outside application/domain modules."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def backup(database: Path, destination: Path) -> None:
    """Create a consistent SQLite backup through SQLite's online backup API."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as source, sqlite3.connect(destination) as target:
        source.backup(target)


def restore(source_path: Path, database: Path) -> None:
    """Restore a backup into the configured database path."""

    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_path) as source, sqlite3.connect(database) as target:
        source.backup(target)
