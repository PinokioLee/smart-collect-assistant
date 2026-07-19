"""분석적 추정 사람 시간을 기존 roi_benchmark_llm.json에 '추정 ROI'로 주입한다.

측정(roi/roi_claim_available)은 건드리지 않는다 — 실측이 없으면 여전히 false.
대신 roi_estimated/manual_time_estimate 키로 '분석적 추정'임을 명시해 붙인다.
benchmark_roi.py의 함수를 그대로 재사용하므로 계산식은 실측 경로와 동일하다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from smart_collect.benchmark_roi import _manual_measurements, _roi  # noqa: E402

TARGET = ROOT / "data" / "roi_benchmark_llm.json"
ESTIMATE_CSV = ROOT / "data" / "manual_time_estimate.csv"


def main() -> int:
    data = json.loads(TARGET.read_text(encoding="utf-8"))
    manual = _manual_measurements(str(ESTIMATE_CSV))
    if manual is None:
        raise SystemExit("추정 CSV를 읽지 못했습니다.")
    manual = {**manual, "evidence": "analytical_estimate",
              "disclaimer": "스톱워치 실측 아님 — 작업 분해 기반 추정",
              "methodology_doc": "docs/roi_manual_estimate.md"}
    agentic = next(a for a in data["architectures"]
                   if a["architecture"] == "agentic_supervisor_graph")
    roi = _roi(manual, agentic)
    roi = {**roi, "evidence": "analytical_estimate",
           "note": "사람 시간만 추정, Agent 시간은 실측(agentic_supervisor_graph.e2e_batch_seconds)"}

    data["manual_time_estimate"] = manual
    data["roi_estimated"] = roi
    # 실측 ROI는 여전히 없음을 정직하게 유지
    data.setdefault("roi", None)
    data.setdefault("roi_claim_available", False)

    TARGET.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manual_time_estimate": manual, "roi_estimated": roi},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
