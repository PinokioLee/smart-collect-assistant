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
