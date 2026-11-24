import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).with_name("leads.db")))

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    number        TEXT NOT NULL UNIQUE,
    contact_id    TEXT,
    token         TEXT NOT NULL UNIQUE,
    status        TEXT NOT NULL DEFAULT 'PENDENTE',
    created_at    TEXT,
    sent_at       TEXT,
    clicked_at    TEXT,
    message_index INTEGER,
    send_count    INTEGER NOT NULL DEFAULT 0,
    followup_day  INTEGER NOT NULL DEFAULT 0,
    sends_in_day  INTEGER NOT NULL DEFAULT 0,
    slot_cursor   INTEGER NOT NULL DEFAULT 0,
    day_anchor    TEXT
);
"""

MIGRATIONS = {
    "message_index": "ALTER TABLE leads ADD COLUMN message_index INTEGER",
    "send_count": (
        "ALTER TABLE leads ADD COLUMN send_count INTEGER NOT NULL DEFAULT 0"
    ),
    "followup_day": (
        "ALTER TABLE leads ADD COLUMN followup_day INTEGER NOT NULL DEFAULT 0"
    ),
    "sends_in_day": (
        "ALTER TABLE leads ADD COLUMN sends_in_day INTEGER NOT NULL DEFAULT 0"
    ),
    "slot_cursor": (
        "ALTER TABLE leads ADD COLUMN slot_cursor INTEGER NOT NULL DEFAULT 0"
    ),
    "day_anchor": "ALTER TABLE leads ADD COLUMN day_anchor TEXT",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(today: str | None = None) -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(leads)")
        }
        for column, statement in MIGRATIONS.items():
            if column not in columns:
                conn.execute(statement)

        anchor = today or datetime.now(timezone.utc).date().isoformat()
        conn.execute(
            "UPDATE leads SET send_count = 1, followup_day = 1, "
            "sends_in_day = 0, slot_cursor = 0, day_anchor = ? "
            "WHERE send_count = 0 "
            "AND (status IN ('ENVIADO', 'ATIVO') OR sent_at IS NOT NULL)",
            (anchor,),
        )


def upsert_lead(number: str, contact_id: str | None, token: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO leads (number, contact_id, token, status, created_at)
            VALUES (?, ?, ?, 'PENDENTE', ?)
            ON CONFLICT(number) DO UPDATE SET
                contact_id = COALESCE(excluded.contact_id, leads.contact_id)
            """,
            (number, contact_id, token, _now()),
        )


def list_running() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM leads WHERE status IN ('PENDENTE', 'ENVIADO') "
            "ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def get_by_token(token: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM leads WHERE token = ?", (token,)
        ).fetchone()
    return dict(row) if row else None


def initialize_lead_day(token: str, day_anchor: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET day_anchor = ?, sends_in_day = 0, "
            "slot_cursor = 0 WHERE token = ? AND day_anchor IS NULL",
            (day_anchor, token),
        )


def advance_day(
    token: str, followup_day: int, day_anchor: str, status: str
) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET followup_day = ?, sends_in_day = 0, "
            "slot_cursor = 0, day_anchor = ?, status = ? WHERE token = ?",
            (followup_day, day_anchor, status, token),
        )


def set_slot_cursor(token: str, slot_cursor: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET slot_cursor = ? WHERE token = ?",
            (slot_cursor, token),
        )


def register_send(token: str, message_index: int, now: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET send_count = send_count + 1, "
            "sends_in_day = sends_in_day + 1, "
            "slot_cursor = slot_cursor + 1, sent_at = ?, "
            "message_index = ?, status = 'ENVIADO' "
            "WHERE token = ? AND status IN ('PENDENTE', 'ENVIADO')",
            (now, message_index, token),
        )


def mark_active(token: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET status = 'ATIVO', "
            "clicked_at = COALESCE(clicked_at, ?) WHERE token = ?",
            (_now(), token),
        )


def count_by_status() -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS total FROM leads GROUP BY status"
        ).fetchall()
    return {row["status"]: row["total"] for row in rows}
