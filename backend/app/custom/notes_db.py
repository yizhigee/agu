"""notes 模块 — SQLite 数据层。

负责:
- 单一连接(per-process,线程安全用 check_same_thread=False + 自维护 lock)
- schema 迁移(版本号 + 幂等 ALTER/CREATE)
- 笔记/标签的 CRUD 业务(参数化 SQL,杜绝注入)

设计要点:
- 软删除(`deleted_at`):保留 30 天,M2+ 加硬删 UI
- 所有业务表带 `user_id`,本期恒为 "local",为多用户扩展铺路
- JSON 字段存 tags/related_stocks 等小数组(避免 note_tags 多对多爆炸)
- notes ↔ tags 多对多仍用 note_tags 表(标签查询性能)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

CURRENT_USER = "local"  # 预留多用户:本期恒为 "local"

# 当前 schema 版本(写到 meta 表)
SCHEMA_VERSION = 2  # M1:notes/tags/note_tags/meta 四表 + 软删


# ---------- 时间戳工具 ----------

def _now_iso() -> str:
    """UTC ISO8601,带时区。"""
    return datetime.now(timezone.utc).isoformat()


def _gen_id() -> str:
    return uuid.uuid4().hex


# ---------- 连接管理 ----------

class NotesDB:
    """SQLite 连接单例(进程内)+ 迁移管理。

    线程安全:sqlite3 默认一个连接只允许创建它的线程使用,本类用
    `check_same_thread=False` 开启跨线程,但通过 `self._lock` 串行化
    写操作,读操作走事务快照。
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_dir()
        self._conn = self._open()
        self._migrate()

    def _ensure_dir(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit,我们显式 BEGIN/COMMIT
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            assert self._conn is not None
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            assert self._conn is not None
            return self._conn.execute(sql, params)

    def executemany(self, sql: str, params_seq: list[tuple]) -> sqlite3.Cursor:
        with self._lock:
            assert self._conn is not None
            return self._conn.executemany(sql, params_seq)

    # ---------- 迁移 ----------

    def _migrate(self) -> None:
        """幂等迁移。schema_version 单调递增。"""
        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            current = int(row["value"]) if row else 0

            if current < 1:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notes (
                        id              TEXT PRIMARY KEY,
                        user_id         TEXT NOT NULL DEFAULT 'local',
                        type            TEXT NOT NULL,
                        title           TEXT,
                        content         TEXT NOT NULL,
                        tags            TEXT NOT NULL DEFAULT '[]',
                        related_stocks  TEXT NOT NULL DEFAULT '[]',
                        source_url      TEXT,
                        source_app      TEXT,
                        mood            TEXT,
                        pnl             REAL,
                        pitfall_meta    TEXT,
                        knowledge_meta  TEXT,
                        read_status     TEXT NOT NULL DEFAULT 'unread',
                        next_review_at  TEXT,
                        pinned          INTEGER NOT NULL DEFAULT 0,
                        parent_note_id  TEXT,
                        derived_rule_id TEXT,
                        created_at      TEXT NOT NULL,
                        updated_at      TEXT NOT NULL,
                        deleted_at      TEXT
                    )
                    """
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_notes_user_type ON notes(user_id, type)"
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_notes_user_created ON notes(user_id, created_at DESC)"
                )

            if current < 2:
                # v2 = 当前 M1:加 tags / note_tags / 软删索引
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tags (
                        id          TEXT PRIMARY KEY,
                        user_id     TEXT NOT NULL DEFAULT 'local',
                        name        TEXT NOT NULL,
                        color       TEXT,
                        parent_id   TEXT,
                        use_count   INTEGER NOT NULL DEFAULT 0,
                        merged_into TEXT,
                        created_at  TEXT NOT NULL,
                        UNIQUE(user_id, name)
                    )
                    """
                )
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS note_tags (
                        note_id TEXT NOT NULL,
                        tag_id  TEXT NOT NULL,
                        PRIMARY KEY (note_id, tag_id),
                        FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
                        FOREIGN KEY (tag_id)  REFERENCES tags(id)  ON DELETE CASCADE
                    )
                    """
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_notes_user_pinned ON notes(user_id, pinned, created_at DESC)"
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_notes_parent ON notes(parent_note_id)"
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_notes_deleted ON notes(user_id, deleted_at)"
                )

            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('last_migration_at', ?)",
                (_now_iso(),),
            )

    # ---------- Notes CRUD ----------

    def list_notes(
        self,
        *,
        type_filter: Optional[str] = None,
        tag_filter: Optional[str] = None,
        pinned_only: bool = False,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM notes WHERE user_id = ? AND deleted_at IS NULL"
        params: list[Any] = [CURRENT_USER]
        if type_filter:
            sql += " AND type = ?"
            params.append(type_filter)
        if pinned_only:
            sql += " AND pinned = 1"
        if search:
            sql += " AND (title LIKE ? OR content LIKE ?)"
            like = f"%{search}%"
            params.extend([like, like])
        sql += " ORDER BY pinned DESC, created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self.execute(sql, tuple(params)).fetchall()
        if tag_filter:
            # 后过滤(标签 N:N 走 IN 比 EXISTS 简单)
            tag_ids = self.execute(
                "SELECT id FROM tags WHERE user_id = ? AND name = ?",
                (CURRENT_USER, tag_filter),
            ).fetchall()
            if not tag_ids:
                return []
            tag_id_set = {r["id"] for r in tag_ids}
            ids = self.execute(
                "SELECT note_id FROM note_tags WHERE tag_id IN ({})".format(
                    ",".join("?" * len(tag_id_set))
                ),
                tuple(tag_id_set),
            ).fetchall()
            note_ids = {r["note_id"] for r in ids}
            rows = [r for r in rows if r["id"] in note_ids]
        return [_row_to_note(r) for r in rows]

    def get_note(self, note_id: str) -> Optional[dict[str, Any]]:
        row = self.execute(
            "SELECT * FROM notes WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
            (note_id, CURRENT_USER),
        ).fetchone()
        if not row:
            return None
        note = _row_to_note(row)
        note["tag_ids"] = [r["tag_id"] for r in self.execute(
            "SELECT tag_id FROM note_tags WHERE note_id = ?", (note_id,)
        ).fetchall()]
        return note

    def create_note(
        self,
        *,
        type_: str,
        content: str,
        title: Optional[str] = None,
        tags: Optional[list[str]] = None,
        related_stocks: Optional[list[str]] = None,
        source_url: Optional[str] = None,
        source_app: Optional[str] = None,
        mood: Optional[str] = None,
        pnl: Optional[float] = None,
        pinned: bool = False,
    ) -> dict[str, Any]:
        if type_ not in {"knowledge", "pitfall", "review", "idea", "question"}:
            raise ValueError(f"invalid note type: {type_}")
        if not content or not content.strip():
            raise ValueError("content is required")
        note_id = _gen_id()
        now = _now_iso()
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO notes(
                    id, user_id, type, title, content, tags, related_stocks,
                    source_url, source_app, mood, pnl, pinned,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    note_id, CURRENT_USER, type_, title, content,
                    json.dumps(tags or [], ensure_ascii=False),
                    json.dumps(related_stocks or [], ensure_ascii=False),
                    source_url, source_app, mood, pnl,
                    1 if pinned else 0,
                    now, now,
                ),
            )
            if tags:
                tag_ids = self._upsert_tags(tags)
                conn.executemany(
                    "INSERT OR IGNORE INTO note_tags(note_id, tag_id) VALUES (?, ?)",
                    [(note_id, tid) for tid in tag_ids],
                )
        result = self.get_note(note_id)
        assert result is not None
        return result

    def update_note(self, note_id: str, patch: dict[str, Any]) -> Optional[dict[str, Any]]:
        """部分更新。tags 字段特殊处理:替换为新集合。"""
        existing = self.get_note(note_id)
        if not existing:
            return None
        fields: list[str] = []
        params: list[Any] = []
        for key in (
            "title", "content", "source_url", "source_app", "mood",
            "pnl", "read_status", "next_review_at", "pinned",
        ):
            if key in patch:
                val = patch[key]
                if key == "pinned":
                    val = 1 if val else 0
                fields.append(f"{key} = ?")
                params.append(val)
        if "tags" in patch:
            fields.append("tags = ?")
            params.append(json.dumps(patch["tags"] or [], ensure_ascii=False))
        if "related_stocks" in patch:
            fields.append("related_stocks = ?")
            params.append(json.dumps(patch["related_stocks"] or [], ensure_ascii=False))
        fields.append("updated_at = ?")
        params.append(_now_iso())
        params.append(note_id)
        with self._tx() as conn:
            conn.execute(
                f"UPDATE notes SET {', '.join(fields)} WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                tuple(params + [CURRENT_USER]),
            )
            if "tags" in patch:
                conn.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
                tag_ids = self._upsert_tags(patch["tags"] or [])
                conn.executemany(
                    "INSERT OR IGNORE INTO note_tags(note_id, tag_id) VALUES (?, ?)",
                    [(note_id, tid) for tid in tag_ids],
                )
        return self.get_note(note_id)

    def delete_note(self, note_id: str, *, hard: bool = False) -> bool:
        """软删为主;hard=True 真删(M2+ 硬删 UI 用)。"""
        with self._tx() as conn:
            if hard:
                cur = conn.execute(
                    "DELETE FROM notes WHERE id = ? AND user_id = ?",
                    (note_id, CURRENT_USER),
                )
            else:
                cur = conn.execute(
                    "UPDATE notes SET deleted_at = ?, updated_at = ? "
                    "WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                    (_now_iso(), _now_iso(), note_id, CURRENT_USER),
                )
            return cur.rowcount > 0

    # ---------- Tags CRUD ----------

    def list_tags(self) -> list[dict[str, Any]]:
        rows = self.execute(
            "SELECT * FROM tags WHERE user_id = ? ORDER BY use_count DESC, name ASC",
            (CURRENT_USER,),
        ).fetchall()
        return [_row_to_tag(r) for r in rows]

    def _upsert_tags(self, names: list[str]) -> list[str]:
        """创建/返回已存在的标签 id 列表,顺带 +1 use_count。"""
        ids: list[str] = []
        for raw_name in names:
            name = (raw_name or "").strip()
            if not name:
                continue
            row = self.execute(
                "SELECT id FROM tags WHERE user_id = ? AND name = ?",
                (CURRENT_USER, name),
            ).fetchone()
            if row:
                tag_id = row["id"]
            else:
                tag_id = _gen_id()
                self.execute(
                    "INSERT INTO tags(id, user_id, name, created_at) VALUES (?,?,?,?)",
                    (tag_id, CURRENT_USER, name, _now_iso()),
                )
            self.execute(
                "UPDATE tags SET use_count = use_count + 1 WHERE id = ?", (tag_id,)
            )
            ids.append(tag_id)
        return ids

    def create_tag(self, name: str, color: Optional[str] = None) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("tag name is required")
        tag_id = _gen_id()
        with self._tx() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO tags(id, user_id, name, color, created_at) VALUES (?,?,?,?,?)",
                (tag_id, CURRENT_USER, name, color, _now_iso()),
            )
            row = conn.execute(
                "SELECT id FROM tags WHERE user_id = ? AND name = ?",
                (CURRENT_USER, name),
            ).fetchone()
            assert row is not None
            tag_id = row["id"]
        tags = self.list_tags()
        return next(t for t in tags if t["id"] == tag_id)


# ---------- 行 → dict ----------

def _row_to_note(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["tags"] = json.loads(d.get("tags") or "[]")
    d["related_stocks"] = json.loads(d.get("related_stocks") or "[]")
    d["pinned"] = bool(d.get("pinned"))
    return d


def _row_to_tag(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)