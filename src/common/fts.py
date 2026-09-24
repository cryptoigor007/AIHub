"""Простой FTS по заголовкам/проектам/истории (SQLite FTS5 если доступен, иначе LIKE)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from .config import get_settings
from .logging import get_logger

log = get_logger(__name__)


class FTSIndex:
    def __init__(self) -> None:
        self._path = get_settings().data_dir / "fts.db"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        # FTS5 может быть недоступен — fallback на обычную таблицу
        try:
            cur.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS agents_fts USING fts5(
                    id UNINDEXED,
                    title,
                    project,
                    last_step,
                    body,
                    tokenize = 'unicode61'
                )
                """
            )
            self._mode = "fts5"
        except sqlite3.OperationalError:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS agents_fts (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    project TEXT,
                    last_step TEXT,
                    body TEXT
                )
                """
            )
            self._mode = "like"
        self._conn.commit()
        log.info("fts_ready", mode=self._mode)

    def upsert(
        self,
        agent_id: str,
        title: str = "",
        project: str = "",
        last_step: str = "",
        body: str = "",
    ) -> None:
        cur = self._conn.cursor()
        if self._mode == "fts5":
            cur.execute("DELETE FROM agents_fts WHERE id = ?", (agent_id,))
            cur.execute(
                "INSERT INTO agents_fts(id, title, project, last_step, body) VALUES (?,?,?,?,?)",
                (agent_id, title or "", project or "", last_step or "", body or ""),
            )
        else:
            cur.execute(
                """
                INSERT INTO agents_fts(id, title, project, last_step, body)
                VALUES (?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    project=excluded.project,
                    last_step=excluded.last_step,
                    body=excluded.body
                """,
                (agent_id, title or "", project or "", last_step or "", body or ""),
            )
        self._conn.commit()

    def search(self, query: str, limit: int = 50) -> list[str]:
        if not query or not query.strip():
            return []
        q = query.strip()
        cur = self._conn.cursor()
        try:
            if self._mode == "fts5":
                # Экранируем спецсимволы FTS грубо
                safe = q.replace('"', '""')
                cur.execute(
                    "SELECT id FROM agents_fts WHERE agents_fts MATCH ? LIMIT ?",
                    (safe, limit),
                )
            else:
                like = f"%{q}%"
                cur.execute(
                    """
                    SELECT id FROM agents_fts
                    WHERE title LIKE ? OR project LIKE ? OR last_step LIKE ? OR body LIKE ?
                    LIMIT ?
                    """,
                    (like, like, like, like, limit),
                )
            return [row[0] for row in cur.fetchall()]
        except Exception as e:
            log.warning("fts_search_error", error=str(e))
            return []

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


_fts: Optional[FTSIndex] = None


def get_fts() -> FTSIndex:
    global _fts
    if _fts is None:
        _fts = FTSIndex()
    return _fts
