"""Smart Collect FastAPI 서버 (Phase 3).

React 프론트엔드와 멀티에이전트 워크플로우를 연결한다.

엔드포인트
  GET  /api/health            상태 확인
  POST /api/gen-samples       데모용 샘플 메일/엑셀 생성
  GET  /api/sample-email      샘플 메일 제목/본문 조회
  POST /api/collect           메일 + 엑셀 업로드 → 검증/병합 실행
  GET  /api/download/{request_id}/{kind}   결과 파일 다운로드(merged|error)
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

from smart_collect.config import DATA_DIR, SAMPLE_DIR, ensure_dirs, settings  # noqa: E402
from smart_collect.graph import run_collection_graph  # noqa: E402
from smart_collect.pipeline import run_collection  # noqa: E402
from smart_collect.sample_data import MOCK_EMAIL, generate_samples  # noqa: E402
from smart_collect.state import AgentState  # noqa: E402
from smart_collect.tools import rag_tools  # noqa: E402

UPLOAD_DIR = DATA_DIR / "uploads"

app = FastAPI(title="Smart Collect Assistant", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # PoC: 로컬 개발 편의. 운영에선 도메인 제한.
    allow_methods=["*"],
    allow_headers=["*"],
)


def _state_to_dict(state: AgentState) -> dict:
    return {
        "request_id": state.request_id,
        "current_stage": state.current_stage,
        "extracted_requirements": state.extracted_requirements.model_dump()
        if state.extracted_requirements
        else None,
        "validation_rules": state.validation_rules.model_dump()
        if state.validation_rules
        else None,
        "validation_result": state.validation_result.model_dump()
        if state.validation_result
        else None,
        "merged_file": state.merged_file,
        "error_report": state.error_report,
        "result_summary": state.result_summary,
        "agent_handoff_history": state.agent_handoff_history,
        "downloads": {
            "merged": f"/api/download/{state.request_id}/merged"
            if state.merged_file
            else None,
            "error": f"/api/download/{state.request_id}/error"
            if state.error_report
            else None,
        },
    }


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "azure_ready": settings.azure_ready,
        "use_rag": settings.use_rag,
        "use_langfuse": settings.langfuse_ready,
        "email_send_mode": settings.email_send_mode,
        "gmail_ready": bool(settings.gmail_credentials_file)
        if settings.email_send_mode == "gmail"
        else False,
    }


@app.post("/api/gen-samples")
def gen_samples() -> dict:
    return generate_samples()


@app.get("/api/sample-email")
def sample_email() -> dict:
    return {"subject": MOCK_EMAIL["subject"], "body": MOCK_EMAIL["body"]}


@app.post("/api/collect")
async def collect(
    subject: str = Form(...),
    body: str = Form(...),
    use_graph: bool = Form(True),
    use_llm: bool = Form(True),
    files: list[UploadFile] = File(...),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="엑셀 파일을 1개 이상 업로드하세요.")

    ensure_dirs()
    request_id = "REQ-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    job_dir = UPLOAD_DIR / request_id
    job_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    for up in files:
        if not (up.filename or "").lower().endswith((".xlsx", ".xls")):
            raise HTTPException(
                status_code=400, detail=f"엑셀 파일이 아닙니다: {up.filename}"
            )
        dest = job_dir / Path(up.filename).name
        with dest.open("wb") as f:
            shutil.copyfileobj(up.file, f)
        saved.append(str(dest))

    try:
        if use_graph:
            state = run_collection_graph(request_id, subject, body, saved)
        else:
            state = run_collection(
                request_id, subject, body, saved, prefer_llm=use_llm
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"처리 실패: {exc}") from exc

    return _state_to_dict(state)


@app.post("/api/update-fields")
async def update_fields(
    target_field: str = Form(...),
    new_value: str = Form(...),
    old_value: str = Form(""),
    files: list[UploadFile] = File(...),
) -> dict:
    """공통 항목 일괄 수정 (#7)."""
    from smart_collect.tools.excel_tools import update_common_fields

    ensure_dirs()
    request_id = "UPD-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    job_dir = UPLOAD_DIR / request_id
    job_dir.mkdir(parents=True, exist_ok=True)
    out_dir = DATA_DIR / "updated_files" / request_id
    saved: list[str] = []
    for up in files:
        dest = job_dir / Path(up.filename).name
        with dest.open("wb") as f:
            shutil.copyfileobj(up.file, f)
        saved.append(str(dest))

    r = update_common_fields(
        saved, target_field, new_value,
        old_value=(old_value or None), output_dir=out_dir,
    )
    r["downloads"] = [
        f"/api/download-file/{request_id}/{Path(p).name}" for p in r["updated_files"]
    ]
    r["request_id"] = request_id
    return r


@app.post("/api/save-style-mail")
def save_style_mail(payload: dict) -> dict:
    """과거 발송 요청 메일을 스타일 코퍼스로 저장한다(#4).

    payload: {filename?, subject?, body}
    Claude Code(MCP)가 Sent 메일을 이 형태로 전달하거나, UI 파일 업로드로도 사용.
    """
    body = str(payload.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="메일 본문(body)이 필요합니다.")
    subject = str(payload.get("subject") or "").strip()
    rag_tools.STYLE_DIR.mkdir(parents=True, exist_ok=True)
    filename = str(payload.get("filename") or "").strip()
    if not filename:
        filename = "style-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if not filename.lower().endswith((".txt", ".md")):
        filename += ".txt"
    dest = rag_tools.STYLE_DIR / Path(filename).name
    content = (f"제목: {subject}\n\n" if subject else "") + body
    dest.write_text(content, encoding="utf-8")
    count = len(
        [p for p in rag_tools.STYLE_DIR.glob("*") if p.suffix.lower() in {".txt", ".md"}]
    )
    return {"saved": str(dest), "count": count}


@app.get("/api/style-mails")
def style_mails() -> dict:
    """저장된 스타일 샘플 개수/목록(#4). UI 배지용."""
    if not rag_tools.STYLE_DIR.exists():
        return {"count": 0, "files": []}
    files = sorted(
        p.name for p in rag_tools.STYLE_DIR.glob("*")
        if p.suffix.lower() in {".txt", ".md"}
    )
    return {"count": len(files), "files": files}


@app.post("/api/guide")
def guide(subject: str = Form(...), body: str = Form(...)) -> dict:
    """작성 가이드 + 요청 메일 초안 (과거 발송 스타일 RAG 반영)."""
    from smart_collect.tools.guide_tools import create_request_mail, generate_writing_guide
    from smart_collect.tools.requirement_tools import analyze_collection_email
    from smart_collect.tools.submission_tools import SAMPLE_RECIPIENTS

    req = analyze_collection_email(subject, body, prefer_llm=True)
    query = " ".join(filter(None, [req.request_title or "", *req.required_fields]))
    style_samples = rag_tools.retrieve_style_samples(query)
    g = generate_writing_guide(req, references=style_samples or None)
    m = create_request_mail(
        g["guide_body"], SAMPLE_RECIPIENTS, req.deadline, "취합양식.xlsx",
        style_samples=style_samples or None,
    )
    return {
        "extracted": req.model_dump(),
        "guide": g,
        "mail_draft": m,
        "llm_used": settings.azure_ready,
        "style_used": bool(style_samples),
        "style_sources": [s["title"] for s in style_samples],
    }


@app.post("/api/send-email")
def send_email_endpoint(payload: dict) -> dict:
    """승인된 메일 초안을 Gmail 또는 mock adapter 로 발송한다.

    payload: {to:[email], subject, body, cc?, attachment_paths?}
    """
    from smart_collect.tools.email_tools import EmailSendRequest, send_email

    to = [str(v).strip() for v in payload.get("to", []) if str(v).strip()]
    if not to:
        raise HTTPException(status_code=400, detail="수신자 이메일이 필요합니다.")
    subject = str(payload.get("subject") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not subject or not body:
        raise HTTPException(status_code=400, detail="메일 제목과 본문이 필요합니다.")
    cc = [str(v).strip() for v in payload.get("cc", []) if str(v).strip()]
    attachment_paths = [
        str(v).strip() for v in payload.get("attachment_paths", []) if str(v).strip()
    ]
    try:
        return send_email(
            EmailSendRequest(
                to=to,
                cc=cc,
                subject=subject,
                body=body,
                attachment_paths=attachment_paths,
            )
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"메일 발송 실패: {exc}") from exc


@app.post("/api/track")
def track(payload: dict) -> dict:
    """제출 현황 추적 + 미제출자 리마인드 (#5, #6).

    payload: {recipients:[{name,dept,email}], submitted:[식별자], deadline}
    """
    from smart_collect.tools.guide_tools import generate_reminder_message
    from smart_collect.tools.submission_tools import (
        SAMPLE_RECIPIENTS,
        track_submission_status,
    )

    recipients = payload.get("recipients") or SAMPLE_RECIPIENTS
    submitted = [
        {"identifier": s, "submitted_at": payload.get("submitted_at", "2026-06-12 14:00")}
        for s in (payload.get("submitted") or [])
    ]
    deadline = payload.get("deadline", "2026-06-12 17:00")
    st = track_submission_status(recipients, submitted, deadline=deadline)
    if st["missing_list"]:
        st["reminder"] = generate_reminder_message(st["missing_list"], deadline)
    return st


@app.get("/api/download-file/{request_id}/{filename}")
def download_file(request_id: str, filename: str) -> FileResponse:
    path = DATA_DIR / "updated_files" / request_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="파일 없음")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )


@app.get("/api/download/{request_id}/{kind}")
def download(request_id: str, kind: str) -> FileResponse:
    if kind == "merged":
        path = DATA_DIR / "merged_files" / f"{request_id}_merged.xlsx"
    elif kind == "error":
        path = DATA_DIR / "error_reports" / f"{request_id}_error_report.xlsx"
    else:
        raise HTTPException(status_code=400, detail="kind 은 merged 또는 error")

    if not path.exists():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
