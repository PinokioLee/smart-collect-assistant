"""핵심 기술 결정 실측 근거 — 엑셀 검증을 LLM 직접 판단(A)으로 할지, 규칙 기반 코드(B)로 할지 비교한다.

benchmark.py 의 라벨링 데이터셋(정답 오류 포함)을 그대로 사용해, 같은 데이터로
(A) Azure OpenAI 직접 판단과 (B) pandas/openpyxl 규칙 기반 코드의 검출 정확도(F1)·
재현성(반복 시 표준편차)·처리 속도를 공정하게 비교한다.

작은 규모(4파일/44행/오류10건)와 실무에 가까운 큰 규모(8파일/130행/오류26건) 두 가지로 측정한다.

실행: python -m backend.smart_collect.llm_vs_rule_benchmark
  (Azure OpenAI 호출이 발생한다 — settings.azure_ready 가 False 면 LLM 측정은 건너뛴다.)

결과는 data/llm_vs_rule_benchmark.json, data/llm_vs_rule_benchmark_large.json 에 저장된다.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import pandas as pd

from .benchmark import COLUMNS, _rule, build_labeled_dataset, measure_detection_accuracy, measure_reproducibility
from .config import DATA_DIR, SAMPLE_DIR, ensure_dirs, settings
from .llm import chat

TEAMS_LARGE = ["영업1팀", "영업2팀", "생산1팀", "생산2팀", "품질팀", "물류팀", "구매팀", "개발팀"]
SYSTEMS_LARGE = ["ERP", "MES", "WMS", "CRM", "QMS", "LIMS", "PLM", "SCM"]

SYSTEM_PROMPT = """당신은 회사 취합 엑셀 데이터를 검증하는 Excel Validation Agent입니다.
아래 규칙에 따라 각 파일의 데이터 행에서 오류를 찾아 JSON 배열로만 응답하세요.

규칙:
1. 필수 입력 컬럼: 부서명, 담당자, 요청시스템, 긴급도 (비어 있으면 "필수값 누락")
2. 요청일자 컬럼은 YYYY-MM-DD 형식이어야 함 (아니면 "날짜 형식 오류")
3. 긴급도 컬럼은 "상"/"중"/"하" 중 하나여야 함 (아니면 "허용되지 않은 코드값")
4. 부서명+요청시스템+개선요청내용 조합이 다른 행과 완전히 동일하면 "중복 데이터" (나중에 나온 행에 표시)

각 오류를 {"file": 파일명, "row": 엑셀행번호, "error_type": 위 4종 중 하나} 형태로 JSON 배열에 담아
다른 설명 없이 JSON 배열만 출력하세요. 오류가 없으면 빈 배열 []을 출력하세요."""


def build_large_labeled_dataset(bench_dir: Path, n_files: int = 8, n_clean_per_file: int = 13):
    """실무 규모(기본 8파일/130행/오류26건) 라벨링 데이터셋을 만든다."""
    bench_dir.mkdir(parents=True, exist_ok=True)
    ground_truth: set[tuple] = set()
    paths: list[str] = []
    g = 0
    first_clean_row = None

    for fi in range(n_files):
        fname = f"bench_large_{fi:02d}.xlsx"
        rows: list[list[str]] = []
        for _ in range(n_clean_per_file):
            row = [TEAMS_LARGE[g % len(TEAMS_LARGE)], f"담당{g}", SYSTEMS_LARGE[g % len(SYSTEMS_LARGE)],
                   f"개선요청{g}", ["상", "중", "하"][g % 3], f"사유{g}", "2026-06-05"]
            rows.append(row)
            if first_clean_row is None:
                first_clean_row = list(row)
            g += 1
        errs = [
            ("담당자" if fi % 2 == 0 else "부서명", "필수값 누락", ""),
            ("긴급도", "허용되지 않은 코드값", ["매우급함", "긴급", "높음", "위험"][fi % 4]),
            ("요청일자", "날짜 형식 오류", ["2026/06/05", "06-05-2026", "2026.6.5", "06/05/2026"][fi % 4]),
        ]
        for col, etype, bad in errs:
            r = [TEAMS_LARGE[g % len(TEAMS_LARGE)], f"담당{g}", SYSTEMS_LARGE[g % len(SYSTEMS_LARGE)],
                 f"개선요청{g}", "중", f"사유{g}", "2026-06-05"]
            r[COLUMNS.index(col)] = bad
            rows.append(r)
            ground_truth.add((fname, len(rows) + 1, etype))
            g += 1

        path = bench_dir / fname
        pd.DataFrame(rows, columns=COLUMNS).to_excel(path, index=False, engine="openpyxl")
        paths.append(str(path))

    for last in paths[-2:]:
        df = pd.read_excel(last, dtype=str, engine="openpyxl")
        df.loc[len(df)] = first_clean_row
        dup_row = len(df) + 1
        df.to_excel(last, index=False, engine="openpyxl")
        ground_truth.add((Path(last).name, dup_row, "중복 데이터"))

    return paths, ground_truth


def _rows_to_text(path: str) -> str:
    df = pd.read_excel(path, dtype=str, engine="openpyxl").fillna("")
    lines = [f"[파일: {Path(path).name}]", ",".join(COLUMNS)]
    for idx, row in df.iterrows():
        excel_row = idx + 2
        lines.append(f"행{excel_row}: " + ",".join(str(row[c]) for c in COLUMNS))
    return "\n".join(lines)


def _extract_json_array(text: str | None):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("["):]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []


def run_llm_validation(paths: list[str], ground_truth: set[tuple], runs: int) -> dict:
    """(A) Azure OpenAI 로 같은 데이터를 직접 판단시켜 정확도·재현성·속도를 측정한다."""
    user_content = "\n\n".join(_rows_to_text(p) for p in paths)
    gt = {(f, r, t) for (f, r, t) in ground_truth}

    detected_counts, times_ms, f1s, precisions, recalls = [], [], [], [], []

    for _ in range(runs):
        t0 = time.perf_counter()
        content = chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
        )
        times_ms.append((time.perf_counter() - t0) * 1000)

        detected = set()
        for it in _extract_json_array(content):
            try:
                detected.add((str(it["file"]), int(it["row"]), str(it["error_type"])))
            except (KeyError, TypeError, ValueError):
                continue

        tp = len(detected & gt)
        fp = len(detected - gt)
        fn = len(gt - detected)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        detected_counts.append(len(detected))
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)

    return {
        "runs": runs,
        "ground_truth_errors": len(gt),
        "detected_count_mean": statistics.mean(detected_counts),
        "detected_count_stdev": round(statistics.pstdev(detected_counts), 4),
        "precision_mean": round(statistics.mean(precisions), 4),
        "recall_mean": round(statistics.mean(recalls), 4),
        "f1_mean": round(statistics.mean(f1s), 4),
        "f1_stdev": round(statistics.pstdev(f1s), 4),
        "time_mean_ms": round(statistics.mean(times_ms), 1),
        "time_stdev_ms": round(statistics.pstdev(times_ms), 1),
        "per_run_detected_counts": detected_counts,
        "per_run_f1": [round(x, 4) for x in f1s],
    }


def _compare(paths, gt, rules, *, llm_runs: int, rule_repro_runs: int = 10) -> dict:
    total_rows = sum(len(pd.read_excel(p)) for p in paths)
    result: dict = {
        "dataset": {"files": len(paths), "total_rows": total_rows, "ground_truth_errors": len(gt)},
    }
    if settings.azure_ready:
        result["llm_direct_validation"] = run_llm_validation(paths, gt, runs=llm_runs)
    else:
        result["llm_direct_validation"] = None  # Azure 미설정 시 측정 생략

    rule_detection = measure_detection_accuracy(paths, gt, rules)
    rule_repro = measure_reproducibility(paths, rules, runs=rule_repro_runs)
    result["rule_based_validation"] = {"detection": rule_detection, "reproducibility": rule_repro}
    return result


def run_all() -> dict:
    ensure_dirs()
    bench_dir = SAMPLE_DIR / "benchmark"
    rules = _rule()

    small_paths, small_gt = build_labeled_dataset(bench_dir)
    small = _compare(small_paths, small_gt, rules, llm_runs=5)
    (DATA_DIR / "llm_vs_rule_benchmark.json").write_text(
        json.dumps(small, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    large_paths, large_gt = build_large_labeled_dataset(bench_dir)
    large = _compare(large_paths, large_gt, rules, llm_runs=3)
    (DATA_DIR / "llm_vs_rule_benchmark_large.json").write_text(
        json.dumps(large, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {"small": small, "large": large}


if __name__ == "__main__":
    out = run_all()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n저장: {DATA_DIR / 'llm_vs_rule_benchmark.json'}")
    print(f"저장: {DATA_DIR / 'llm_vs_rule_benchmark_large.json'}")
