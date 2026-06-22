"""1차 PoC 데모용 샘플 데이터 생성기.

- mock 취합 요청 메일 1건 (JSON)
- 부서별 제출 엑셀 3개 (영업/생산/품질) — 검증 데모를 위해 오류를 의도적으로 심음

표준 스키마 (시스템 개선요청 취합 양식)
  부서명 / 담당자 / 요청시스템 / 개선요청내용 / 긴급도 / 요청사유 / 요청일자

심어둔 오류 (총 4건, 4개 행)
  - 영업팀 4행: 요청시스템 누락 (필수값 누락)
  - 생산팀 3행: 담당자 누락 (필수값 누락)
  - 생산팀 5행: 1팀 2행과 동일 → 중복 데이터
  - 품질팀 3행: 긴급도 "매우 급함" (허용값 외) + 요청일자 "2026/06/05" (형식 오류)
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .config import SAMPLE_DIR, ensure_dirs

COLUMNS = [
    "부서명",
    "담당자",
    "요청시스템",
    "개선요청내용",
    "긴급도",
    "요청사유",
    "요청일자",
]

MOCK_EMAIL = {
    "subject": "2026년 6월 시스템 개선 요청사항 취합",
    "body": (
        "각 부서별 시스템 개선 요청사항을 첨부 양식에 작성하여 "
        "2026년 6월 12일 17시까지 회신 바랍니다.\n"
        "작성 항목은 부서명, 담당자, 요청시스템, 개선요청내용, 긴급도, 요청사유, 요청일자입니다.\n"
        "긴급도는 상/중/하 중 하나로 작성해 주세요.\n"
        "요청일자는 YYYY-MM-DD 형식으로 작성해 주세요.\n"
        "부서명, 담당자, 요청시스템, 긴급도는 필수 입력 항목입니다."
    ),
}

_영업팀 = [
    ["영업1팀", "김영수", "ERP", "거래처 등록 화면 속도 개선", "중", "등록 지연 빈번", "2026-06-03"],
    ["영업1팀", "박지민", "CRM", "영업 기회 알림 기능 추가", "상", "기회 누락 발생", "2026-06-04"],
    ["영업2팀", "이서연", "ERP", "견적서 양식 표준화", "하", "부서별 양식 상이", "2026-06-05"],
    # 4행: 요청시스템 누락 (필수값 누락)
    ["영업2팀", "최민호", "", "단가 이력 조회 기능", "중", "과거 단가 추적 어려움", "2026-06-05"],
]

_생산팀 = [
    ["생산1팀", "정우성", "MES", "설비 가동률 대시보드", "상", "실시간 모니터링 필요", "2026-06-02"],
    # 3행: 담당자 누락 (필수값 누락)
    ["생산1팀", "", "MES", "작업지시 자동 배포", "중", "수기 배포 비효율", "2026-06-03"],
    ["생산2팀", "한지원", "WMS", "재고 실사 모바일 지원", "중", "현장 입력 불편", "2026-06-04"],
    # 5행: 생산1팀 1행과 동일 → 중복 데이터
    ["생산1팀", "정우성", "MES", "설비 가동률 대시보드", "상", "실시간 모니터링 필요", "2026-06-02"],
]

_품질팀 = [
    ["품질팀", "오세훈", "QMS", "불량 코드 표준화", "중", "코드 불일치", "2026-06-03"],
    ["품질팀", "신유진", "QMS", "검사 성적서 자동 생성", "상", "수기 작성 부담", "2026-06-04"],
    # 3행: 긴급도 허용값 외 + 요청일자 형식 오류 (오류 2건, 같은 행)
    ["품질팀", "강하늘", "LIMS", "시험 결과 연동", "매우 급함", "수기 입력 오류", "2026/06/05"],
]


def _write_excel(rows: list[list[str]], filename: str) -> Path:
    df = pd.DataFrame(rows, columns=COLUMNS)
    path = SAMPLE_DIR / filename
    df.to_excel(path, index=False, engine="openpyxl")
    return path


def generate_samples() -> dict[str, object]:
    """샘플 메일 + 엑셀 3개를 생성하고 경로를 반환한다."""
    ensure_dirs()

    email_path = SAMPLE_DIR / "mock_email.json"
    email_path.write_text(
        json.dumps(MOCK_EMAIL, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    excel_paths = [
        _write_excel(_영업팀, "개선요청_영업팀.xlsx"),
        _write_excel(_생산팀, "개선요청_생산팀.xlsx"),
        _write_excel(_품질팀, "개선요청_품질팀.xlsx"),
    ]

    return {
        "email": str(email_path),
        "excels": [str(p) for p in excel_paths],
    }


if __name__ == "__main__":
    result = generate_samples()
    print("샘플 데이터 생성 완료:")
    print(f"  메일: {result['email']}")
    for p in result["excels"]:  # type: ignore[index]
        print(f"  엑셀: {p}")
