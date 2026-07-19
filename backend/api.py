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
from contextlib import asynccontextmanager
from datetime import datetime
from email.utils import parseaddr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

from smart_collect.config import DATA_DIR, SAMPLE_DIR, TEMPLATE_DIR, ensure_dirs, settings  # noqa: E402
from smart_collect.graph import run_collection_graph  # noqa: E402
from smart_collect.pipeline import run_collection  # noqa: E402
from smart_collect.sample_data import (  # noqa: E402
    MOCK_EMAIL,
    PROJECT_COMMON_COLUMNS,
    generate_hard_samples,
    generate_project_common_samples,
    generate_samples,
)
from smart_collect.state import AgentState  # noqa: E402
from smart_collect.tools import rag_tools  # noqa: E402
from smart_collect import store  # noqa: E402
from smart_collect import scheduler as sched_mod  # noqa: E402
from smart_collect import job_store  # noqa: E402
from smart_collect.inbox_pipeline import ingest_inbox  # noqa: E402
from smart_collect.tools.email_tools import EmailSendRequest, send_email  # noqa: E402

UPLOAD_DIR = DATA_DIR / "uploads"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """프로세스 수명과 Inbox Scheduler 수명을 일치시킨다."""
    sched_mod.start()
    yield


# 개발 서버 재로딩 시 .env의 최신 자동화 정책도 함께 다시 읽힌다.
app = FastAPI(title="Smart Collect Assistant", version="0.2.0", lifespan=lifespan)
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
        "self_correction": state.self_correction.model_dump()
        if state.self_correction
        else None,
        "supervisor_plan": state.supervisor_plan,
        "template_locked": state.template_locked,
        "template_id": state.template_id,
        "merged_file": state.merged_file,
        "error_report": state.error_report,
        "result_summary": state.result_summary,
        "agent_handoff_history": state.agent_handoff_history,
        # 에이전트 추론 과정 (화면 타임라인 + 시연 증거)
        "reasoning_log": state.reasoning_log,
        "reasoning_steps": [s.model_dump() for s in state.reasoning_steps],
        "downloads": {
            "merged": f"/api/download/{state.request_id}/merged"
            if state.merged_file
            else None,
            "error": f"/api/download/{state.request_id}/error"
            if state.error_report
            else None,
            "trace_md": f"/api/download-trace/{state.request_id}/md"
            if state.trace_files.get("md")
            else None,
            "trace_json": f"/api/download-trace/{state.request_id}/json"
            if state.trace_files.get("json")
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
        "gmail_read_ready": settings.gmail_read_ready,
        "auto_send_enabled": settings.auto_send_enabled,
    }


@app.post("/api/gen-samples")
def gen_samples() -> dict:
    return generate_samples()


@app.post("/api/gen-hard-samples")
def gen_hard_samples() -> dict:
    """현실 난이도 하드 샘플(오류 5종·스키마 드리프트·통화 숫자)을 생성한다 (item 2)."""
    return generate_hard_samples()


@app.post("/api/gen-project-samples")
def gen_project_samples() -> dict:
    """공통 항목 일괄 수정 데모용 프로젝트 엑셀 5개를 생성한다."""
    return generate_project_common_samples()


@app.get("/api/sample-email")
def sample_email() -> dict:
    return {"subject": MOCK_EMAIL["subject"], "body": MOCK_EMAIL["body"]}


@app.post("/api/design-template")
def design_template(intent: str = Form(...), use_llm: bool = Form(True)) -> dict:
    """자연어 취합 의도 → 양식 컬럼 스키마 설계(미리보기, 미확정).

    LLM(Azure) 이 있으면 LLM 설계, 없으면 휴리스틱. 사용자가 검토·수정 후 build 로 확정한다.
    """
    from smart_collect.tools.template_tools import (
        design_template_from_intent,
        template_spec_to_validation_rule,
    )

    intent = (intent or "").strip()
    if not intent:
        raise HTTPException(status_code=400, detail="걷고 싶은 내용을 입력하세요.")
    spec = design_template_from_intent(intent, prefer_llm=use_llm)
    rule = template_spec_to_validation_rule(spec)
    return {
        "template_spec": spec.model_dump(),
        "validation_rule": rule.model_dump(),
        "llm_used": spec.source == "llm",
    }


@app.post("/api/build-template")
def build_template(payload: dict) -> dict:
    """검토·수정한 양식 스펙을 확정해 배포용 엑셀 양식을 생성한다.

    payload: TemplateSpec(dict) 또는 {template_spec: {...}}
    반환: template_id, 다운로드 링크, 파생된 검증 규칙(라운드트립 증거).
    """
    from smart_collect.state import TemplateSpec
    from smart_collect.tools.template_tools import build_and_save_template

    data = payload.get("template_spec") if "template_spec" in payload else payload
    try:
        spec = TemplateSpec.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"양식 스펙이 올바르지 않습니다: {exc}") from exc
    if not spec.columns:
        raise HTTPException(status_code=400, detail="컬럼이 1개 이상 필요합니다.")
    ensure_dirs()
    return build_and_save_template(spec)


@app.get("/api/download-template/{template_id}")
def download_template(template_id: str) -> FileResponse:
    """생성한 양식 엑셀 파일 다운로드."""
    from smart_collect.tools.template_tools import template_excel_path

    path = template_excel_path(template_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="양식 파일을 찾을 수 없습니다.")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )


@app.post("/api/inbox/ingest")
def inbox_ingest(
    max_results: int = Form(100),
    use_llm: bool = Form(True),
) -> dict:
    """수신함 1회 자율 처리. 자동 발송은 서버 안전 정책을 통과할 때만 수행한다."""
    result = ingest_inbox(prefer_llm=use_llm, max_results=max_results)
    result["read_mode"] = settings.email_read_mode
    return result


@app.get("/api/inbox/queue")
def inbox_queue(status: str | None = None) -> dict:
    """검토 큐 조회. draft_ready/needs_review/general/quarantined/sent/error."""
    store.init_db()  # 최초 조회(수집 전)에도 안전하도록 테이블 보장
    return {
        "queue": store.list_records(status=status),
        "counts": store.counts_by_status(),
        "read_mode": settings.email_read_mode,
    }


@app.get("/api/agent/jobs")
def agent_jobs(status: str | None = None) -> dict:
    jobs = job_store.list_jobs(status=status)
    return {"jobs": jobs, "count": len(jobs)}


@app.get("/api/agent/actions/{event_id}")
def agent_actions(event_id: str) -> dict:
    actions = job_store.list_actions(event_id)
    return {"event_id": event_id, "actions": actions}


@app.get("/api/schedule")
def get_schedule() -> dict:
    """현재 자동 수집 스케줄 설정 + 다음 실행 예정 + 마지막 실행 결과."""
    return sched_mod.status()


@app.post("/api/schedule")
async def set_schedule(request: Request) -> dict:
    """화면 스케줄을 반영한다. 발송은 별도 Auto-send Policy Gate를 따른다."""
    body = await request.json()
    try:
        return sched_mod.apply(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/schedule/run-now")
def schedule_run_now() -> dict:
    """스케줄과 무관하게 지금 즉시 1회 수집한다."""
    return {"result": sched_mod.run_now(), "status": sched_mod.status()}


@app.post("/api/inbox/{message_id}/send")
def inbox_send(message_id: str, payload: dict | None = None) -> dict:
    """승인 발송 또는 처리 완료 메일의 추가 수신자 발송."""
    rec = store.get_record(message_id)
    if not rec:
        raise HTTPException(status_code=404, detail="해당 메일을 찾을 수 없습니다.")
    if rec["status"] not in {"draft_ready", "sent"}:
        raise HTTPException(
            status_code=400, detail="승인 대기 또는 발송 완료 상태에서만 발송할 수 있습니다."
        )

    payload = payload or {}
    raw_extras = payload.get("extra_recipients") or []
    if isinstance(raw_extras, str):
        raw_extras = raw_extras.split(",")

    def normalize(values) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for value in values:
            email = parseaddr(str(value))[1].strip().lower()
            if email and "@" in email and email not in seen:
                seen.add(email)
                out.append(email)
        return out

    base_to = normalize(c.get("email", "") for c in rec.get("recipients", []))
    extras = normalize(raw_extras)
    if rec["status"] == "sent":
        # 이미 받은 사람에게 중복 발송하지 않고 새로 추가한 사람에게만 보낸다.
        to = [email for email in extras if email not in set(base_to)]
        additional_only = True
    else:
        to = list(dict.fromkeys([*base_to, *extras]))
        additional_only = False
    if not to:
        detail = "추가 발송할 새 수신자를 입력해 주세요." if rec["status"] == "sent" else "수신자가 없습니다."
        raise HTTPException(status_code=400, detail=detail)

    result = send_email(
        EmailSendRequest(
            to=to,
            subject=rec.get("draft_subject") or "[취합 요청]",
            body=rec.get("draft_body") or "",
            attachment_paths=[
                p for p in rec.get("artifacts", {}).get("attachment_paths", [])
                if Path(p).exists()
            ],
        )
    )
    if additional_only:
        rec.setdefault("artifacts", {}).setdefault("additional_sends", []).append({
            "recipients": to,
            "message_id": result.get("message_id"),
            "sent_at": datetime.now().isoformat(timespec="seconds"),
        })
        store.upsert_record(rec)
    else:
        existing = {c.get("email", "").lower() for c in rec.get("recipients", [])}
        rec["recipients"].extend(
            {"name": email.split("@", 1)[0], "dept": "수동 추가", "email": email}
            for email in extras if email not in existing
        )
        store.upsert_record(rec)
        store.mark_sent(message_id, result.get("message_id"))
        job_id = rec.get("artifacts", {}).get("job_id")
        if job_id and rec.get("intent") == "request":
            job_store.update_job(job_id, status="collecting")
    return {
        "message_id": message_id,
        "send_result": result,
        "additional_only": additional_only,
    }


@app.post("/api/collect")
async def collect(
    subject: str = Form(...),
    body: str = Form(...),
    use_graph: bool = Form(True),
    use_llm: bool = Form(True),
    template_id: str = Form(""),
    files: list[UploadFile] = File(...),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="엑셀 파일을 1개 이상 업로드하세요.")

    ensure_dirs()

    # 라운드트립: 생성한 양식(template_id)이 지정되면 그 양식이 곧 검증 규칙이 된다.
    rule_override = None
    if template_id.strip():
        from smart_collect.tools.template_tools import (
            load_template_spec,
            template_spec_to_validation_rule,
        )

        spec = load_template_spec(template_id.strip())
        if spec is None:
            raise HTTPException(status_code=404, detail="지정한 양식(template_id)을 찾을 수 없습니다.")
        rule_override = template_spec_to_validation_rule(spec)
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
            state = run_collection_graph(
                request_id, subject, body, saved,
                rule_override=rule_override,
                template_id=template_id.strip() or None,
            )
        else:
            state = run_collection(
                request_id, subject, body, saved, prefer_llm=use_llm,
                rule_override=rule_override,
                template_id=template_id.strip() or None,
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


@app.post("/api/sync-common-fields")
async def sync_common_fields(
    reference_file: UploadFile = File(...),
    target_files: list[UploadFile] = File(...),
) -> dict:
    """기준 파일의 공통 프로젝트 컬럼 값으로 대상 파일들을 동기화한다."""
    from smart_collect.tools.excel_tools import sync_common_fields_from_reference

    if not reference_file.filename:
        raise HTTPException(status_code=400, detail="기준 파일이 필요합니다.")
    if not target_files:
        raise HTTPException(status_code=400, detail="수정 대상 파일을 1개 이상 업로드하세요.")
    if not reference_file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="기준 파일은 엑셀(.xlsx/.xls)이어야 합니다.")

    ensure_dirs()
    request_id = "SYNC-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    job_dir = UPLOAD_DIR / request_id
    job_dir.mkdir(parents=True, exist_ok=True)
    out_dir = DATA_DIR / "updated_files" / request_id

    ref_path = job_dir / Path(reference_file.filename).name
    with ref_path.open("wb") as f:
        shutil.copyfileobj(reference_file.file, f)

    saved_targets: list[str] = []
    for up in target_files:
        if not (up.filename or "").lower().endswith((".xlsx", ".xls")):
            raise HTTPException(
                status_code=400, detail=f"수정 대상은 엑셀(.xlsx/.xls)이어야 합니다: {up.filename}"
            )
        dest = job_dir / Path(up.filename).name
        with dest.open("wb") as f:
            shutil.copyfileobj(up.file, f)
        saved_targets.append(str(dest))

    try:
        r = sync_common_fields_from_reference(
            str(ref_path),
            saved_targets,
            PROJECT_COMMON_COLUMNS,
            output_dir=out_dir,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"공통 항목 동기화 실패: {exc}") from exc

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


def _extract_eml_text(raw: bytes) -> str:
    """.eml 바이트에서 제목 + 본문 텍스트를 추출한다."""
    from email import message_from_bytes
    from email.policy import default

    msg = message_from_bytes(raw, policy=default)
    subject = msg.get("subject", "") or ""
    body = ""
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is not None:
            body = part.get_content()
    except Exception:  # noqa: BLE001 - 폴백 보장
        payload = msg.get_payload()
        body = payload if isinstance(payload, str) else ""
    return (f"제목: {subject}\n\n" if subject else "") + (body or "")


@app.post("/api/upload-style-mails")
async def upload_style_mails(files: list[UploadFile] = File(...)) -> dict:
    """과거에 내가 작성한 메일 파일(.txt/.md/.eml)을 스타일 코퍼스로 업로드한다(#4)."""
    if not files:
        raise HTTPException(status_code=400, detail="업로드할 메일 파일이 필요합니다.")
    rag_tools.STYLE_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for up in files:
        name = Path(up.filename or "").name
        ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
        raw = await up.read()
        if ext == "eml":
            text = _extract_eml_text(raw)
            out_name = (name.rsplit(".", 1)[0] or "mail") + ".txt"
        elif ext in {"txt", "md"}:
            text = raw.decode("utf-8", errors="ignore")
            out_name = name
        else:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 형식입니다: {name} (.txt/.md/.eml만 가능)",
            )
        dest = rag_tools.STYLE_DIR / out_name
        dest.write_text(text, encoding="utf-8")
        saved.append(dest.name)
    count = len(
        [p for p in rag_tools.STYLE_DIR.glob("*") if p.suffix.lower() in {".txt", ".md"}]
    )
    return {"saved": saved, "count": count}


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


@app.post("/api/send-request-mail")
async def send_request_mail(
    to: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    template_id: str = Form(""),
    files: list[UploadFile] = File(default=[]),
) -> dict:
    """요청 메일 초안 + 첨부 양식 엑셀을 발송한다(1번 흐름).

    to: 쉼표로 구분된 수신자 이메일. files: 요청과 함께 받은 양식 엑셀(첨부).
    template_id: 지정하면 AI가 생성한 양식 엑셀을 자동 첨부한다.
    기본은 mock 발송. EMAIL_SEND_MODE=gmail 이면 실제 발송.
    """
    from smart_collect.tools.email_tools import EmailSendRequest, send_email

    recipients = [v.strip() for v in to.split(",") if v.strip()]
    if not recipients:
        raise HTTPException(status_code=400, detail="수신자 이메일이 필요합니다.")
    if not subject.strip() or not body.strip():
        raise HTTPException(status_code=400, detail="메일 제목과 본문이 필요합니다.")

    ensure_dirs()
    attach_paths: list[str] = []
    # 생성한 양식(template_id)을 자동 첨부
    if template_id.strip():
        from smart_collect.tools.template_tools import template_excel_path

        tpath = template_excel_path(template_id.strip())
        if tpath is None or not tpath.exists():
            raise HTTPException(status_code=404, detail="지정한 양식(template_id)을 찾을 수 없습니다.")
        attach_paths.append(str(tpath))
    if files:
        req_id = "SEND-" + datetime.now().strftime("%Y%m%d-%H%M%S")
        adir = UPLOAD_DIR / req_id
        adir.mkdir(parents=True, exist_ok=True)
        for up in files:
            if not up.filename:
                continue
            if not up.filename.lower().endswith((".xlsx", ".xls")):
                raise HTTPException(
                    status_code=400,
                    detail=f"첨부 양식은 엑셀(.xlsx/.xls)만 가능합니다: {up.filename}",
                )
            dest = adir / Path(up.filename).name
            with dest.open("wb") as f:
                shutil.copyfileobj(up.file, f)
            attach_paths.append(str(dest))

    try:
        res = send_email(
            EmailSendRequest(
                to=recipients, subject=subject, body=body,
                attachment_paths=attach_paths,
            )
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"메일 발송 실패: {exc}") from exc
    res["attachments"] = [Path(p).name for p in attach_paths]
    return res


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


@app.get("/api/download-trace/{request_id}/{kind}")
def download_trace(request_id: str, kind: str) -> FileResponse:
    """에이전트 실행 트레이스 증거 파일 다운로드 (md|json)."""
    if kind not in ("md", "json"):
        raise HTTPException(status_code=400, detail="kind 은 md 또는 json")
    path = DATA_DIR / "traces" / f"{request_id}.{kind}"
    if not path.exists():
        raise HTTPException(status_code=404, detail="트레이스 파일 없음")
    media = "text/markdown" if kind == "md" else "application/json"
    return FileResponse(path, media_type=media, filename=path.name)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
