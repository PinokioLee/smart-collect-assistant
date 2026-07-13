"""담당자 조직도(디렉터리) — 취합 요청 메일의 수신자 결정.

설계 원칙 (RAG 사용 검토 결과 반영)
---------------------------------
담당자 이메일 주소는 RAG로 '추측'하면 안 된다. 잘못된 주소로 요청 메일이
발송되면 실무 사고다. 따라서 수신자 정보는 정확한 조직도(디렉터리)에서만
가져온다. 1차 PoC 에서는 아래 내장 mock 디렉터리를 쓰고, 운영 단계에서는
사내 조직도 API/DB 로 교체할 수 있도록 인터페이스만 고정한다.
"""

from __future__ import annotations

from dataclasses import dataclass


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
    if not depts:
        return [c.__dict__.copy() for c in _DIRECTORY]

    wanted = {d for d in (_normalize_dept(x) for x in depts) if d}
    matched = [c for c in _DIRECTORY if c.dept in wanted]
    # 매칭 실패 시 전체 반환(누락보다 과다 안내가 안전) — 검토 화면에서 조정
    picked = matched or _DIRECTORY
    return [c.__dict__.copy() for c in picked]
