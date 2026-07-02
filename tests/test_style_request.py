"""Gmail MCP 스타일 기반 요청 초안 기능 테스트."""

from fastapi.testclient import TestClient

from api import app
from smart_collect.tools import rag_tools


# ---------- Task 1: retrieve_style_samples ----------

def test_style_samples_empty_when_no_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path / "none")
    assert rag_tools.retrieve_style_samples("취합 요청") == []


def test_style_samples_returns_saved(monkeypatch, tmp_path):
    d = tmp_path / "style"
    d.mkdir()
    (d / "mail1.txt").write_text(
        "안녕하세요. 취합 협조 요청드립니다.", encoding="utf-8"
    )
    monkeypatch.setattr(rag_tools, "STYLE_DIR", d)
    out = rag_tools.retrieve_style_samples("취합 요청")
    assert len(out) == 1
    assert out[0]["title"] == "mail1.txt"
    assert "협조" in out[0]["snippet"]


# ---------- Task 2: 스타일 힌트 / 요청 메일 ----------

def test_build_style_hint_empty():
    from smart_collect.tools.guide_tools import _build_style_hint
    assert _build_style_hint(None) == ""
    assert _build_style_hint([]) == ""


def test_build_style_hint_includes_examples():
    from smart_collect.tools.guide_tools import _build_style_hint
    hint = _build_style_hint([{"snippet": "안녕하세요 협조바랍니다"}])
    assert "예시 1" in hint
    assert "협조바랍니다" in hint


def test_create_request_mail_accepts_style_samples():
    from smart_collect.tools.guide_tools import create_request_mail
    out = create_request_mail(
        "본문 안내", [{"name": "A"}], "2026-06-12", "form.xlsx",
        style_samples=[{"title": "m", "snippet": "안녕하세요"}],
    )
    assert "mail_subject" in out
    assert "mail_body" in out


# ---------- Task 3: 저장/조회 엔드포인트 ----------

def test_save_style_mail_and_count(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path)
    client = TestClient(app)
    r = client.post(
        "/api/save-style-mail",
        json={"subject": "취합요청", "body": "안녕하세요 협조바랍니다"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["saved"].endswith((".txt", ".md"))


def test_save_style_mail_requires_body(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path)
    client = TestClient(app)
    r = client.post("/api/save-style-mail", json={"body": "   "})
    assert r.status_code == 400


def test_style_mails_lists_saved(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    client = TestClient(app)
    r = client.get("/api/style-mails")
    assert r.status_code == 200
    assert r.json()["count"] == 1
    assert "a.txt" in r.json()["files"]


def test_upload_style_mails_txt(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path)
    client = TestClient(app)
    r = client.post(
        "/api/upload-style-mails",
        files=[
            ("files", ("mymail.txt", "안녕하세요 협조 부탁드립니다".encode("utf-8"), "text/plain")),
        ],
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1
    assert "mymail.txt" in r.json()["saved"]
    assert (tmp_path / "mymail.txt").read_text(encoding="utf-8") == "안녕하세요 협조 부탁드립니다"


def test_upload_style_mails_rejects_bad_ext(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path)
    client = TestClient(app)
    r = client.post(
        "/api/upload-style-mails",
        files=[("files", ("bad.xlsx", b"data", "application/octet-stream"))],
    )
    assert r.status_code == 400


def test_upload_style_mails_eml_extracts_body(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path)
    eml = (
        "Subject: 6월 취합 요청\r\n"
        "From: me@company.com\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "안녕하세요. 늘 협조 감사드립니다."
    ).encode("utf-8")
    client = TestClient(app)
    r = client.post(
        "/api/upload-style-mails",
        files=[("files", ("past.eml", eml, "message/rfc822"))],
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1
    saved = tmp_path / "past.txt"
    assert saved.exists()
    text = saved.read_text(encoding="utf-8")
    assert "협조 감사드립니다" in text


# ---------- Task 4: /api/guide 스타일 연결 ----------

def test_guide_reports_style_used(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path)
    (tmp_path / "past.txt").write_text(
        "안녕하세요. 늘 감사합니다. 협조 부탁드립니다.", encoding="utf-8"
    )
    client = TestClient(app)
    r = client.post(
        "/api/guide",
        data={"subject": "6월 취합", "body": "작성 항목은 부서명, 담당자 입니다."},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["style_used"] is True
    assert "past.txt" in d["style_sources"]


def test_guide_without_style(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_tools, "STYLE_DIR", tmp_path / "empty")
    client = TestClient(app)
    r = client.post(
        "/api/guide",
        data={"subject": "6월 취합", "body": "작성 항목은 부서명 입니다."},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["style_used"] is False
    assert d["style_sources"] == []
