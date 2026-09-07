"""notes 模块 M1 CRUD 测试。

每个测试用临时目录构造独立 NotesDB,避免污染共享 DB。
通过 `configure_backend_extensions` 隔离验证路由注册与端点契约。
"""
from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def fresh_db(monkeypatch: pytest.MonkeyPatch):
    """重置 notes_db 模块 + 注入临时 DB 路径,每个 case 独立。"""
    tmpdir = Path(tempfile.mkdtemp(prefix="notes_test_"))
    db_path = tmpdir / "notes.db"

    # 重新加载 notes_db 拿干净模块
    if "app.custom.notes_db" in sys.modules:
        importlib.reload(sys.modules["app.custom.notes_db"])
    if "app.custom.notes" in sys.modules:
        importlib.reload(sys.modules["app.custom.notes"])

    # patch 单例 getter,让它直接用临时 db
    from app.custom import notes as notes_module
    from app.custom import notes_db

    def _factory() -> notes_db.NotesDB:
        return notes_db.NotesDB(db_path)

    monkeypatch.setattr(notes_module, "_get_db", _factory)
    return db_path


def _isolated_client(fresh_db: Path) -> TestClient:
    """构造一个只挂 notes 模块路由的 FastAPI,返回 TestClient。"""
    from app.custom import notes as notes_module

    # 把 notes 模块喂给 loader,避免真实 _custom_module_names 的副作用
    fake = ModuleType("app.custom.notes")
    fake.EXTENSION_ID = notes_module.EXTENSION_ID
    fake.EXTENSION_API_VERSION = notes_module.EXTENSION_API_VERSION
    fake.setup = notes_module.setup
    fake.startup = notes_module.startup

    app = FastAPI()
    # 直接挂 router,跳过 loader 的版本/冲突校验
    app.include_router(notes_module._build_router())
    return TestClient(app)


# ---------- M0 既有 ----------

def test_health_with_fresh_db(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    response = client.get("/api/custom/notes/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["db"] is True  # 此时 DB 可达


def test_schema_version(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    response = client.get("/api/custom/notes/schema-version")
    assert response.status_code == 200
    assert response.json()["version"] == 2  # M1 升到 v2


# ---------- Notes CRUD ----------

def test_create_note_minimal(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    response = client.post(
        "/api/custom/notes/notes",
        json={"type": "idea", "content": "今天看 MACD 顶背离觉得要跑"},
    )
    assert response.status_code == 201, response.text
    note = response.json()
    assert note["id"]
    assert note["type"] == "idea"
    assert note["content"] == "今天看 MACD 顶背离觉得要跑"
    assert note["tags"] == []
    assert note["pinned"] is False
    assert note["deleted_at"] is None


def test_create_note_with_tags_creates_tag_records(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    response = client.post(
        "/api/custom/notes/notes",
        json={
            "type": "knowledge",
            "title": "MACD 顶背离",
            "content": "DIF 高点比前高更低,价格高点比前高更高 → 顶背离",
            "tags": ["技术形态", "MACD", "技术形态"],  # 去重由 SQL UNIQUE 处理
        },
    )
    assert response.status_code == 201
    note = response.json()
    assert set(note["tags"]) == {"技术形态", "MACD"}

    # 标签字典应自动创建两条
    tags = client.get("/api/custom/notes/tags").json()["items"]
    assert {t["name"] for t in tags} == {"技术形态", "MACD"}


def test_create_note_rejects_invalid_type(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    response = client.post(
        "/api/custom/notes/notes",
        json={"type": "wrong", "content": "x"},
    )
    assert response.status_code == 400


def test_create_note_rejects_empty_content(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    response = client.post(
        "/api/custom/notes/notes",
        json={"type": "idea", "content": "   "},
    )
    assert response.status_code == 400


def test_list_notes_default_orders_by_pinned_then_recent(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    # 创建 3 条,中间一条 pinned
    for i, content in enumerate(["第一条", "第二条", "第三条"]):
        client.post("/api/custom/notes/notes", json={"type": "idea", "content": content})
    # 把第二条 pinned
    notes = client.get("/api/custom/notes/notes").json()["items"]
    assert len(notes) == 3
    second_id = notes[1]["id"]
    client.patch(f"/api/custom/notes/notes/{second_id}", json={"pinned": True})

    listed = client.get("/api/custom/notes/notes").json()["items"]
    assert listed[0]["id"] == second_id  # pinned 排第一
    assert listed[0]["pinned"] is True


def test_list_notes_excludes_deleted(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    a = client.post("/api/custom/notes/notes", json={"type": "idea", "content": "A"}).json()
    b = client.post("/api/custom/notes/notes", json={"type": "idea", "content": "B"}).json()
    client.delete(f"/api/custom/notes/notes/{a['id']}")

    listed = client.get("/api/custom/notes/notes").json()["items"]
    assert [n["id"] for n in listed] == [b["id"]]


def test_get_note_returns_full(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    created = client.post(
        "/api/custom/notes/notes",
        json={"type": "pitfall", "content": "追高被套", "tags": ["追高"]},
    ).json()
    response = client.get(f"/api/custom/notes/notes/{created['id']}")
    assert response.status_code == 200
    note = response.json()
    assert note["id"] == created["id"]
    assert "tag_ids" in note
    assert note["tags"] == ["追高"]


def test_get_note_404(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    response = client.get("/api/custom/notes/nonexistent")
    assert response.status_code == 404


def test_update_note_partial(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    created = client.post(
        "/api/custom/notes/notes",
        json={"type": "idea", "content": "原始内容", "tags": ["a"]},
    ).json()
    response = client.patch(
        f"/api/custom/notes/notes/{created['id']}",
        json={"content": "改后内容", "pinned": True, "tags": ["b", "c"]},
    )
    assert response.status_code == 200
    note = response.json()
    assert note["content"] == "改后内容"
    assert note["pinned"] is True
    assert set(note["tags"]) == {"b", "c"}


def test_update_note_404(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    response = client.patch(
        "/api/custom/notes/nonexistent",
        json={"content": "x"},
    )
    assert response.status_code == 404


def test_delete_note_soft(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    created = client.post(
        "/api/custom/notes/notes", json={"type": "idea", "content": "要删"}
    ).json()

    response = client.delete(f"/api/custom/notes/notes/{created['id']}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert response.json()["hard"] is False

    # 软删后 GET 不到
    assert client.get(f"/api/custom/notes/notes/{created['id']}").status_code == 404
    # 列表也不包含
    assert client.get("/api/custom/notes/notes").json()["count"] == 0


def test_delete_note_hard(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    created = client.post(
        "/api/custom/notes/notes", json={"type": "idea", "content": "要硬删"}
    ).json()

    response = client.delete(f"/api/custom/notes/notes/{created['id']}?hard=true")
    assert response.status_code == 200
    assert response.json()["hard"] is True


def test_delete_note_404_when_missing(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    response = client.delete("/api/custom/notes/nonexistent")
    assert response.status_code == 404


def test_list_notes_filter_by_type(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    client.post("/api/custom/notes/notes", json={"type": "knowledge", "content": "K"})
    client.post("/api/custom/notes/notes", json={"type": "pitfall", "content": "P"})

    listed = client.get("/api/custom/notes/notes?type=pitfall").json()["items"]
    assert len(listed) == 1
    assert listed[0]["type"] == "pitfall"


def test_list_notes_search(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    client.post("/api/custom/notes/notes", json={"type": "idea", "content": "今天看 MACD 顶背离"})
    client.post("/api/custom/notes/notes", json={"type": "idea", "content": "追高被套了"})

    listed = client.get("/api/custom/notes/notes?search=MACD").json()["items"]
    assert len(listed) == 1
    assert "MACD" in listed[0]["content"]


# ---------- Tags CRUD ----------

def test_create_tag(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    response = client.post("/api/custom/notes/tags", json={"name": "半导体"})
    assert response.status_code == 201
    assert response.json()["name"] == "半导体"


def test_create_tag_rejects_empty(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    response = client.post("/api/custom/notes/tags", json={"name": "  "})
    assert response.status_code == 400


def test_list_tags_orders_by_use_count(fresh_db: Path) -> None:
    client = _isolated_client(fresh_db)
    # 创建笔记带不同频次的标签
    client.post(
        "/api/custom/notes/notes",
        json={"type": "idea", "content": "1", "tags": ["半导体", "光模块"]},
    )
    client.post(
        "/api/custom/notes/notes",
        json={"type": "idea", "content": "2", "tags": ["半导体", "AI"]},
    )
    client.post(
        "/api/custom/notes/notes",
        json={"type": "idea", "content": "3", "tags": ["半导体"]},
    )
    listed = client.get("/api/custom/notes/tags").json()["items"]
    # use_count: 半导体=3, 光模块=AI=1
    assert listed[0]["name"] == "半导体"
    assert listed[0]["use_count"] == 3