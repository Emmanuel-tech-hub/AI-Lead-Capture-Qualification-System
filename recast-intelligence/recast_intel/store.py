"""SQLite storage: articles, deduplication, triage results, sends and source health."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .sources import Article
from .textutil import similarity, title_fingerprint

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    publisher TEXT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    canonical TEXT NOT NULL,
    title_fp TEXT NOT NULL,
    published_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    summary TEXT,
    topics TEXT,
    duplicate_of TEXT,
    prefilter_score REAL DEFAULT 0,
    passed_prefilter INTEGER DEFAULT 0,
    triaged_at TEXT,
    score INTEGER,
    topic TEXT,
    breaking INTEGER DEFAULT 0,
    reason TEXT,
    sent_daily_at TEXT,
    sent_breaking_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_canonical ON items(canonical);
CREATE INDEX IF NOT EXISTS idx_items_fp ON items(title_fp);
CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at);
CREATE TABLE IF NOT EXISTS source_runs (
    source_id TEXT NOT NULL,
    ran_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    new_items INTEGER DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS sends (
    kind TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    local_date TEXT NOT NULL,
    subject TEXT,
    item_ids TEXT
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
"""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # ---------------------------------------------------------------- state
    def get_state(self, key: str, default: str | None = None) -> str | None:
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO state(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value))
        self.db.commit()

    # ---------------------------------------------------------------- articles
    def add_article(self, a: Article, prefilter_score: float, passed: bool) -> str:
        """Stores an article. Returns 'new', 'duplicate' (stored but linked to an earlier story) or 'seen'."""
        if self.db.execute("SELECT 1 FROM items WHERE id=?", (a.id,)).fetchone():
            return "seen"
        fp = title_fingerprint(a.title)
        week_ago = iso(now_utc() - timedelta(days=7))
        dup = self.db.execute(
            "SELECT id FROM items WHERE duplicate_of IS NULL AND (canonical=? OR title_fp=?) AND fetched_at>=? LIMIT 1",
            (a.canonical, fp, week_ago)).fetchone()
        if not dup:
            # Near-duplicate titles: the same story reported by different outlets.
            three_days = iso(now_utc() - timedelta(days=3))
            for row in self.db.execute(
                    "SELECT id, title FROM items WHERE duplicate_of IS NULL AND fetched_at>=?", (three_days,)):
                if similarity(row["title"], a.title) >= 0.7:
                    dup = row
                    break
        self.db.execute(
            """INSERT INTO items(id, source_id, source_name, kind, publisher, title, url, canonical, title_fp,
                                 published_at, fetched_at, summary, topics, duplicate_of, prefilter_score,
                                 passed_prefilter)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (a.id, a.source_id, a.source_name, a.kind, a.publisher, a.title, a.url, a.canonical, fp,
             iso(a.published_at), iso(now_utc()), a.summary, json.dumps(a.topics),
             dup["id"] if dup else None, prefilter_score, int(passed and not dup)))
        if dup:
            self._maybe_upgrade_primary(dup["id"], a)
        self.db.commit()
        return "duplicate" if dup else "new"

    def _maybe_upgrade_primary(self, primary_id: str, a: Article) -> None:
        """If an official announcement arrives after news coverage, make the official one the primary story."""
        primary = self.db.execute("SELECT kind, sent_daily_at FROM items WHERE id=?", (primary_id,)).fetchone()
        if primary and a.kind == "official" and primary["kind"] != "official" and not primary["sent_daily_at"]:
            self.db.execute("UPDATE items SET duplicate_of=NULL, passed_prefilter=1 WHERE id=?", (a.id,))
            self.db.execute("UPDATE items SET duplicate_of=? WHERE id=? OR duplicate_of=?", (a.id, primary_id, primary_id))
            self.db.execute("UPDATE items SET duplicate_of=NULL WHERE id=?", (a.id,))

    def untriaged(self, limit: int = 200) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM items WHERE passed_prefilter=1 AND duplicate_of IS NULL AND triaged_at IS NULL "
            "ORDER BY published_at DESC LIMIT ?", (limit,)).fetchall()

    def save_triage(self, item_id: str, score: int, topic: str, breaking: bool, reason: str) -> None:
        self.db.execute("UPDATE items SET triaged_at=?, score=?, topic=?, breaking=?, reason=? WHERE id=?",
                        (iso(now_utc()), int(score), topic, int(breaking), reason, item_id))
        self.db.commit()

    def candidates(self, min_score: int, since: datetime, exclude_sent_daily: bool = True) -> list[sqlite3.Row]:
        sql = ("SELECT * FROM items WHERE duplicate_of IS NULL AND triaged_at IS NOT NULL AND score>=? "
               "AND published_at>=?")
        if exclude_sent_daily:
            sql += " AND sent_daily_at IS NULL"
        return self.db.execute(sql + " ORDER BY score DESC, published_at DESC", (min_score, iso(since))).fetchall()

    def breaking_candidates(self, min_score: int, since: datetime) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM items WHERE duplicate_of IS NULL AND breaking=1 AND score>=? AND sent_breaking_at IS NULL "
            "AND sent_daily_at IS NULL AND published_at>=? ORDER BY score DESC", (min_score, iso(since))).fetchall()

    def also_covered_by(self, item_id: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT publisher, url FROM items WHERE duplicate_of=? ORDER BY kind", (item_id,)).fetchall()

    def mark_sent(self, item_ids: list[str], kind: str) -> None:
        col = "sent_daily_at" if kind == "daily" else "sent_breaking_at"
        self.db.executemany(f"UPDATE items SET {col}=? WHERE id=?", [(iso(now_utc()), i) for i in item_ids])
        self.db.commit()

    # ---------------------------------------------------------------- sends + source health
    def record_send(self, kind: str, local_date: str, subject: str, item_ids: list[str]) -> None:
        self.db.execute("INSERT INTO sends(kind, sent_at, local_date, subject, item_ids) VALUES(?,?,?,?,?)",
                        (kind, iso(now_utc()), local_date, subject, json.dumps(item_ids)))
        self.db.commit()

    def sends_on(self, kind: str, local_date: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM sends WHERE kind=? AND local_date=?", (kind, local_date)).fetchone()[0]

    def record_source_run(self, source_id: str, ok: bool, new_items: int = 0, error: str = "") -> None:
        self.db.execute("INSERT INTO source_runs(source_id, ran_at, ok, new_items, error) VALUES(?,?,?,?,?)",
                        (source_id, iso(now_utc()), int(ok), new_items, error[:500]))
        self.db.commit()

    def failing_sources(self, hours: int = 24) -> list[sqlite3.Row]:
        """Sources whose most recent run in the window failed."""
        since = iso(now_utc() - timedelta(hours=hours))
        return self.db.execute(
            """SELECT r.source_id, r.error, r.ran_at FROM source_runs r
               JOIN (SELECT source_id, MAX(ran_at) AS last FROM source_runs WHERE ran_at>=? GROUP BY source_id) m
                 ON r.source_id=m.source_id AND r.ran_at=m.last
               WHERE r.ok=0""", (since,)).fetchall()
