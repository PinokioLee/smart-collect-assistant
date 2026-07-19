"""담당자 조직도(디렉터리) — 취합 요청 메일의 수신자 결정.

설계 원칙 (RAG 사용 검토 결과 반영)
---------------------------------
담당자 이메일 주소는 RAG로 '추측'하면 안 된다. 잘못된 주소로 요청 메일이
발송되면 실무 사고다. 따라서 수신자 정보는 정확한 조직도(디렉터리)에서만
가져온다. 1차 PoC 에서는 아래 내장 mock 디렉터리를 쓰고, 운영 단계에서는
사내 조직도 API/DB 로 교체할 수 있도록 인터페이스만 고정한다.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from email.utils import getaddresses
from pathlib import Path

from ..config import settings


@dataclass
class Contact:
    name: str
    dept: str
    email: str


# 내장 mock 조직도 — 운영에서는 사내 조직도 API/DB 로 교체
_DIRECTORY: list[Contact] = [
    Contact(name="김영수", dept="영업팀", email="kimys@company.com"),
    Contact(name="정우성", dept="생산팀", email="jung@company.com"),
    Contact(name="오세훈", dept="품질팀", email="ohsh@company.com"),
]

# 부서명 정규화(요청 메일에 '영업1팀' 처럼 세부팀이 와도 상위 부서로 매핑)
_DEPT_ALIASES = {
    "영업": "영업팀", "생산": "생산팀", "품질": "품질팀",
}


def _valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value.strip()))


def _configured_directory() -> list[Contact] | None:
    """설정된 CSV/JSON 조직도를 읽는다.

    설정 파일이 지정됐는데 읽지 못하거나 유효한 연락처가 없으면 내장 샘플로
    조용히 폴백하지 않는다. 잘못된 실수신자로 발송될 가능성보다 검토 전환이 안전하다.
    """
    if not settings.directory_file:
        return None
    path = Path(settings.directory_file).expanduser()
    if not path.is_file():
        return []
    try:
        if path.suffix.lower() == ".json":
            rows = json.loads(path.read_text(encoding="utf-8-sig"))
        elif path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
        else:
            return []
    except (OSError, UnicodeError, json.JSONDecodeError, csv.Error):
        return []
    if not isinstance(rows, list):
        return []
    contacts: list[Contact] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        email = str(row.get("email") or "").strip().lower()
        dept = str(row.get("dept") or "").strip()
        name = str(row.get("name") or "").strip()
        if not dept or not _valid_email(email) or email in seen:
            continue
        seen.add(email)
        contacts.append(Contact(name=name or email.split("@", 1)[0], dept=dept, email=email))
    return contacts


def _directory() -> list[Contact]:
    configured = _configured_directory()
    return _DIRECTORY if configured is None else configured


def _normalize_dept(name: str) -> str | None:
    text = name.strip()
    for key, canonical in _DEPT_ALIASES.items():
        if key in text:
            return canonical
    return None


def lookup_recipients(depts: list[str] | None = None) -> list[dict]:
    """담당자 목록을 조회한다. depts 가 없으면 전체 부서를 반환한다.

    Returns: [{"name", "dept", "email"}]
    """
    directory = _directory()
    if not depts:
        return [c.__dict__.copy() for c in directory]

    available = {c.dept for c in directory}
    wanted = {
        normalized
        for raw in depts
        for normalized in (
            _normalize_dept(raw) or (raw.strip() if raw.strip() in available else None),
        )
        if normalized
    }
    matched = [c for c in directory if c.dept in wanted]
    # 명시된 부서를 찾지 못했는데 전 직원에게 보내는 것은 실무 사고가 될 수 있다.
    # 빈 목록을 반환해 Autonomy Policy가 사람 확인으로 전환하도록 한다.
    return [c.__dict__.copy() for c in matched]


def _contacts_from_headers(values: list[str]) -> list[dict]:
    """From/Cc 헤더를 발송 가능한 연락처 목록으로 정규화한다."""
    contacts: list[dict] = []
    seen: set[str] = set()
    for name, email in getaddresses(values):
        normalized = email.strip().lower()
        if not normalized or "@" not in normalized or normalized in seen:
            continue
        seen.add(normalized)
        contacts.append({
            "name": name.strip() or normalized.split("@", 1)[0],
            "dept": "원본 메일",
            "email": normalized,
        })
    return contacts


def resolve_collection_recipients(message) -> tuple[list[dict], str]:
    """취합 대상을 결정한다.

    메일에 대상 부서가 명확하면 조직도를 사용하고, 별도 대상이 없으면 최초
    요청 메일의 작성자(From)와 참조자(Cc)를 그대로 회신 대상으로 사용한다.
    """
    text = f"{message.subject}\n{message.body}"
    target_lines = re.findall(
        r"(?:취합\s*대상|작성\s*대상|제출\s*대상|수신자)\s*[:：]\s*([^\n]+)",
        text,
        flags=re.IGNORECASE,
    )
    target_text = " ".join(target_lines)
    explicit_departments = [
        canonical
        for alias, canonical in _DEPT_ALIASES.items()
        if alias in target_text or f"{canonical}에서" in text or f"{canonical} 대상" in text
    ]
    for contact in _directory():
        if contact.dept in target_text and contact.dept not in explicit_departments:
            explicit_departments.append(contact.dept)
    all_departments = any(
        phrase in text
        for phrase in ("각 부서", "전 부서", "모든 부서", "전체 부서", "각 팀", "전사 대상")
    )
    if explicit_departments or all_departments:
        return lookup_recipients(explicit_departments or None), "directory_explicit_target"

    reply_all = _contacts_from_headers([message.sender, *(message.cc or [])])
    if reply_all:
        return reply_all, "original_sender_cc"

    return [], "missing_recipients"
