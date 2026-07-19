import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

DB_PATH = os.getenv("DB_PATH", "roast_bot.db")


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                username TEXT,
                content TEXT,
                hour_utc INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS roast_log (
                user_id TEXT,
                roasted_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


def record_message(user_id: str, username: str, content: str, hour_utc: int):
    with _conn() as c:
        c.execute(
            "INSERT INTO messages (user_id, username, content, hour_utc) VALUES (?, ?, ?, ?)",
            (user_id, username, content, hour_utc),
        )


def prune_old_messages(days: int = 30):
    """Keeps the table from growing forever -- older raw message content
    isn't needed once it's aged out of any reasonable roast window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as c:
        c.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))


def get_user_stats(user_id: str, days: int = 7) -> dict:
    """Message count, late-night ratio, and a few sample messages for a
    user over the trailing window -- the raw material a roast draws from."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT content, hour_utc, username FROM messages WHERE user_id = ? AND created_at >= ? ORDER BY id DESC",
            (user_id, cutoff),
        ).fetchall()

    if not rows:
        return {"count": 0}

    count = len(rows)
    username = rows[0]["username"]
    # Late night = 5am-11am UTC, which is roughly 1am-7am ET -- a rough
    # "sleeps in / posting at odd hours" signal, not a precise timezone
    # calculation since we don't know each user's actual timezone.
    late_night = sum(1 for r in rows if r["hour_utc"] is not None and 5 <= r["hour_utc"] <= 11)
    late_night_ratio = late_night / count if count else 0

    lol_count = sum(1 for r in rows if r["content"] and "lol" in r["content"].lower())
    caps_count = sum(
        1 for r in rows
        if r["content"] and len(r["content"]) >= 6 and r["content"] == r["content"].upper()
        and any(ch.isalpha() for ch in r["content"])
    )
    question_count = sum(1 for r in rows if r["content"] and "?" in r["content"])

    sample_messages = [r["content"] for r in rows if r["content"] and len(r["content"]) > 3][:5]

    return {
        "count": count,
        "username": username,
        "late_night_ratio": round(late_night_ratio, 2),
        "lol_count": lol_count,
        "caps_count": caps_count,
        "question_count": question_count,
        "sample_messages": sample_messages,
    }


def get_active_users(days: int = 7, min_messages: int = 5) -> list[dict]:
    """Users active enough in the window to be fair roast targets for the
    daily auto-post -- avoids picking someone who barely said anything."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT user_id, username, COUNT(*) as cnt
            FROM messages
            WHERE created_at >= ?
            GROUP BY user_id
            HAVING cnt >= ?
            """,
            (cutoff, min_messages),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_roasted(user_id: str):
    with _conn() as c:
        c.execute("INSERT INTO roast_log (user_id) VALUES (?)", (user_id,))


def recently_roasted_user_ids(days: int = 3) -> set:
    """So the daily auto-post doesn't hit the same person two days running."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute("SELECT user_id FROM roast_log WHERE roasted_at >= ?", (cutoff,)).fetchall()
    return {r["user_id"] for r in rows}


def set_config(key: str, value: str):
    with _conn() as c:
        c.execute(
            "INSERT INTO config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_config(key: str) -> str | None:
    with _conn() as c:
        row = c.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
