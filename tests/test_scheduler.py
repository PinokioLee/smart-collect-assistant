"""자동 수집 스케줄 설정 검증 테스트 (Phase C).

잡을 실제로 돌리지 않고 설정 정규화·검증 로직만 확인한다(부수효과 없음).
"""

import pytest

from smart_collect import scheduler as sch


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    # 실제 data/ 를 건드리지 않도록 설정 파일 경로를 임시로 바꾼다.
    monkeypatch.setattr(sch, "CONFIG_PATH", tmp_path / "schedule_config.json")


def test_times_mode_normalizes_and_sorts():
    cfg = sch.normalize_config(
        {"enabled": True, "mode": "times", "times": ["19:00", "09:00", "14:00", "09:00"]}
    )
    assert cfg["enabled"] is True
    assert cfg["mode"] == "times"
    assert cfg["times"] == ["09:00", "14:00", "19:00"]  # 중복 제거 + 정렬


def test_interval_mode_validates_range():
    cfg = sch.normalize_config({"mode": "interval", "interval_hours": 1})
    assert cfg["interval_hours"] == 1
    with pytest.raises(ValueError):
        sch.normalize_config({"mode": "interval", "interval_hours": 0})
    with pytest.raises(ValueError):
        sch.normalize_config({"mode": "interval", "interval_hours": 999})


def test_weekly_mode_validates():
    cfg = sch.normalize_config({"mode": "weekly", "weekday": 2, "weekly_time": "08:30"})
    assert cfg["weekday"] == 2 and cfg["weekly_time"] == "08:30"
    with pytest.raises(ValueError):
        sch.normalize_config({"mode": "weekly", "weekday": 9, "weekly_time": "08:30"})


def test_invalid_time_and_mode_rejected():
    with pytest.raises(ValueError):
        sch.normalize_config({"mode": "times", "times": ["25:00"]})
    with pytest.raises(ValueError):
        sch.normalize_config({"mode": "times", "times": []})
    with pytest.raises(ValueError):
        sch.normalize_config({"mode": "hourly"})  # 지원하지 않는 mode


def test_save_and_load_roundtrip():
    cfg = sch.normalize_config(
        {"enabled": True, "mode": "times", "times": ["09:00", "14:00", "19:00"]}
    )
    sch.save_config(cfg)
    loaded = sch.load_config()
    assert loaded["enabled"] is True
    assert loaded["times"] == ["09:00", "14:00", "19:00"]


def test_status_shape_without_scheduler_running():
    st = sch.status()
    assert "config" in st and "next_runs" in st and "running" in st
    assert set(st["config"]) >= {"enabled", "mode", "times", "interval_hours"}
