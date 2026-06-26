"""Submission Tracking Agent 도구 — 제출 현황 추적 (mock 기반, 결정론적).

작성자 목록과 제출물(회신 메일/첨부 파일명)을 대조해 제출자/미제출자/지연자를
구분한다. LLM 판단이 아니라 규칙 매칭으로 처리해 재현성을 보장한다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

# 데모용 기본 작성자 목록
SAMPLE_RECIPIENTS = [
    {"name": "김영수", "dept": "영업팀", "email": "kimys@company.com"},
    {"name": "정우성", "dept": "생산팀", "email": "jung@company.com"},
    {"name": "오세훈", "dept": "품질팀", "email": "ohsh@company.com"},
    {"name": "한지원", "dept": "물류팀", "email": "hanjw@company.com"},
]


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def submissions_from_files(file_paths: list[str], submitted_at: str | None = None) -> list[dict]:
    """제출된 엑셀 파일명에서 제출 식별자를 도출(부서명 추정)."""
    subs = []
    for p in file_paths:
        subs.append({"identifier": Path(p).stem, "submitted_at": submitted_at})
    return subs


def track_submission_status(
    recipient_list: list[dict],
    submissions: list[dict],
    deadline: str | None = None,
) -> dict:
    """작성자별 제출 여부를 대조한다.

    submissions: [{identifier: 파일명/이름/부서/이메일, submitted_at?}]
    Returns: {submitted_list, missing_list, late_list, submission_rate, summary}
    """
    deadline_dt = _parse_dt(deadline)
    submitted_list, missing_list, late_list = [], [], []

    for r in recipient_list:
        keys = [r.get("name", ""), r.get("dept", ""), r.get("email", "")]
        match = None
        for s in submissions:
            ident = str(s.get("identifier", ""))
            if any(k and k in ident for k in keys):
                match = s
                break
        if match is None:
            missing_list.append(r)
            continue
        rec = {**r, "submitted_at": match.get("submitted_at")}
        submitted_list.append(rec)
        sub_dt = _parse_dt(match.get("submitted_at"))
        if deadline_dt and sub_dt and sub_dt > deadline_dt:
            late_list.append(rec)

    total = len(recipient_list)
    rate = round(len(submitted_list) / total * 100, 1) if total else 0.0
    summary = (
        f"전체 {total}명 / 제출 {len(submitted_list)}명 / 미제출 {len(missing_list)}명 / "
        f"지연 {len(late_list)}명 / 제출률 {rate}%"
    )
    return {
        "submitted_list": submitted_list,
        "missing_list": missing_list,
        "late_list": late_list,
        "submission_rate": rate,
        "summary": summary,
    }
