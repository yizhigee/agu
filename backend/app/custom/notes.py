"""notes 模块 — 智能记录与知识关联(M0 骨架)。

详见 `docs/.workbuddy/memory/EDD-notes-module.md`(项目长期记忆)。
本模块通过 `app.extensions` 的 L2 扩展契约接入,不修改核心代码。
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter

from app.extensions import (
    BACKEND_EXTENSION_API_VERSION,
    BackendExtensionRegistrar,
    ExtensionContext,
)
from app import secrets_store

logger = logging.getLogger(__name__)

EXTENSION_ID = "notes"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION

# 模块当前 schema 版本(供前端做迁移引导)
SCHEMA_VERSION = 1

# 数据目录名(相对于 context.data_dir)
DATA_SUBDIR = "notes"


def _data_dir(context: ExtensionContext) -> Path:
    """返回本模块独立的数据目录,负责创建。"""
    p = context.data_dir / DATA_SUBDIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def _check_ai_key_configured() -> bool:
    """复用 `secrets_store.get_ai_key`,不重新实现 Key 管理。"""
    try:
        key = secrets_store.get_ai_key()
    except Exception:  # noqa: BLE001
        return False
    return bool(key and key.strip())


def _build_router() -> APIRouter:
    router = APIRouter(prefix="/api/custom/notes", tags=["notes"])

    @router.get("/health")
    def health() -> dict:
        """模块健康检查。返回当前可用的子能力状态。"""
        return {
            "status": "ok",
            "module": EXTENSION_ID,
            "schema_version": SCHEMA_VERSION,
            "db": False,           # M1 才连 SQLite,这里先固定 False
            "ai_key": _check_ai_key_configured(),
        }

    @router.get("/schema-version")
    def schema_version() -> dict:
        """当前 schema 版本。前端据此做迁移引导。"""
        return {
            "version": SCHEMA_VERSION,
            "migrations": [],
        }

    return router


def setup(registrar: BackendExtensionRegistrar) -> None:
    """扩展注册。失败由 loader 捕获并 warn,不阻止主程序启动。"""
    registrar.include_router(_build_router())


def startup(context: ExtensionContext) -> None:
    """可选的启动钩子:确保数据目录存在。

    仅做最小 IO;失败记录日志,不抛出。
    """
    try:
        _data_dir(context)
        logger.info("notes module ready (data_dir=%s)", _data_dir(context))
    except Exception as exc:  # noqa: BLE001
        logger.warning("notes module startup failed: %s", exc)