"""M3 模式检测 + 规则 CRUD + AI 规则草稿测试。

不依赖真实 AI:monkey-patch `generate_ai_text`。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.custom import notes as notes_module
from app.custom import notes_db


@pytest.fixture
def db():
    tmp = Path(tempfile.mkdtemp())
    return notes_db.NotesDB(tmp / "notes.db")


@pytest.fixture
def client(db):
    audit = Path(tempfile.mkdtemp()) / "ai_audit.log"
    notes_module._db_singleton = db
    notes_module._AUDIT_LOG_PATH = audit
    app = FastAPI()
    app.include_router(notes_module._build_router())
    return TestClient(app)


# ---------- 模式检测 ----------

def _seed_notes(db: notes_db.NotesDB) -> None:
    """种 6 条 pitfall(共享 tag '追高') + 3 条 knowledge + 2 条 idea。"""
    pitfall_ids = []
    for i in range(6):
        nid = db.create_note(
            type_="pitfall",
            content=f"追高被套第{i+1}次,明天还要割肉",
            title=f"追高坑{i+1}",
            tags=["追高", "止损"],
        )["id"]
        pitfall_ids.append(nid)
    for i in range(3):
        db.create_note(
            type_="knowledge",
            content=f"学到 MACD 顶背离知识{i+1}",
            title=f"MACD{i+1}",
            tags=["技术形态"],
        )
    for i in range(2):
        db.create_note(
            type_="idea",
            content=f"看多某个板块的想法{i+1}",
            title=None,
            tags=["板块"],
        )


def test_detect_patterns_finds_tag_cluster(client, db):
    _seed_notes(db)
    resp = client.get("/api/custom/notes/patterns/detect?min_count=3&limit=10")
    assert resp.status_code == 200
    body = resp.json()
    patterns = body["patterns"]
    # tag 聚类应能找到 "type=pitfall, tag=追高" (count=6)
    tag_pitfall = next(
        (p for p in patterns if p["type"] == "pitfall" and p["tag"] == "追高"),
        None,
    )
    assert tag_pitfall is not None
    assert tag_pitfall["note_count"] == 6
    assert len(tag_pitfall["sample_note_ids"]) >= 1
    assert len(tag_pitfall["sample_titles"]) >= 1
    # 纯 type 聚合:pitfall=6 也应命中 (>= min_count*2=6)
    type_pitfall = next(
        (p for p in patterns if p["type"] == "pitfall" and p["tag"] is None),
        None,
    )
    assert type_pitfall is not None
    assert type_pitfall["note_count"] == 6


def test_detect_patterns_min_count_threshold(client, db):
    _seed_notes(db)
    # min_count=10 → 任何聚类都不足
    resp = client.get("/api/custom/notes/patterns/detect?min_count=10")
    assert resp.status_code == 200
    assert resp.json()["patterns"] == []


def test_detect_patterns_excludes_soft_deleted(client, db):
    _seed_notes(db)
    # 删掉所有 pitfall
    notes = db.list_notes(type_filter="pitfall")
    for n in notes:
        db.delete_note(n["id"], hard=True)
    resp = client.get("/api/custom/notes/patterns/detect?min_count=3")
    body = resp.json()
    # 不应再找到 pitfall 聚类
    assert all(p["type"] != "pitfall" for p in body["patterns"])


def test_detect_patterns_empty_db(client):
    resp = client.get("/api/custom/notes/patterns/detect")
    assert resp.status_code == 200
    assert resp.json()["patterns"] == []


# ---------- Rules CRUD ----------

def test_rules_crud_basic(client):
    # create
    resp = client.post(
        "/api/custom/notes/rules",
        json={
            "category": "止损",
            "title": "高位追涨后必须次日设止损",
            "trigger_conditions": ["当日涨幅 > 7%", "买在分时高位"],
            "exceptions": "一字板除外",
            "source_note_ids": ["a1", "a2"],
        },
    )
    assert resp.status_code == 201
    rule = resp.json()
    assert rule["id"]
    assert rule["category"] == "止损"
    assert rule["status"] == "active"
    assert rule["violation_count"] == 0

    # list
    resp = client.get("/api/custom/notes/rules")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1

    # get
    resp = client.get(f"/api/custom/notes/rules/{rule['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "高位追涨后必须次日设止损"

    # patch
    resp = client.patch(
        f"/api/custom/notes/rules/{rule['id']}",
        json={"status": "archived"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "archived"
    # violation_count 由系统自动维护,不在 PATCH 范围

    # delete
    resp = client.delete(f"/api/custom/notes/rules/{rule['id']}")
    assert resp.status_code == 200
    resp = client.get(f"/api/custom/notes/rules/{rule['id']}")
    assert resp.status_code == 404


def test_rules_create_validation(client):
    # pydantic min_length=1 校验先于业务校验 → 422
    resp = client.post(
        "/api/custom/notes/rules",
        json={"category": "", "title": "x"},
    )
    assert resp.status_code == 422


def test_rules_patch_404(client):
    resp = client.patch("/api/custom/notes/rules/nonexistent", json={"title": "x"})
    assert resp.status_code == 404


def test_rules_list_filter_by_status(client):
    client.post(
        "/api/custom/notes/rules",
        json={"category": "a", "title": "active rule"},
    )
    client.post(
        "/api/custom/notes/rules",
        json={"category": "a", "title": "draft rule", "status": "draft"},
    )
    resp = client.get("/api/custom/notes/rules?status=active")
    assert resp.json()["count"] == 1
    resp = client.get("/api/custom/notes/rules?status=draft")
    assert resp.json()["count"] == 1


# ---------- AI 规则草稿 ----------

def test_draft_rule_ai_key_missing(client, db):
    note_id = db.create_note(
        type_="pitfall", content="追高被套", tags=["追高"],
    )["id"]
    with patch.object(notes_module, "_check_ai_key_configured", return_value=False):
        resp = client.post(
            "/api/custom/notes/ai/draft-rule",
            json={"note_ids": [note_id]},
        )
    assert resp.status_code == 400


def test_draft_rule_happy_path(client, db):
    notes = []
    for i in range(3):
        nid = db.create_note(
            type_="pitfall",
            content=f"追高买入次日被套{i+1}",
            title=f"追高{i+1}",
            tags=["追高", "止损"],
        )["id"]
        notes.append(nid)
    payload = {
        "category": "止损",
        "title": "高位追涨次日必须设止损",
        "trigger_conditions": ["买入当日涨幅 > 5%", "次日开盘价 < 买入价"],
        "exceptions": "封板一字板除外",
        "rationale": "3 条笔记均反映追高被套,统一规律是次日设止损。",
    }
    ai_text = json.dumps(payload, ensure_ascii=False)
    with patch.object(notes_module, "_check_ai_key_configured", return_value=True), \
         patch("app.services.ai_provider.generate_ai_text", new=AsyncMock(return_value=ai_text)):
        resp = client.post(
            "/api/custom/notes/ai/draft-rule",
            json={"note_ids": notes, "category_hint": "止损"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "高位追涨次日必须设止损"
    assert body["category"] == "止损"
    assert len(body["trigger_conditions"]) == 2
    assert body["exceptions"] == "封板一字板除外"
    assert body["rationale"]


def test_draft_rule_ai_returns_no_pattern(client, db):
    """AI 认为笔记间没共同模式:422 + 明确错误。"""
    nid = db.create_note(
        type_="idea", content="随便一条想法", tags=["闲聊"],
    )["id"]
    ai_text = json.dumps({
        "category": "复盘",
        "title": "暂无可提炼的规则",
        "trigger_conditions": [],
        "exceptions": None,
        "rationale": "笔记之间没有共同模式",
    }, ensure_ascii=False)
    with patch.object(notes_module, "_check_ai_key_configured", return_value=True), \
         patch("app.services.ai_provider.generate_ai_text", new=AsyncMock(return_value=ai_text)):
        resp = client.post(
            "/api/custom/notes/ai/draft-rule",
            json={"note_ids": [nid]},
        )
    assert resp.status_code == 422


def test_draft_rule_ai_returns_non_json(client, db):
    nid = db.create_note(
        type_="pitfall", content="x", tags=["追高"],
    )["id"]
    with patch.object(notes_module, "_check_ai_key_configured", return_value=True), \
         patch("app.services.ai_provider.generate_ai_text", new=AsyncMock(return_value="随便说两句")):
        resp = client.post(
            "/api/custom/notes/ai/draft-rule",
            json={"note_ids": [nid]},
        )
    assert resp.status_code == 502


def test_draft_rule_ai_error(client, db):
    nid = db.create_note(
        type_="pitfall", content="x",
    )["id"]
    with patch.object(notes_module, "_check_ai_key_configured", return_value=True), \
         patch("app.services.ai_provider.generate_ai_text", new=AsyncMock(side_effect=RuntimeError("net"))):
        resp = client.post(
            "/api/custom/notes/ai/draft-rule",
            json={"note_ids": [nid]},
        )
    assert resp.status_code == 502


def test_draft_rule_empty_notes(client):
    resp = client.post(
        "/api/custom/notes/ai/draft-rule",
        json={"note_ids": []},
    )
    assert resp.status_code == 422


def test_draft_rule_no_existing_notes(client):
    """note_ids 全部不存在:400。"""
    with patch.object(notes_module, "_check_ai_key_configured", return_value=True):
        resp = client.post(
            "/api/custom/notes/ai/draft-rule",
            json={"note_ids": ["nonexistent1", "nonexistent2"]},
        )
    assert resp.status_code == 400


# ---------- 端到端: detect → draft → 采纳为 rule ----------

def test_e2e_detect_draft_adopt(client, db):
    _seed_notes(db)
    # 1) 检测模式
    resp = client.get("/api/custom/notes/patterns/detect?min_count=3")
    patterns = resp.json()["patterns"]
    tag_pitfall = next(
        p for p in patterns if p["type"] == "pitfall" and p["tag"] == "追高"
    )
    assert tag_pitfall["note_count"] >= 3

    # 2) AI 草稿
    ai_text = json.dumps({
        "category": "止损",
        "title": "追高被套后必须次日设止损",
        "trigger_conditions": ["当日涨幅 > 5%", "次日开盘低于买入价"],
        "exceptions": None,
        "rationale": "多条追高笔记支撑。",
    }, ensure_ascii=False)
    with patch.object(notes_module, "_check_ai_key_configured", return_value=True), \
         patch("app.services.ai_provider.generate_ai_text", new=AsyncMock(return_value=ai_text)):
        resp = client.post(
            "/api/custom/notes/ai/draft-rule",
            json={
                "note_ids": tag_pitfall["sample_note_ids"],
                "category_hint": "止损",
            },
        )
    assert resp.status_code == 200
    draft = resp.json()

    # 3) 用户采纳为正式规则
    resp = client.post(
        "/api/custom/notes/rules",
        json={
            "category": draft["category"],
            "title": draft["title"],
            "trigger_conditions": draft["trigger_conditions"],
            "exceptions": draft["exceptions"],
            "source_note_ids": tag_pitfall["sample_note_ids"],
        },
    )
    assert resp.status_code == 201
    rule = resp.json()
    assert rule["source_note_ids"] == tag_pitfall["sample_note_ids"]
    assert rule["status"] == "active"

    # 4) 列出规则可见
    resp = client.get("/api/custom/notes/rules")
    assert resp.json()["count"] == 1