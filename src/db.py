"""
db.py - One place that opens the database.

Everything else imports connect() / transaction() from here, so moving to SQL
Server later means changing this file (and a few SQL dialect details).
"""
import sqlite3
from contextlib import contextmanager

from config import DB_PATH

_schema_checked = False


def connect() -> sqlite3.Connection:
    """Open a connection. Rows behave like dicts (row["name"])."""
    global _schema_checked
    con = sqlite3.connect(DB_PATH, isolation_level=None)  # we manage transactions ourselves
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    if not _schema_checked:
        ensure_schema(con)
        _schema_checked = True
    return con


def ensure_schema(con: sqlite3.Connection) -> None:
    """Add columns/tables that load_data.py does not create. Safe to run repeatedly."""
    cols = [r["name"] for r in con.execute("PRAGMA table_info(appointments)")]
    if "notes" not in cols:   # the patient's own words ("toothache since last night")
        con.execute("ALTER TABLE appointments ADD COLUMN notes TEXT")


@contextmanager
def transaction():
    """
    All-or-nothing database work:

        with transaction() as con:
            ...writes...      # committed if no error, rolled back if one is raised

    BEGIN IMMEDIATE locks the database for writing, so two callers cannot
    book the same slot at the same moment.
    """
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
