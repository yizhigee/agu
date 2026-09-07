"""notes 模块 — 智能记录与知识关联(M0 骨架 + M1 CRUD + M2 AI 标签建议)。

详见 `.workbuddy/memory/EDD-notes-module.md`。
本模块通过 `app.extensions` 的 L2 扩展契约接入,不修改核心代码。
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
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


class SuggestTagsRequest(BaseModel):
    title: Optional[str] = None
    content: str = Field(..., min_length=1)
    existing_tags: list[str] = Field(default_factory=list)
    max_suggest: int = Field(default=8, ge=1, le=20)


class TagSuggestion(BaseModel):
    name: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: Optional[str] = None


class SuggestTagsResponse(BaseModel):
    suggested_type: Optional[str] = None
    suggested_type_confidence: Optional[float] = None
    tags: list[TagSuggestion] = Field(default_factory=list)
    model: Optional[str] = None
    latency_ms: int = 0


# ---------- AI 辅助 ----------

# 在 setup/startup 中初始化(失败兜底 None)
_AUDIT_LOG_PATH: Optional[Path] = None
_AUDIT_LOCK = threading.Lock()

VALID_TYPES = ("knowledge", "pitfall", "review", "idea", "question")


def _set_audit_log_path(path: Path) -> None:
    global _AUDIT_LOG_PATH
    _AUDIT_LOG_PATH = path


def _audit_ai_call(
    *,
    endpoint: str,
    status: str,
    latency_ms: int,
    error_code: Optional[str] = None,
    input_tokens_estimate: int = 0,
    output_tokens_estimate: int = 0,
    cited_note_count: int = 0,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """写一行 JSONL 到 ai_audit.log。

    仅统计(调用耗时/成败/token估算/引用条数),不记录用户原文/AI 答案。
    路径在 startup 时设置;失败静默,不让审计拖累主流程。
    """
    if _AUDIT_LOG_PATH is None:
        return
    record: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "endpoint": endpoint,
        "status": status,
        "latency_ms": latency_ms,
        "input_tokens_estimate": input_tokens_estimate,
        "output_tokens_estimate": output_tokens_estimate,
        "cited_note_count": cited_note_count,
    }
    if error_code is not None:
        record["error_code"] = error_code
    if extra:
        record.update(extra)
    try:
        with _AUDIT_LOCK:
            with _AUDIT_LOG_PATH.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.debug("audit log write failed: %s", exc)


# 提取 AI 返回文本中的 JSON 块(允许 ```json ... ``` 包裹,也允许裸 JSON)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL | re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json_object(text: str) -> Optional[dict[str, Any]]:
    """从 AI 输出文本中抽取首个 JSON object;容忍 markdown 包裹 / 多余文本。"""
    if not text:
        return None
    # 1) 优先匹配 ```json ... ``` 围栏
    m = _JSON_FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 2) 否则找首个 {...} 段(平衡括号检测)
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return None
    return None


def _normalize_suggestion(raw: dict[str, Any]) -> Optional[TagSuggestion]:
    name = str(raw.get("name") or raw.get("tag") or "").strip()
    if not name:
        return None
    # 长度上限 24 字,避免长尾
    name = name[:24].strip()
    if not name:
        return None
    try:
        conf = float(raw.get("confidence", raw.get("score", 0.6)))
    except (TypeError, ValueError):
        conf = 0.6
    conf = max(0.0, min(1.0, conf))
    reason = raw.get("reason") or raw.get("why") or None
    if reason is not None:
        reason = str(reason)[:200]
    return TagSuggestion(name=name, confidence=conf, reason=reason)


def _parse_ai_response(text: str, max_n: int) -> tuple[Optional[str], list[TagSuggestion]]:
    """解析 AI 输出:返回 (suggested_type, [TagSuggestion])。失败容错。"""
    obj = _extract_json_object(text)
    if not isinstance(obj, dict):
        return None, []
    st = obj.get("suggested_type") or obj.get("type")
    if st and st in VALID_TYPES:
        suggested_type: Optional[str] = st
    else:
        suggested_type = None
    raw_tags = obj.get("tags") or obj.get("suggestions") or []
    if not isinstance(raw_tags, list):
        return suggested_type, []
    out: list[TagSuggestion] = []
    seen: set[str] = set()
    for item in raw_tags:
        if isinstance(item, str):
            # 简短形式:["半导体", "止损"]
            s = _normalize_suggestion({"name": item, "confidence": 0.6})
        elif isinstance(item, dict):
            s = _normalize_suggestion(item)
        else:
            continue
        if s and s.name not in seen:
            seen.add(s.name)
            out.append(s)
        if len(out) >= max_n:
            break
    return suggested_type, out


def _build_suggest_tags_prompt(req: SuggestTagsRequest) -> list[dict[str, str]]:
    title = (req.title or "").strip()
    content = req.content.strip()
    existing = ", ".join(req.existing_tags) if req.existing_tags else "(无)"

    system = (
        "你是 A 股散户的笔记整理助手。任务:根据笔记标题与正文,推荐合适的标签与笔记类型。\n"
        "只输出严格 JSON,不要任何解释、不要 markdown 围栏以外的内容。\n"
        f"笔记类型只能是以下 5 种之一:{'/'.join(VALID_TYPES)}\n"
        "标签要求:2-6 字中文短语,粒度参考「半导体/止损/财报/技术形态/政策」等业务标签,最多"
        f"{req.max_suggest} 个,不要包含已经存在的标签(见下),不要编造股票代码。\n"
        "每个标签附带 0-1 的 confidence(越相关越高)与一句 ≤30 字的理由。\n"
        "如果正文内容太短无法判断,返回空 tags 数组,suggested_type 留空。"
    )
    user = (
        f"标题: {title or '(无)'}\n"
        f"正文: {content}\n"
        f"已有标签: {existing}\n\n"
        "输出 schema:\n"
        "{\n"
        '  "suggested_type": "knowledge|pitfall|review|idea|question|null",\n'
        '  "suggested_type_confidence": 0.0-1.0,\n'
        '  "tags": [\n'
        '    {"name": "标签名", "confidence": 0.0-1.0, "reason": "简短理由"}\n'
        "  ]\n"
        "}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


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

    # ----- AI 能力 (M2) -----

    @router.post("/ai/suggest-tags")
    async def ai_suggest_tags(body: SuggestTagsRequest) -> SuggestTagsResponse:
        if not _check_ai_key_configured():
            _audit_ai_call(
                endpoint="suggest_tags",
                status="error",
                latency_ms=0,
                error_code="ai_key_missing",
            )
            raise HTTPException(
                status_code=400,
                detail="AI Key 未配置,请在设置页配置后重试",
            )

        # 延迟导入:不在启动时绑死 AI provider,允许模块独立测试
        from app.services.ai_provider import generate_ai_text, current_ai_model

        messages = _build_suggest_tags_prompt(body)
        # 输入 token 估算(中文 1 字 1 token,其它 4 字符 1 token)
        input_est = sum(
            (len(m["content"]) // 4) + 1
            for m in messages
        )

        start = time.monotonic()
        status = "success"
        error_code: Optional[str] = None
        text = ""
        try:
            text = await generate_ai_text(
                messages,
                temperature=0.3,
                max_tokens=600,
                timeout=60.0,
            )
        except Exception as exc:  # noqa: BLE001
            status = "error"
            error_code = exc.__class__.__name__
            latency = int((time.monotonic() - start) * 1000)
            _audit_ai_call(
                endpoint="suggest_tags",
                status=status,
                latency_ms=latency,
                error_code=error_code,
                input_tokens_estimate=input_est,
            )
            raise HTTPException(
                status_code=502,
                detail=f"AI 服务调用失败: {exc}",
            ) from exc
        latency = int((time.monotonic() - start) * 1000)
        output_est = max(1, len(text) // 4)

        suggested_type, tags = _parse_ai_response(text, body.max_suggest)
        # 过滤掉已存在的标签(避免重复)
        existing = {t.strip().lower() for t in body.existing_tags if t.strip()}
        tags = [t for t in tags if t.name.lower() not in existing]

        _audit_ai_call(
            endpoint="suggest_tags",
            status=status,
            latency_ms=latency,
            error_code=error_code,
            input_tokens_estimate=input_est,
            output_tokens_estimate=output_est,
            cited_note_count=0,
            extra={"tag_count": len(tags)},
        )
        return SuggestTagsResponse(
            suggested_type=suggested_type,
            suggested_type_confidence=None,
            tags=tags,
            model=current_ai_model(),
            latency_ms=latency,
        )

    return router


# ---------- 注册入口 ----------

def setup(registrar: BackendExtensionRegistrar) -> None:
    registrar.include_router(_build_router())


def startup(context: ExtensionContext) -> None:
    """初始化数据目录 + DB(幂等,失败 fail-isolated)。"""
    try:
        data_dir = _data_dir(context)
        _set_audit_log_path(data_dir / "ai_audit.log")
        _get_db()  # 触发首次连接 + 迁移
        logger.info("notes module ready (data_dir=%s)", data_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notes module startup failed: %s", exc)