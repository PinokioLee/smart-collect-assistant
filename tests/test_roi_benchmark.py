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
    orphan = next(row for row in agentic["details"] if row["id"] == "orphan")
    assert orphan["trace_steps"] >= 4
    assert result["manual_time_study"] is None
    assert result["roi_claim_available"] is False


def test_manual_time_is_calculated_only_from_supplied_measurements(tmp_path):
    csv_path = tmp_path / "manual.csv"
    csv_path.write_text("run,active_minutes\n1,20\n2,24\n3,22\n", encoding="utf-8")
    result = run_roi_benchmark(manual_csv=str(csv_path))
    assert result["manual_time_study"]["n"] == 3
    assert result["manual_time_study"]["median_active_minutes"] == 22
    assert result["roi_claim_available"] is True
