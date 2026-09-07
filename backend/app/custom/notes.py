"""notes 模块 — 智能记录与知识关联(M0 骨架 + M1 CRUD)。

详见 `.workbuddy/memory/EDD-notes-module.md`。
本模块通过 `app.extensions` 的 L2 扩展契约接入,不修改核心代码。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.extensions import (
    BACKEND_EXTENSION_API_VERSION,
    BackendExtensionRegistrar,
    ExtensionContext,
)
from app.custom import notes_db
from app import secrets_store

logger = logging.getLogger(__name__)

EXTENSION_ID = "notes"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION

# 当前 schema 版本(由 notes_db 同步维护)
SCHEMA_VERSION = notes_db.SCHEMA_VERSION

DATA_SUBDIR = "notes"

# 进程级单例 + 锁
_db_singleton: Optional[notes_db.NotesDB] = None
_db_lock = threading.Lock()


# ---------- DB 单例 ----------

def _get_db() -> notes_db.NotesDB:
    global _db_singleton
    if _db_singleton is None:
        with _db_lock:
            if _db_singleton is None:
                # 从配置读 data_dir;若失败兜底到 ./data
                try:
                    from app.config import settings
                    base = settings.data_dir
                except Exception:  # noqa: BLE001
                    base = Path("./data").resolve()
                db_path = base / DATA_SUBDIR / "notes.db"
                _db_singleton = notes_db.NotesDB(db_path)
    return _db_singleton


def _data_dir(context: ExtensionContext) -> Path:
    p = context.data_dir / DATA_SUBDIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def _check_ai_key_configured() -> bool:
    try:
        key = secrets_store.get_ai_key()
    except Exception:  # noqa: BLE001
        return False
    return bool(key and key.strip())


# ---------- Pydantic 模型 ----------

class NoteCreate(BaseModel):
    type: str = Field(..., description="knowledge|pitfall|review|idea|question")
    content: str = Field(..., min_length=1)
    title: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    related_stocks: list[str] = Field(default_factory=list)
    source_url: Optional[str] = None
    source_app: Optional[str] = None
    mood: Optional[str] = None
    pnl: Optional[float] = None
    pinned: bool = False


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    related_stocks: Optional[list[str]] = None
    source_url: Optional[str] = None
    source_app: Optional[str] = None
    mood: Optional[str] = None
    pnl: Optional[float] = None
    read_status: Optional[str] = None
    next_review_at: Optional[str] = None
    pinned: Optional[bool] = None


class TagCreate(BaseModel):
    name: str = Field(..., min_length=1)
    color: Optional[str] = None


# ---------- 路由 ----------

def _build_router() -> APIRouter:
    router = APIRouter(prefix="/api/custom/notes", tags=["notes"])

    @router.get("/health")
    def health() -> dict:
        db_ok = False
        try:
            _get_db().list_notes(limit=1)
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
        return {
            "status": "ok",
            "module": EXTENSION_ID,
            "schema_version": SCHEMA_VERSION,
            "db": db_ok,
            "ai_key": _check_ai_key_configured(),
        }

    @router.get("/schema-version")
    def schema_version() -> dict:
        return {"version": SCHEMA_VERSION, "migrations": []}

    # ----- Notes CRUD -----

    @router.get("/notes")
    def list_notes(
        type: Optional[str] = None,
        tag: Optional[str] = None,
        pinned_only: bool = False,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        notes = _get_db().list_notes(
            type_filter=type,
            tag_filter=tag,
            pinned_only=pinned_only,
            search=search,
            limit=limit,
            offset=offset,
        )
        return {"items": notes, "count": len(notes)}

    @router.post("/notes", status_code=201)
    def create_note(body: NoteCreate) -> dict:
        try:
            note = _get_db().create_note(
                type_=body.type,
                content=body.content,
                title=body.title,
                tags=body.tags,
                related_stocks=body.related_stocks,
                source_url=body.source_url,
                source_app=body.source_app,
                mood=body.mood,
                pnl=body.pnl,
                pinned=body.pinned,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return note

    @router.get("/notes/{note_id}")
    def get_note(note_id: str) -> dict:
        note = _get_db().get_note(note_id)
        if not note:
            raise HTTPException(status_code=404, detail="note not found")
        return note

    @router.patch("/notes/{note_id}")
    def update_note(note_id: str, body: NoteUpdate) -> dict:
        patch: dict[str, Any] = {k: v for k, v in body.model_dump().items() if v is not None}
        note = _get_db().update_note(note_id, patch)
        if not note:
            raise HTTPException(status_code=404, detail="note not found")
        return note

    @router.delete("/notes/{note_id}")
    def delete_note(note_id: str, hard: bool = False) -> dict:
        ok = _get_db().delete_note(note_id, hard=hard)
        if not ok:
            raise HTTPException(status_code=404, detail="note not found or already deleted")
        return {"deleted": True, "hard": hard, "id": note_id}

    # ----- Tags CRUD(M1 仅 GET + POST;改/删留 v2.0)-----

    @router.get("/tags")
    def list_tags() -> dict:
        return {"items": _get_db().list_tags(), "count": len(_get_db().list_tags())}

    @router.post("/tags", status_code=201)
    def create_tag(body: TagCreate) -> dict:
        try:
            return _get_db().create_tag(body.name, body.color)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return router


# ---------- 注册入口 ----------

def setup(registrar: BackendExtensionRegistrar) -> None:
    registrar.include_router(_build_router())


def startup(context: ExtensionContext) -> None:
    """初始化数据目录 + DB(幂等,失败 fail-isolated)。"""
    try:
        _data_dir(context)
        _get_db()  # 触发首次连接 + 迁移
        logger.info("notes module ready (data_dir=%s)", _data_dir(context))
    except Exception as exc:  # noqa: BLE001
        logger.warning("notes module startup failed: %s", exc)