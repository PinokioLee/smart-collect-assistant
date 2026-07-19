import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).parents[1] / "scripts" / "manual_roi_timer.py"
    spec = importlib.util.spec_from_file_location("manual_roi_timer", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_append_measurement_creates_reusable_csv(tmp_path):
    timer = _module()
    output = tmp_path / "manual.csv"
    first = timer.append_measurement(
        output, participant="P01", scenario_count=12, elapsed_seconds=600,
    )
    second = timer.append_measurement(
        output, participant="P02", scenario_count=12, elapsed_seconds=720,
    )
    assert first["run"] == 1
    assert second["run"] == 2
    text = output.read_text(encoding="utf-8-sig")
    assert "P01" in text and "P02" in text
