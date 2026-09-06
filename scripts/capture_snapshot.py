"""Capture ./data/ripple.db into a single self-contained snapshot file.

Invoked by `python run.py snapshot`. Kept as a script rather than inline in
run.py because it needs sqlite_vec, which lives in the virtualenv run.py
merely orchestrates.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import sqlite_vec


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)
    return conn


def capture(source: Path, target: Path) -> None:
    if target.exists():
        target.unlink()

    src = _connect(source)
    try:
        # Fold the write-ahead log in and drop free pages, so the snapshot is
        # one portable file rather than a db/wal/shm trio.
        src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        src.execute("VACUUM INTO ?", (str(target),))
    finally:
        src.close()

    dst = _connect(target)
    try:
        # Sessions are live bearer tokens, and stage_counters holds raw model
        # responses. Neither reproduces anything; both are better not shared.
        dst.execute("DELETE FROM sessions")
        dst.execute("UPDATE jobs SET stage_counters = NULL")
        dst.commit()
        dst.execute("VACUUM")
    finally:
        dst.close()


if __name__ == "__main__":
    capture(Path(sys.argv[1]), Path(sys.argv[2]))
