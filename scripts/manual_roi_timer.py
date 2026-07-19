"""수작업 Before 시간 실측 도구.

취합 담당자가 동일한 통제 시나리오를 직접 처리하는 능동 작업시간을 측정해
benchmark_roi.py가 읽을 수 있는 CSV에 누적한다.
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime
from pathlib import Path


FIELDS = ["run", "participant", "scenario_count", "active_minutes", "measured_at", "notes"]


def append_measurement(
    output: Path,
    *,
    participant: str,
    scenario_count: int,
    elapsed_seconds: float,
    notes: str = "",
) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if output.exists():
        with output.open(encoding="utf-8-sig", newline="") as file:
            existing = list(csv.DictReader(file))
    row = {
        "run": len(existing) + 1,
        "participant": participant,
        "scenario_count": scenario_count,
        "active_minutes": round(elapsed_seconds / 60, 3),
        "measured_at": datetime.now().isoformat(timespec="seconds"),
        "notes": notes,
    }
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(existing)
        writer.writerow(row)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Smart Collect 수작업 Before 시간 실측")
    parser.add_argument("--participant", required=True, help="익명 참여자 ID (예: P01)")
    parser.add_argument("--scenario-count", type=int, default=12)
    parser.add_argument("--notes", default="")
    parser.add_argument("--output", default="data/manual_time_measurements.csv")
    args = parser.parse_args()
    if args.scenario_count <= 0:
        parser.error("--scenario-count는 1 이상이어야 합니다.")

    print("통제 시나리오의 메일 확인, Excel 검증, 반려/승인 판단을 수작업으로 수행합니다.")
    input("준비되면 Enter를 눌러 측정을 시작하세요: ")
    started = time.perf_counter()
    input("모든 시나리오 처리가 끝나면 Enter를 누르세요: ")
    elapsed = time.perf_counter() - started
    row = append_measurement(
        Path(args.output),
        participant=args.participant,
        scenario_count=args.scenario_count,
        elapsed_seconds=elapsed,
        notes=args.notes,
    )
    print(f"저장 완료: {args.output} / {row['active_minutes']}분")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
