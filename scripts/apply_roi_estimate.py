"""분석적 추정 ROI를 실측 벤치마크와 분리된 JSON으로 산출한다.

추정값이 ``roi_benchmark_llm.json``에 섞이면 발표자가 실측으로 오인할 수 있으므로
이 스크립트는 ``data/roi_estimate.json``만 갱신한다. 실측 결과의
``roi_claim_available``에는 절대 손대지 않는다.
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from smart_collect.benchmark_roi import _roi  # noqa: E402

TARGET = ROOT / "data" / "roi_benchmark_llm.json"
ESTIMATE_CSV = ROOT / "data" / "manual_time_estimate.csv"
OUTPUT = ROOT / "data" / "roi_estimate.json"


def _read_analytical_estimate() -> dict:
    measurements = []
    with ESTIMATE_CSV.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            minutes = float(row["active_minutes"])
            count = int(row.get("scenario_count") or 1)
            measurements.append(minutes * 60 / count)
    if not measurements:
        raise SystemExit("추정 CSV를 읽지 못했습니다.")
    return {
        "n": len(measurements),
        "median_seconds_per_scenario": round(statistics.median(measurements), 2),
        "min_seconds_per_scenario": round(min(measurements), 2),
        "max_seconds_per_scenario": round(max(measurements), 2),
        "evidence": "analytical_estimate",
        "disclaimer": "스톱워치 실측 아님 — 작업 분해 기반 추정",
        "methodology_doc": "docs/roi_manual_estimate.md",
    }


def main() -> int:
    data = json.loads(TARGET.read_text(encoding="utf-8"))
    manual = _read_analytical_estimate()
    agentic = next(a for a in data["architectures"]
                   if a["architecture"] == "agentic_supervisor_graph")
    roi = _roi(manual, agentic)
    roi = {**roi, "evidence": "analytical_estimate",
           "note": "사람 시간만 추정, Agent 시간은 실측(agentic_supervisor_graph.e2e_batch_seconds)"}

    estimate = {
        "benchmark_source": str(TARGET.relative_to(ROOT)).replace("\\", "/"),
        "evidence_level": "analytical_estimate_only",
        "presentation_claim_allowed": False,
        "manual_time_estimate": manual,
        "roi_estimated": roi,
    }
    OUTPUT.write_text(json.dumps(estimate, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(estimate, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
