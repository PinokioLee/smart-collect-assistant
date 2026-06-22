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

# backend 패키지 import 경로 보장
sys.path.insert(0, str(Path(__file__).resolve().parent))

from smart_collect.config import SAMPLE_DIR, settings  # noqa: E402
from smart_collect.pipeline import run_collection  # noqa: E402
from smart_collect.sample_data import MOCK_EMAIL, generate_samples  # noqa: E402


def _new_request_id() -> str:
    return "REQ-" + datetime.now().strftime("%Y%m%d-%H%M%S")


def cmd_gen_samples(_args: argparse.Namespace) -> int:
    result = generate_samples()
    print("샘플 데이터 생성 완료:")
    print(f"  메일: {result['email']}")
    for p in result["excels"]:  # type: ignore[index]
        print(f"  엑셀: {p}")
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
        print("ℹ️  Azure 키 미설정 → 메일 분석은 휴리스틱으로 동작합니다.\n")

    request_id = _new_request_id()
    if args.graph:
        from smart_collect.graph import run_collection_graph

        print("⚙️  LangGraph Multi-Agent 워크플로우로 실행합니다.\n")
        state = run_collection_graph(request_id, subject, body, excel_files)
    else:
        state = run_collection(
            request_id, subject, body, excel_files, prefer_llm=prefer_llm
        )

    print("\n" + (state.result_summary or "(요약 없음)"))

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


def main() -> int:
    parser = argparse.ArgumentParser(prog="smart-collect", description="엑셀 취합 자동화 PoC")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("gen-samples", help="샘플 메일/엑셀 생성")
    p_gen.set_defaults(func=cmd_gen_samples)

    p_run = sub.add_parser("run", help="취합 검증/병합 실행")
    p_run.add_argument("--subject", help="메일 제목")
    p_run.add_argument("--body", help="메일 본문 (직접 입력)")
    p_run.add_argument("--body-file", help="메일 본문 텍스트 파일 경로")
    p_run.add_argument("--excel", nargs="+", help="제출 엑셀 파일 경로들")
    p_run.add_argument("--no-llm", action="store_true", help="LLM 미사용(휴리스틱)")
    p_run.add_argument("--graph", action="store_true", help="LangGraph 워크플로우로 실행")
    p_run.add_argument("--json", action="store_true", help="JSON 결과도 출력")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
