from smart_collect.benchmark_roi import run_roi_benchmark


def test_agentic_benchmark_outperforms_fixed_and_sequential_without_fake_roi():
    result = run_roi_benchmark(use_llm=False)
    scores = {
        row["architecture"]: row["workflow_success_rate"]
        for row in result["architectures"]
    }
    assert scores["agentic_supervisor_graph"] > scores["llm_fixed_workflow"]
    assert scores["llm_fixed_workflow"] > scores["rule_sequential"]
    assert result["evidence_level"] == "actual_workflow_execution"
    assert all(row["execution_mode"] == "actual_code_path" for row in result["architectures"])
    agentic = next(row for row in result["architectures"] if row["architecture"] == "agentic_supervisor_graph")
    fixed = next(row for row in result["architectures"] if row["architecture"] == "llm_fixed_workflow")
    rule = next(row for row in result["architectures"] if row["architecture"] == "rule_sequential")
    orphan = next(row for row in agentic["details"] if row["id"] == "orphan")
    fixed_reminder = next(row for row in fixed["details"] if row["id"] == "reminder")
    assert orphan["trace_steps"] >= 4
    assert fixed_reminder["success"] is True  # capability parity: deadline은 두 비교군 모두 보유
    assert fixed["failure_recovery_cases"] == agentic["failure_recovery_cases"] == 3
    assert fixed["failure_recovery_rate"] == 0
    assert agentic["failure_recovery_rate"] == 1
    assert rule["autonomous_resolution_rate"] <= rule["workflow_success_rate"]
    assert all(
        row["autonomous_resolution_rate"] <= row["workflow_success_rate"]
        for row in result["architectures"]
    )
    assert result["manual_time_study"] is None
    assert result["roi_claim_available"] is False


def test_manual_time_is_calculated_only_from_supplied_measurements(tmp_path):
    csv_path = tmp_path / "manual.csv"
    csv_path.write_text("run,active_minutes\n1,20\n2,24\n3,22\n", encoding="utf-8")
    result = run_roi_benchmark(manual_csv=str(csv_path))
    assert result["manual_time_study"]["n"] == 3
    assert result["manual_time_study"]["median_active_minutes"] == 22
    assert result["roi_claim_available"] is True


def test_estimate_or_fewer_than_three_runs_never_becomes_measured_roi(tmp_path):
    estimate = tmp_path / "estimate.csv"
    estimate.write_text(
        "run,participant,scenario_count,active_minutes,notes\n"
        "1,ESTIMATE,12,39,analytical-estimate\n"
        "2,ESTIMATE,12,38,analytical-estimate\n"
        "3,ESTIMATE,12,40,analytical-estimate\n",
        encoding="utf-8",
    )
    estimated_result = run_roi_benchmark(manual_csv=str(estimate))
    assert estimated_result["manual_time_study"] is None
    assert estimated_result["roi_claim_available"] is False
    assert estimated_result["manual_measurement_status"] == "rejected_or_insufficient"

    short = tmp_path / "short.csv"
    short.write_text("run,active_minutes\n1,20\n2,21\n", encoding="utf-8")
    short_result = run_roi_benchmark(manual_csv=str(short))
    assert short_result["roi_claim_available"] is False
