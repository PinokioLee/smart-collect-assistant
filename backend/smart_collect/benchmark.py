"""실측 벤치마크 — 발표용 정량 지표를 재현 가능하게 산출한다.

측정 항목
  1) 검출 정확도   : 라벨링된 데이터셋에서 오류 검출 Precision/Recall/F1
  2) 재현성        : 동일 입력 N회 반복 시 오류 수 표준편차(결정론 → 0)
  3) 처리 속도     : 자동 처리 시간(실측) vs 현행 수동(설계서 기준) 단축률·배수
  4) 자동 교정율   : Self-Correction 으로 자동 복구된 비율
  5) ToT 변별력    : 스키마 드리프트 시 과잉 필수규칙의 오탐을 회피한 건수

실행: python backend/benchmark.py   (결과는 data/benchmark_metrics.json 에도 저장)
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import pandas as pd

from .config import DATA_DIR, SAMPLE_DIR, ensure_dirs
from .state import ExtractedRequirements
from .tools import excel_tools as ex
from .tools.requirement_tools import build_validation_rules
from .tools.self_correction import run_self_correction
from .tools.tot_rules import evaluate_candidate, generate_candidates

COLUMNS = ["부서명", "담당자", "요청시스템", "개선요청내용", "긴급도", "요청사유", "요청일자"]
TEAMS = ["영업1팀", "영업2팀", "생산1팀", "생산2팀", "품질팀", "물류팀"]
SYSTEMS = ["ERP", "MES", "WMS", "CRM", "QMS", "LIMS", "PLM", "SCM"]

# 현행 수동 검토 추정(투명한 공식): 파일 1개 열람 60초 + 행 1개당 4종 규칙
# 육안 점검·오류기록 15초. 설계서의 '최종 취합 90분/건'과도 정합적인 보수적 추정.
MANUAL_SECONDS_PER_FILE = 60
MANUAL_SECONDS_PER_ROW = 15


def _rule() -> tuple:
    rules = build_validation_rules(
        ExtractedRequirements(required_fields=COLUMNS, cautions=[
            "부서명, 담당자, 요청시스템, 긴급도는 필수 입력 항목입니다."
        ])
    )
    return rules


def build_labeled_dataset(bench_dir: Path) -> tuple[list[str], set[tuple]]:
    """라벨(정답) 오류를 심은 4개 엑셀을 생성한다.

    모든 행의 (부서명,요청시스템,개선요청내용)을 전역 유니크로 만들어
    '의도치 않은 중복'을 배제한다. 중복 오류는 마지막에 의도적으로만 주입한다.

    Returns: (파일경로들, ground_truth 오류집합{(file,row,error_type)})
    """
    bench_dir.mkdir(parents=True, exist_ok=True)
    ground_truth: set[tuple] = set()
    paths: list[str] = []
    g = 0  # 전역 유니크 카운터 (개선요청내용)

    # 파일별 (정상행수, 심을 단일셀 오류[(컬럼,오류유형,값)])
    plans = {
        "bench_영업팀.xlsx": (9, [("요청시스템", "필수값 누락", ""),
                                  ("긴급도", "허용되지 않은 코드값", "매우높음")]),
        "bench_생산팀.xlsx": (9, [("담당자", "필수값 누락", ""),
                                  ("요청일자", "날짜 형식 오류", "2026.06.05")]),
        "bench_품질팀.xlsx": (9, [("긴급도", "허용되지 않은 코드값", "긴급"),
                                  ("요청일자", "날짜 형식 오류", "06/05/2026"),
                                  ("부서명", "필수값 누락", "")]),
        "bench_물류팀.xlsx": (9, [("요청일자", "날짜 형식 오류", "2026/6/5"),
                                  ("긴급도", "허용되지 않은 코드값", "낮음정도")]),
    }

    first_clean_row = None  # 의도적 중복 주입용

    for fname, (n_clean, errors) in plans.items():
        rows: list[list[str]] = []
        for _ in range(n_clean):
            row = [TEAMS[g % len(TEAMS)], f"담당{g}", SYSTEMS[g % len(SYSTEMS)],
                   f"개선요청{g}", ["상", "중", "하"][g % 3], f"사유{g}", "2026-06-05"]
            rows.append(row)
            if first_clean_row is None:
                first_clean_row = list(row)
            g += 1
        # 단일셀 오류 행 (각 행도 전역 유니크 내용 → 의도외 중복 없음)
        for col, etype, bad in errors:
            r = [TEAMS[g % len(TEAMS)], f"담당{g}", SYSTEMS[g % len(SYSTEMS)],
                 f"개선요청{g}", "중", f"사유{g}", "2026-06-05"]
            r[COLUMNS.index(col)] = bad
            rows.append(r)
            ground_truth.add((fname, len(rows) + 1, etype))
            g += 1

        path = bench_dir / fname
        pd.DataFrame(rows, columns=COLUMNS).to_excel(path, index=False, engine="openpyxl")
        paths.append(str(path))

    # 의도적 중복 1건: 마지막 파일에 첫 정상행과 동일한 행을 추가
    last = paths[-1]
    df = pd.read_excel(last, dtype=str, engine="openpyxl")
    df.loc[len(df)] = first_clean_row
    dup_row = len(df) + 1
    df.to_excel(last, index=False, engine="openpyxl")
    ground_truth.add((Path(last).name, dup_row, "중복 데이터"))

    return paths, ground_truth


def measure_detection_accuracy(paths: list[str], ground_truth: set[tuple], rules) -> dict:
    """검출 Precision/Recall/F1 (오류유형 단위)."""
    loaded = ex.load_excel_files(paths)
    result = ex.validate_excel_data(loaded, rules)
    types = {"필수값 누락", "날짜 형식 오류", "허용되지 않은 코드값", "중복 데이터"}
    detected = {
        (Path(e.file).name, e.row, e.error_type)
        for e in result.error_details
        if e.error_type in types
    }
    gt = {(f, r, t) for (f, r, t) in ground_truth}
    tp = len(detected & gt)
    fp = len(detected - gt)
    fn = len(gt - detected)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "ground_truth_errors": len(gt),
        "detected": len(detected),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def measure_reproducibility(paths: list[str], rules, runs: int = 10) -> dict:
    """동일 입력 N회 반복 — 오류 수 표준편차 + 처리시간 통계."""
    loaded = ex.load_excel_files(paths)
    error_counts: list[int] = []
    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        res = ex.validate_excel_data(loaded, rules)
        times.append(time.perf_counter() - t0)
        error_counts.append(res.error_rows)
    return {
        "runs": runs,
        "error_count_mean": statistics.mean(error_counts),
        "error_count_stdev": statistics.pstdev(error_counts),
        "time_mean_ms": round(statistics.mean(times) * 1000, 2),
        "time_stdev_ms": round(statistics.pstdev(times) * 1000, 3),
    }


def measure_speed(paths: list[str], rules, runs: int = 20) -> dict:
    """엔드투엔드(로드+검증+병합) 처리시간 실측 + 수동 대비 단축률."""
    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        loaded = ex.load_excel_files(paths)
        res = ex.validate_excel_data(loaded, rules)
        out = DATA_DIR / "merged_files" / "bench_tmp_merged.xlsx"
        ex.merge_valid_rows(loaded, res, out, add_metadata=True)
        times.append(time.perf_counter() - t0)
    auto = statistics.median(times)
    loaded = ex.load_excel_files(paths)
    total_rows = sum(len(f.df) for f in loaded)
    manual = len(paths) * MANUAL_SECONDS_PER_FILE + total_rows * MANUAL_SECONDS_PER_ROW
    return {
        "total_rows": total_rows,
        "auto_seconds": round(auto, 4),
        "throughput_rows_per_sec": round(total_rows / auto, 0),
        "manual_estimate_seconds": manual,
        "manual_estimate_min": round(manual / 60, 1),
        "speedup_x": round(manual / auto, 0),
        "reduction_pct": round((1 - auto / manual) * 100, 2),
    }


def measure_self_correction(paths: list[str], rules) -> dict:
    loaded = ex.load_excel_files(paths)
    result = ex.validate_excel_data(loaded, rules)
    sc, _, _ = run_self_correction(loaded, result, rules)
    recovered = sc.errors_before - sc.errors_after
    return {
        "errors_before": sc.errors_before,
        "fixable": sc.fixable_errors,
        "applied": sc.applied_corrections,
        "auto_fix_rate_pct": round(sc.auto_fix_rate * 100, 1),
        "error_rows_recovered": recovered,
        "rework_reduction_pct": round(recovered / sc.errors_before * 100, 1)
        if sc.errors_before else 0.0,
    }


def measure_tot_discrimination() -> dict:
    """스키마 드리프트 시 ToT 가 과잉 필수규칙(Strict)의 오탐을 회피하는지."""
    # 한 파일에 '요청사유' 컬럼이 빠진 상황을 가정 (실제 양식 변형)
    fields = COLUMNS
    req = ExtractedRequirements(required_fields=fields, cautions=[
        "부서명, 담당자, 요청시스템, 긴급도는 필수 입력 항목입니다."
    ])
    actual_columns = set(c for c in COLUMNS if c != "요청사유")  # 드리프트
    cands = generate_candidates(req, "\n".join(req.cautions))
    for c in cands:
        evaluate_candidate(c, actual_columns)
    best = max(cands, key=lambda c: (c.score, len(c.rule.required_columns)))
    strict = next(c for c in cands if c.name == "A.Strict")
    # Strict 가 요구하지만 데이터에 없는 컬럼 = 잠재 오탐(필수 컬럼 누락)
    strict_absent = [c for c in strict.rule.required_columns if c not in actual_columns]
    selected_absent = [c for c in best.rule.required_columns if c not in actual_columns]
    return {
        "scenario": "한 양식에서 '요청사유' 컬럼 누락(드리프트)",
        "candidate_scores": {c.name: c.score for c in cands},
        "selected": best.name,
        "strict_false_positive_cols": strict_absent,
        "selected_false_positive_cols": selected_absent,
        "false_positives_avoided": len(strict_absent) - len(selected_absent),
    }


def run_benchmark() -> dict:
    ensure_dirs()
    bench_dir = SAMPLE_DIR / "benchmark"
    rules = _rule()
    paths, gt = build_labeled_dataset(bench_dir)

    metrics = {
        "dataset": {"files": len(paths), "ground_truth_errors": len(gt)},
        "detection_accuracy": measure_detection_accuracy(paths, gt, rules),
        "reproducibility": measure_reproducibility(paths, rules),
        "speed": measure_speed(paths, rules),
        "self_correction": measure_self_correction(paths, rules),
        "tot_discrimination": measure_tot_discrimination(),
    }
    out = DATA_DIR / "benchmark_metrics.json"
    out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics


def _print_table(m: dict) -> None:
    d = m["detection_accuracy"]
    rep = m["reproducibility"]
    sp = m["speed"]
    sc = m["self_correction"]
    tot = m["tot_discrimination"]
    print("\n" + "=" * 60)
    print("  Smart Collect — 실측 벤치마크 (KPI)")
    print("=" * 60)
    print(f"  데이터셋: {m['dataset']['files']}파일 / 정답오류 {m['dataset']['ground_truth_errors']}건")
    print(f"\n  [1] 검출 정확도  Precision={d['precision']*100:.1f}%  "
          f"Recall={d['recall']*100:.1f}%  F1={d['f1']*100:.1f}%  "
          f"(오탐 {d['false_positive']} / 미탐 {d['false_negative']})")
    print(f"  [2] 재현성       {rep['runs']}회 반복 오류수 표준편차 = {rep['error_count_stdev']:.4f}  "
          f"(처리 {rep['time_mean_ms']:.2f}ms)")
    print(f"  [3] 처리 속도    {sp['total_rows']}행 자동 {sp['auto_seconds']}초 "
          f"({sp['throughput_rows_per_sec']:,.0f}행/초)  vs 수동추정 {sp['manual_estimate_min']}분  "
          f"→ {sp['speedup_x']:,.0f}배 ({sp['reduction_pct']:.1f}%↓)")
    print(f"  [4] 자동 교정    교정율 {sc['auto_fix_rate_pct']:.0f}%  "
          f"오류행 복구 {sc['error_rows_recovered']}건 (재작업 {sc['rework_reduction_pct']:.0f}%↓)")
    print(f"  [5] ToT 변별     {tot['selected']} 선택 → 과잉규칙 오탐 "
          f"{tot['false_positives_avoided']}건 회피 {tot['strict_false_positive_cols']}")
    print("=" * 60)


if __name__ == "__main__":
    m = run_benchmark()
    _print_table(m)
    print(f"\n저장: {DATA_DIR / 'benchmark_metrics.json'}")
