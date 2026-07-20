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
                message_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at)")
        # Migration: message_id was added after initial deploy -- existing
        # databases won't have it yet, since CREATE TABLE IF NOT EXISTS is
        # a no-op on a table that already exists.
        try:
            c.execute("ALTER TABLE messages ADD COLUMN message_id TEXT")
        except Exception:
            pass  # column already exists
        # Unique index enables dedupe: a /backfill run can be re-run safely,
        # and never double-counts a message already captured live. SQLite
        # allows multiple NULLs in a unique index, so old rows from before
        # this migration (no message_id) don't conflict with each other.
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_msgid ON messages(message_id)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Tracks each person's most recent lines (up to a few), so the
        # template picker can exclude ALL of them and never loop back to
        # a joke too soon. 'kind' separates roast lines from glaze lines
        # so the two features don't share/exhaust each other's pool.
        c.execute("""
            CREATE TABLE IF NOT EXISTS recent_roast_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                line TEXT,
                kind TEXT NOT NULL DEFAULT 'roast',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_recent_lines_user ON recent_roast_lines(user_id)")
        # Migration: kind was added after initial deploy.
        try:
            c.execute("ALTER TABLE recent_roast_lines ADD COLUMN kind TEXT NOT NULL DEFAULT 'roast'")
        except Exception:
            pass  # column already exists


def get_recent_lines(user_id: str, limit: int = 3, kind: str = "roast") -> list[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT line FROM recent_roast_lines WHERE user_id = ? AND kind = ? ORDER BY id DESC LIMIT ?",
            (user_id, kind, limit),
        ).fetchall()
    return [r["line"] for r in rows]


def record_roast_line(user_id: str, line: str, keep: int = 10, kind: str = "roast"):
    with _conn() as c:
        c.execute("INSERT INTO recent_roast_lines (user_id, line, kind) VALUES (?, ?, ?)", (user_id, line, kind))
        # Trim to the most recent `keep` rows for this user+kind so the
        # table doesn't grow unbounded over months of daily roasts/glazes.
        c.execute(
            """
            DELETE FROM recent_roast_lines
            WHERE user_id = ? AND kind = ? AND id NOT IN (
                SELECT id FROM recent_roast_lines WHERE user_id = ? AND kind = ? ORDER BY id DESC LIMIT ?
            )
            """,
            (user_id, kind, user_id, kind, keep),
        )


def get_compliment_candidates(user_id: str, display_name: str, limit: int = 200) -> list[dict]:
    """Messages from OTHER people that mention this person by @mention or
    name -- the raw candidate pool the glaze feature searches for real
    compliments. Filtering for actual positive language happens in
    glaze.py (keeps the SQL simple, keeps the keyword list easy to tune
    without touching storage). Returns {content, username} rows."""
    mention_a = f"%<@{user_id}>%"
    mention_b = f"%<@!{user_id}>%"
    name_pat = f"%{display_name}%"
    with _conn() as c:
        rows = c.execute(
            """
            SELECT content, username FROM messages
            WHERE user_id != ? AND (content LIKE ? OR content LIKE ? OR content LIKE ?)
            ORDER BY RANDOM() LIMIT ?
            """,
            (user_id, mention_a, mention_b, name_pat, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def record_message(user_id: str, username: str, content: str, hour_utc: int, message_id: str = None) -> bool:
    """Records a message. Returns True if it was newly inserted, False if
    this message_id was already recorded (e.g. a repeated /backfill run
    overlapping with live-tracked or previously-backfilled messages)."""
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO messages (user_id, username, content, hour_utc, message_id) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, content, hour_utc, message_id),
        )
        return cur.rowcount > 0


import re

_BARE_MENTION_RE = re.compile(r"^(<@!?\d+>|<#\d+>|<@&\d+>|\s)+$")
_URL_ONLY_RE = re.compile(r"^(https?://\S+|\s)+$")
_EMOJI_ONLY_RE = re.compile(r"^([\U0001F300-\U0001FAFF\u2600-\u27BF<:>\w]{0,2}|\s)*$")


def _is_real_content(content: str) -> bool:
    """Excludes flashback-unworthy messages: bare @mentions, pure links,
    or content so short/emoji-only it reads as nonsense when quoted back
    out of context (e.g. a message that's literally just '@Derb')."""
    stripped = content.strip()
    if not stripped:
        return False
    if _BARE_MENTION_RE.match(stripped):
        return False
    if _URL_ONLY_RE.match(stripped):
        return False
    # Require at least a few real word characters, not just punctuation/emoji shells
    word_chars = re.sub(r"[^\w]", "", stripped)
    if len(word_chars) < 6:
        return False
    return True


def get_random_message(user_id: str, min_length: int = 8) -> str | None:
    """Pulls one genuinely random REAL message from a person's FULL
    history -- no time window, could be from their first day in the
    server or three months ago. This is the 'flashback' material: real
    receipts, not a paraphrase. Filters out bare mentions/links/etc that
    would read as nonsense when quoted out of context (fixes: a flashback
    that just said 'he said \"@Derb\"' with no actual content)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT content FROM messages WHERE user_id = ? AND LENGTH(content) >= ? "
            "ORDER BY RANDOM() LIMIT 25",
            (user_id, min_length),
        ).fetchall()
    for row in rows:
        if _is_real_content(row["content"]):
            return row["content"]
    return None


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
