"""M2 AI 标签建议端点测试。

不依赖真实 AI:monkey-patch `generate_ai_text`,覆盖:
- 缺 Key → 400 + 审计 error
- 正常 JSON → 返回建议 + 审计 success
- AI 返非 JSON → 容错返回空 tags
- markdown 围栏 → 正确解析
- 简短列表形式 → 正确解析
- 过滤已有标签
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
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
def client():
    tmp = Path(tempfile.mkdtemp())
    db_path = tmp / "notes.db"
    audit_path = tmp / "ai_audit.log"
    db = notes_db.NotesDB(db_path)
    notes_module._db_singleton = db
    notes_module._AUDIT_LOG_PATH = audit_path

    app = FastAPI()
    app.include_router(notes_module._build_router())
    return TestClient(app), audit_path


def _read_audit(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_suggest_tags_ai_key_missing(client):
    """缺 Key:400 + 审计记录 error。"""
    cli, audit_path = client
    with patch.object(notes_module, "_check_ai_key_configured", return_value=False):
        resp = cli.post(
            "/api/custom/notes/ai/suggest-tags",
            json={"content": "半导体板块MACD顶背离"},
        )
    assert resp.status_code == 400
    assert "AI Key" in resp.json()["detail"]
    recs = _read_audit(audit_path)
    assert any(r["endpoint"] == "suggest_tags" and r["status"] == "error" for r in recs)


def test_suggest_tags_happy_path(client):
    """AI 返回标准 JSON:正确解析 + 审计 success。"""
    cli, audit_path = client
    payload = {
        "tags": [
            {"name": "半导体", "confidence": 0.9, "reason": "板块关键词"},
            {"name": "MACD顶背离", "confidence": 0.8, "reason": "技术形态"},
            {"name": "技术形态", "confidence": 0.7, "reason": "通用分类"},
        ],
        "suggested_type": "knowledge",
        "suggested_type_confidence": 0.85,
    }
    ai_text = json.dumps(payload, ensure_ascii=False)
    with patch.object(notes_module, "_check_ai_key_configured", return_value=True), \
         patch("app.services.ai_provider.generate_ai_text", new=AsyncMock(return_value=ai_text)):
        resp = cli.post(
            "/api/custom/notes/ai/suggest-tags",
            json={"content": "今天看到半导体MACD顶背离,可能见顶", "max_suggest": 5},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggested_type"] == "knowledge"
    names = [t["name"] for t in body["tags"]]
    assert names == ["半导体", "MACD顶背离", "技术形态"]
    assert all(0 <= t["confidence"] <= 1 for t in body["tags"])
    assert body["latency_ms"] >= 0
    recs = _read_audit(audit_path)
    succ = [r for r in recs if r["status"] == "success"]
    assert len(succ) == 1
    assert succ[0]["endpoint"] == "suggest_tags"
    assert succ[0]["latency_ms"] >= 0
    assert succ[0]["tag_count"] == 3


def test_suggest_tags_markdown_fence(client):
    """AI 返回 ```json ... ``` 围栏:正确解析。"""
    cli, _ = client
    ai_text = (
        "好的,以下是建议:\n"
        "```json\n"
        '{"tags": [{"name": "止损", "confidence": 0.7}], "suggested_type": "pitfall"}\n'
        "```\n"
        "请酌情采纳。"
    )
    with patch.object(notes_module, "_check_ai_key_configured", return_value=True), \
         patch("app.services.ai_provider.generate_ai_text", new=AsyncMock(return_value=ai_text)):
        resp = cli.post(
            "/api/custom/notes/ai/suggest-tags",
            json={"content": "今天追高被套,要不要止损"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggested_type"] == "pitfall"
    assert [t["name"] for t in body["tags"]] == ["止损"]


def test_suggest_tags_brief_list(client):
    """AI 返回简短字符串数组。"""
    cli, _ = client
    ai_text = '{"tags": ["财报", "半导体", "估值"], "suggested_type": "review"}'
    with patch.object(notes_module, "_check_ai_key_configured", return_value=True), \
         patch("app.services.ai_provider.generate_ai_text", new=AsyncMock(return_value=ai_text)):
        resp = cli.post(
            "/api/custom/notes/ai/suggest-tags",
            json={"content": "看 2024 半年报"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert [t["name"] for t in body["tags"]] == ["财报", "半导体", "估值"]


def test_suggest_tags_filters_existing(client):
    """已有标签应被过滤。"""
    cli, _ = client
    ai_text = '{"tags": ["半导体", "止损", "技术形态"], "suggested_type": "knowledge"}'
    with patch.object(notes_module, "_check_ai_key_configured", return_value=True), \
         patch("app.services.ai_provider.generate_ai_text", new=AsyncMock(return_value=ai_text)):
        resp = cli.post(
            "/api/custom/notes/ai/suggest-tags",
            json={"content": "x", "existing_tags": ["半导体", "止损"]},
        )
    assert resp.status_code == 200
    body = resp.json()
    names = [t["name"] for t in body["tags"]]
    assert "半导体" not in names
    assert "止损" not in names
    assert "技术形态" in names


def test_suggest_tags_ai_error(client):
    """AI 调用失败:502 + 审计 error。"""
    cli, audit_path = client
    with patch.object(notes_module, "_check_ai_key_configured", return_value=True), \
         patch("app.services.ai_provider.generate_ai_text", new=AsyncMock(side_effect=RuntimeError("网络异常"))):
        resp = cli.post(
            "/api/custom/notes/ai/suggest-tags",
            json={"content": "半导体板块"},
        )
    assert resp.status_code == 502
    assert "网络异常" in resp.json()["detail"]
    recs = _read_audit(audit_path)
    assert any(r["status"] == "error" and r["error_code"] == "RuntimeError" for r in recs)


def test_suggest_tags_invalid_type(client):
    """AI 返回不在枚举里的类型:忽略,留空。"""
    cli, _ = client
    ai_text = '{"tags": [{"name": "半导体"}], "suggested_type": "bullshit"}'
    with patch.object(notes_module, "_check_ai_key_configured", return_value=True), \
         patch("app.services.ai_provider.generate_ai_text", new=AsyncMock(return_value=ai_text)):
        resp = cli.post(
            "/api/custom/notes/ai/suggest-tags",
            json={"content": "x"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggested_type"] is None


def test_suggest_tags_non_json(client):
    """AI 返回完全非 JSON:容错返回空 tags,不要 500。"""
    cli, _ = client
    with patch.object(notes_module, "_check_ai_key_configured", return_value=True), \
         patch("app.services.ai_provider.generate_ai_text", new=AsyncMock(return_value="随便聊聊")):
        resp = cli.post(
            "/api/custom/notes/ai/suggest-tags",
            json={"content": "x"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tags"] == []
    assert body["suggested_type"] is None


def test_suggest_tags_max_suggest_capped(client):
    """max_suggest 上限:超过 20 应被 pydantic 拒绝。"""
    cli, _ = client
    resp = cli.post(
        "/api/custom/notes/ai/suggest-tags",
        json={"content": "x", "max_suggest": 100},
    )
    assert resp.status_code == 422


def test_suggest_tags_empty_content_rejected(client):
    """空 content 必填校验。"""
    cli, _ = client
    resp = cli.post(
        "/api/custom/notes/ai/suggest-tags",
        json={"content": ""},
    )
    assert resp.status_code == 422