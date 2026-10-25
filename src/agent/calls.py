"""calls.py - Call summaries and human-transfer queue (stored in the same database)."""
from datetime import timedelta

from . import ai_config
import config
from db import connect, transaction

_ready = False
_DDL = """
CREATE TABLE IF NOT EXISTS call_logs (
    call_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, started_at TEXT, ended_at TEXT,
    duration_sec INTEGER, language TEXT, patient_id INTEGER, outcome TEXT, summary TEXT,
    follow_up TEXT, appointment_refs TEXT, transferred INTEGER DEFAULT 0, end_reason TEXT);
CREATE TABLE IF NOT EXISTS handoffs (
    handoff_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, created_at TEXT,
    reason TEXT, patient_id INTEGER, status TEXT DEFAULT 'open');
"""


def _ensure():
    global _ready
    if not _ready:
        con = connect()
        try:
            con.executescript(_DDL)
        finally:
            con.close()
        _ready = True


def _ts() -> str:
    return config.get_now().strftime("%Y-%m-%d %H:%M:%S")


def create_handoff(session_id: str, reason: str, patient_id: int | None) -> int:
    _ensure()
    with transaction() as con:
        cur = con.execute("INSERT INTO handoffs (session_id, created_at, reason, patient_id) VALUES (?,?,?,?)",
                          (session_id, _ts(), reason, patient_id))
        return cur.lastrowid


def save_call_log(**f) -> int:
    _ensure()
    with transaction() as con:
        cur = con.execute("""INSERT INTO call_logs (session_id, started_at, ended_at, duration_sec,
            language, patient_id, outcome, summary, follow_up, appointment_refs, transferred, end_reason)
            VALUES (:session_id,:started_at,:ended_at,:duration_sec,:language,:patient_id,:outcome,
                    :summary,:follow_up,:appointment_refs,:transferred,:end_reason)""", f)
        return cur.lastrowid


def list_call_logs(limit: int = 50) -> list[dict]:
    _ensure()
    con = connect()
    try:
        return [dict(r) for r in con.execute(
            "SELECT * FROM call_logs ORDER BY call_id DESC LIMIT ?", (limit,))]
    finally:
        con.close()


def list_handoffs(status: str = "open") -> list[dict]:
    _ensure()
    con = connect()
    try:
        return [dict(r) for r in con.execute(
            "SELECT * FROM handoffs WHERE status = ? ORDER BY handoff_id DESC", (status,))]
    finally:
        con.close()


def purge_old(days: int = ai_config.CALL_LOG_RETENTION_DAYS) -> int:
    """Retention: delete call summaries older than `days`. Run it daily in production."""
    _ensure()
    cutoff = (config.get_now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with transaction() as con:
        return con.execute("DELETE FROM call_logs WHERE ended_at < ?", (cutoff,)).rowcount
