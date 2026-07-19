from smart_collect.benchmark_classifier import CASES, run


def test_classifier_benchmark_executes_real_heuristic_path():
    result = run(use_llm=False)
    heuristic = result["results"][0]
    assert result["evidence_level"] == "actual_classifier_execution"
    assert heuristic["case_count"] == len(CASES) == 24
    assert heuristic["actual_llm_responses"] == 0
    assert all("predicted" in row for row in heuristic["details"])
