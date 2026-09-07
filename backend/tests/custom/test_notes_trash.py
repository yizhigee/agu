"""notes 模块回收站测试(软删 → 恢复 → 彻底删除)。

覆盖:
- list_notes?deleted=true 只返回已软删
- restore 恢复后 deleted_at 清空、回到正常列表
- DELETE ?hard=true 彻底删除后(deleted=true 也查不到)
- 边界:restore 不存在 / 未软删的 id → 404
"""
from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def fresh_db(monkeypatch: pytest.MonkeyPatch):
    tmpdir = Path(tempfile.mkdtemp(prefix="notes_trash_"))
    db_path = tmpdir / "notes.db"

    if "app.custom.notes_db" in sys.modules:
        importlib.reload(sys.modules["app.custom.notes_db"])
    if "app.custom.notes" in sys.modules:
        importlib.reload(sys.modules["app.custom.notes"])

    from app.custom import notes as notes_module
    from app.custom import notes_db

    def _factory() -> notes_db.NotesDB:
        return notes_db.NotesDB(db_path)

    monkeypatch.setattr(notes_module, "_get_db", _factory)
    return db_path


def _client(fresh_db: Path) -> TestClient:
    from app.custom import notes as notes_module

    fake = ModuleType("app.custom.notes")
    fake.EXTENSION_ID = notes_module.EXTENSION_ID
    fake.EXTENSION_API_VERSION = notes_module.EXTENSION_API_VERSION
    fake.setup = notes_module.setup
    fake.startup = notes_module.startup

    app = FastAPI()
    app.include_router(notes_module._build_router())
    return TestClient(app)


@pytest.fixture
def client(fresh_db: Path) -> TestClient:
    return _client(fresh_db)


def _create(client: TestClient, title: str, type_="idea") -> str:
    resp = client.post(
        "/api/custom/notes/notes",
        json={"type": type_, "title": title, "content": title + " body"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_soft_delete_then_list_in_trash(client):
    nid = _create(client, "待删笔记")
    # 软删
    resp = client.delete(f"/api/custom/notes/notes/{nid}")
    assert resp.status_code == 200
    assert resp.json()["hard"] is False

    # 正常列表看不到
    normal = client.get("/api/custom/notes/notes").json()["items"]
    assert all(n["id"] != nid for n in normal)

    # 回收站看得到,且 deleted_at 非空
    trash = client.get("/api/custom/notes/notes?deleted=true").json()["items"]
    assert any(n["id"] == nid and n["deleted_at"] for n in trash)


def test_restore_brings_back(client):
    nid = _create(client, "可恢复笔记")
    client.delete(f"/api/custom/notes/notes/{nid}")

    resp = client.post(f"/api/custom/notes/notes/{nid}/restore")
    assert resp.status_code == 200
    assert resp.json()["deleted_at"] is None

    normal = client.get("/api/custom/notes/notes").json()["items"]
    assert any(n["id"] == nid for n in normal)

    trash = client.get("/api/custom/notes/notes?deleted=true").json()["items"]
    assert all(n["id"] != nid for n in trash)


def test_hard_delete_removes_forever(client):
    nid = _create(client, "彻底删笔记")
    client.delete(f"/api/custom/notes/notes/{nid}")  # 先软删

    resp = client.delete(f"/api/custom/notes/notes/{nid}?hard=true")
    assert resp.status_code == 200
    assert resp.json()["hard"] is True

    # 正常列表和回收站都查不到
    normal = client.get("/api/custom/notes/notes").json()["items"]
    trash = client.get("/api/custom/notes/notes?deleted=true").json()["items"]
    assert all(n["id"] != nid for n in normal)
    assert all(n["id"] != nid for n in trash)


def test_restore_missing_returns_404(client):
    resp = client.post("/api/custom/notes/notes/does-not-exist/restore")
    assert resp.status_code == 404


def test_restore_not_deleted_returns_404(client):
    nid = _create(client, "没删的笔记")
    resp = client.post(f"/api/custom/notes/notes/{nid}/restore")
    assert resp.status_code == 404
