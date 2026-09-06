"""Select a SQLite driver that can load sqlite-vec on every runtime.

Render's native Python sqlite3 build omits loadable-extension support. The
Linux dependency therefore supplies a statically linked SQLite build with
that feature enabled, while local platforms continue using the standard
library driver.
"""

from __future__ import annotations

try:
    import pysqlite3 as sqlite3
except ImportError:  # pysqlite3-binary is installed only on Linux.
    import sqlite3

__all__ = ["sqlite3"]
