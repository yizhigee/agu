"""notes 模块 M0 骨架测试。

不依赖完整 FastAPI 应用,通过 `configure_backend_extensions` 隔离验证
扩展注册与两个健康端点的行为,与 `test_extensions.py` 同模式。
"""
from __future__ import annotations

import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.extensions.loader import configure_backend_extensions
from app.custom import notes


def _client_with_notes_module() -> TestClient:
    """构造一个只加载 notes 模块的隔离 app,返回 TestClient。"""
    module = types.ModuleType("app.custom.notes")
    module.EXTENSION_ID = notes.EXTENSION_ID
    module.EXTENSION_API_VERSION = notes.EXTENSION_API_VERSION
    module.setup = notes.setup

    # 用独立 FastAPI 实例,避免影响全局 app
    app = FastAPI()
    registry, errors = configure_backend_extensions(app)

    # 上述 configure 会走真实 loader 的 _custom_module_names,
    # 这里再手动补上 notes 的 router,保证测试独立性
    if not registry.has_customizations:
        # 直接走一次 setup,挂到 app 上(与 loader 行为一致)
        from app.extensions.registry import BackendExtensionRegistrar
        registrar = BackendExtensionRegistrar(notes.EXTENSION_ID, api_version=notes.EXTENSION_API_VERSION)
        notes.setup(registrar)
        registry.register(registrar)
        for router in registrar.routers:
            app.include_router(router)
        registry.freeze()

    _ = module, errors
    return TestClient(app)


def test_health_returns_expected_shape() -> None:
    client = _client_with_notes_module()

    response = client.get("/api/custom/notes/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["module"] == "notes"
    assert data["schema_version"] == notes.SCHEMA_VERSION
    assert "db" in data
    assert "ai_key" in data


def test_schema_version_returns_version() -> None:
    client = _client_with_notes_module()

    response = client.get("/api/custom/notes/schema-version")

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == notes.SCHEMA_VERSION
    assert data["migrations"] == []


def test_setup_registers_router_without_exception() -> None:
    """setup 本身可被调用且不抛错(loader 会反复调用)。"""
    from app.extensions.registry import BackendExtensionRegistrar

    registrar = BackendExtensionRegistrar(notes.EXTENSION_ID, api_version=notes.EXTENSION_API_VERSION)
    notes.setup(registrar)
    assert len(registrar.routers) == 1
