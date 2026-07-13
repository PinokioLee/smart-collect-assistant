"""Smart Collect CLI - 1차 PoC 실행 진입점.

사용 예:
  # 1) 샘플 데이터 생성
  python backend/cli.py gen-samples

  # 2) 샘플로 전체 취합 검증/병합 실행
  python backend/cli.py run

  # 3) 내 파일로 실행
  python backend/cli.py run --subject "..." --body-file mail.txt --excel a.xlsx b.xlsx
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Windows 기본 콘솔(CP949)에서도 시연 로그 출력이 중단되지 않도록 한다.
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except AttributeError:
    pass

# backend 패키지 import 경로 보장
sys.path.insert(0, str(Path(__file__).resolve().parent))

from smart_collect.config import SAMPLE_DIR, settings  # noqa: E402
from smart_collect.pipeline import run_collection  # noqa: E402
from smart_collect.sample_data import (  # noqa: E402
    MOCK_EMAIL,
    generate_hard_samples,
    generate_samples,
)

_CONSOLE_TRANSLATION = str.maketrans(
    {
        "—": "-",
        "–": "-",
        "→": "->",
        "←": "<-",
        "↓": " down",
        "↑": " up",
        "×": "x",
        "·": "-",
    }
)


def _safe_text(text: str) -> str:
    """시연 콘솔에서 깨지기 쉬운 기호를 ASCII 중심으로 치환한다."""
    return text.translate(_CONSOLE_TRANSLATION)


def _new_request_id() -> str:
    return "REQ-" + datetime.now().strftime("%Y%m%d-%H%M%S")


def cmd_gen_samples(args: argparse.Namespace) -> int:
    hard = getattr(args, "hard", False)
    result = generate_hard_samples() if hard else generate_samples()
    label = "하드(현실 난이도)" if hard else "기본"
    print(f"{label} 샘플 데이터 생성 완료:")
    print(f"  메일: {result['email']}")
    for p in result["excels"]:  # type: ignore[index]
        print(f"  엑셀: {p}")
    if hard:
        exp = result["expected"]  # type: ignore[index]
        print(
            f"  기대 검증결과: {exp['total_rows']}행 중 오류 {exp['error_rows']}행 · "
            f"오류유형 {len(exp['error_types'])}종 · "
            f"자동교정 {exp['self_correction_applied']}/{exp['self_correction_fixable']}건"
        )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    # 입력 결정: 사용자 지정 vs 샘플
    if args.excel:
        subject = args.subject or "(제목 없음)"
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        else:
            body = args.body or ""
        excel_files = args.excel
    elif getattr(args, "hard", False):
        # 하드(현실 난이도) 샘플 사용 — 항상 새로 생성해 최신 상태 보장
        print("[RUN] 하드(현실 난이도) 샘플 세트로 실행합니다.")
        hard = generate_hard_samples()
        subject = MOCK_EMAIL["subject"]
        body = MOCK_EMAIL["body"]
        excel_files = list(hard["excels"])  # type: ignore[arg-type]
    else:
        # 샘플 사용 (없으면 생성)
        if not (SAMPLE_DIR / "개선요청_영업팀.xlsx").exists():
            print("샘플이 없어 새로 생성합니다...")
            generate_samples()
        subject = MOCK_EMAIL["subject"]
        body = MOCK_EMAIL["body"]
        excel_files = [
            str(SAMPLE_DIR / "개선요청_영업팀.xlsx"),
            str(SAMPLE_DIR / "개선요청_생산팀.xlsx"),
            str(SAMPLE_DIR / "개선요청_품질팀.xlsx"),
        ]

    prefer_llm = not args.no_llm
    if prefer_llm and not settings.azure_ready:
        print("[INFO] Azure 키 미설정 -> 메일 분석은 휴리스틱으로 동작합니다.\n")

    request_id = _new_request_id()
    if args.graph:
        from smart_collect.graph import run_collection_graph

        print("[RUN] LangGraph Multi-Agent 워크플로우로 실행합니다.\n")
        state = run_collection_graph(request_id, subject, body, excel_files)
    else:
        state = run_collection(
            request_id, subject, body, excel_files, prefer_llm=prefer_llm
        )

    print("\n" + _safe_text(state.result_summary or "(요약 없음)"))

    if args.json:
        out = {
            "request_id": state.request_id,
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
            "agent_handoff_history": state.agent_handoff_history,
        }
        print("\n[JSON]")
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_demo(_args: argparse.Namespace) -> int:
    """시연 영상용 데모: 시나리오 → 고수준 추론 로그 → 결과 → 실측 KPI."""
    from smart_collect.graph import run_collection_graph

    if not (SAMPLE_DIR / "개선요청_영업팀.xlsx").exists():
        generate_samples()
    excels = [
        str(SAMPLE_DIR / "개선요청_영업팀.xlsx"),
        str(SAMPLE_DIR / "개선요청_생산팀.xlsx"),
        str(SAMPLE_DIR / "개선요청_품질팀.xlsx"),
    ]

    print("\n" + "=" * 60)
    print("  [시나리오] 2026년 6월 시스템 개선요청 취합 메일 + 부서 엑셀 3개")
    print("  -> 메일 분석 -> ToT 규칙선택 -> 검증 -> Self-Correction -> 병합/보고")
    print("=" * 60)

    state = run_collection_graph(
        _new_request_id(), MOCK_EMAIL["subject"], MOCK_EMAIL["body"], excels
    )

    print("\n---------- 고수준 추론 로그 (Agent Reasoning) ----------")
    for line in state.reasoning_log:
        print("  " + _safe_text(line))

    print("\n" + _safe_text(state.result_summary or ""))

    print("\n\n" + "=" * 60)
    print("  [정량 검증] 라벨링 데이터셋 실측 벤치마크")
    print("=" * 60)
    from smart_collect.benchmark import _print_table, run_benchmark

    _print_table(run_benchmark())
    return 0


def _sample_excels() -> list[str]:
    if not (SAMPLE_DIR / "개선요청_영업팀.xlsx").exists():
        generate_samples()
    return [
        str(SAMPLE_DIR / "개선요청_영업팀.xlsx"),
        str(SAMPLE_DIR / "개선요청_생산팀.xlsx"),
        str(SAMPLE_DIR / "개선요청_품질팀.xlsx"),
    ]


def cmd_inbox(args: argparse.Namespace) -> int:
    """수신함 수집·분류·초안 생성 (Phase A). 기본 mock 수신함."""
    from smart_collect.config import settings as _settings
    from smart_collect.inbox_pipeline import ingest_inbox

    prefer_llm = not args.no_llm
    print(f"[INBOX] 수신함 수집 (read_mode={_settings.email_read_mode})")
    if _settings.email_read_mode != "gmail":
        print("  * mock 수신함 사용 중 — 실제 Gmail 읽기는 EMAIL_READ_MODE=gmail + credentials 필요\n")

    result = ingest_inbox(prefer_llm=prefer_llm)
    print(f"수집 {result['fetched']}건 · 신규 처리 {result['processed_new']}건 · "
          f"중복 건너뜀 {result['skipped']}건")
    print("상태별:", ", ".join(f"{k}={v}" for k, v in result["by_status"].items()))
    print("\n[검토 큐]")
    for r in result["queue"]:
        tag = {"draft_ready": "초안생성", "needs_review": "확인필요",
               "general": "일반", "sent": "발송됨", "error": "오류"}.get(r["status"], r["status"])
        line = (f"  - [{tag}] ({r['classification']} {int(r['confidence']*100)}%) "
                f"{r['subject']}  ← {r['sender']}")
        print(_safe_text(line))
        if r["status"] == "draft_ready":
            to = ", ".join(c["email"] for c in r["recipients"])
            print(_safe_text(f"        초안: {r['draft_subject']}  → {to}"))
    return 0


def cmd_update_fields(args: argparse.Namespace) -> int:
    """공통 항목 일괄 수정 (#7)."""
    from smart_collect.tools.excel_tools import update_common_fields

    excels = args.excel or _sample_excels()
    r = update_common_fields(excels, args.field, args.new, old_value=args.old)
    print(f"공통항목 일괄수정: '{args.field}' -> '{args.new}'"
          + (f" (기존 '{args.old}'만)" if args.old else " (전체)"))
    print(f"  변경 셀: {r['update_count']}개 / 파일 {len(r['updated_files'])}개")
    for d in r["details"]:
        print(f"   - {d['file']}: {d['updated_cells']}셀 -> {d['output']}")
    return 0


def cmd_guide(args: argparse.Namespace) -> int:
    """작성 가이드 + 요청 메일 초안 생성 (#2, #3)."""
    from smart_collect.tools.guide_tools import create_request_mail, generate_writing_guide
    from smart_collect.tools.requirement_tools import analyze_collection_email
    from smart_collect.tools.submission_tools import SAMPLE_RECIPIENTS

    req = analyze_collection_email(MOCK_EMAIL["subject"], MOCK_EMAIL["body"], prefer_llm=not args.no_llm)
    g = generate_writing_guide(req)
    print("=== 작성 가이드 ===")
    print("제목:", g["guide_title"])
    print(g["guide_body"])
    m = create_request_mail(g["guide_body"], SAMPLE_RECIPIENTS, req.deadline, "취합양식.xlsx")
    print("\n=== 요청 메일 초안 (발송 전 승인 필요) ===")
    print("제목:", m["mail_subject"])
    print(m["mail_body"])
    return 0


def cmd_track(args: argparse.Namespace) -> int:
    """제출 현황 추적 + 미제출자 리마인드 (#5, #6)."""
    from smart_collect.tools.guide_tools import generate_reminder_message
    from smart_collect.tools.submission_tools import (
        SAMPLE_RECIPIENTS,
        submissions_from_files,
        track_submission_status,
    )

    # 데모: 물류팀은 미제출 상태 (샘플 3개만 제출)
    subs = submissions_from_files(_sample_excels(), submitted_at="2026-06-12 14:00")
    st = track_submission_status(SAMPLE_RECIPIENTS, subs, deadline=args.deadline)
    print("=== 제출 현황 ===")
    print(st["summary"])
    for m in st["missing_list"]:
        print(f"   - 미제출: {m['name']} / {m['dept']} / {m['email']}")
    if st["missing_list"]:
        rem = generate_reminder_message(st["missing_list"], args.deadline)
        print("\n=== 미제출자 리마인드 초안 (발송 전 승인 필요) ===")
        print("제목:", rem["reminder_mail_subject"])
        print(rem["reminder_mail_body"])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="smart-collect", description="엑셀 취합 자동화 PoC")
    sub = parser.add_subparsers(dest="command", required=True)

    p_demo = sub.add_parser("demo", help="시연 영상용 종합 데모")
    p_demo.set_defaults(func=cmd_demo)

    p_uf = sub.add_parser("update-fields", help="공통 항목 일괄 수정")
    p_uf.add_argument("--field", required=True, help="대상 컬럼명")
    p_uf.add_argument("--new", required=True, help="새 값")
    p_uf.add_argument("--old", help="이 값과 일치하는 셀만 (생략 시 전체)")
    p_uf.add_argument("--excel", nargs="+", help="대상 엑셀들 (생략 시 샘플)")
    p_uf.set_defaults(func=cmd_update_fields)

    p_g = sub.add_parser("guide", help="작성 가이드 + 요청 메일 초안")
    p_g.add_argument("--no-llm", action="store_true")
    p_g.set_defaults(func=cmd_guide)

    p_t = sub.add_parser("track", help="제출 현황 추적 + 리마인드")
    p_t.add_argument("--deadline", default="2026-06-12 17:00")
    p_t.set_defaults(func=cmd_track)

    p_in = sub.add_parser("inbox", help="수신함 수집·분류·초안 생성 (Phase A)")
    p_in.add_argument("--no-llm", action="store_true", help="LLM 미사용(휴리스틱)")
    p_in.set_defaults(func=cmd_inbox)

    p_gen = sub.add_parser("gen-samples", help="샘플 메일/엑셀 생성")
    p_gen.add_argument(
        "--hard", action="store_true", help="현실 난이도 하드 샘플 생성(오류 5종·스키마 드리프트)"
    )
    p_gen.set_defaults(func=cmd_gen_samples)

    p_run = sub.add_parser("run", help="취합 검증/병합 실행")
    p_run.add_argument("--subject", help="메일 제목")
    p_run.add_argument("--body", help="메일 본문 (직접 입력)")
    p_run.add_argument("--body-file", help="메일 본문 텍스트 파일 경로")
    p_run.add_argument("--excel", nargs="+", help="제출 엑셀 파일 경로들")
    p_run.add_argument("--no-llm", action="store_true", help="LLM 미사용(휴리스틱)")
    p_run.add_argument("--graph", action="store_true", help="LangGraph 워크플로우로 실행")
    p_run.add_argument(
        "--hard", action="store_true", help="하드(현실 난이도) 샘플 세트로 실행"
    )
    p_run.add_argument("--json", action="store_true", help="JSON 결과도 출력")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
