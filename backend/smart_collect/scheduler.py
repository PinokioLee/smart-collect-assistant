"""수신함 자동 수집 스케줄러 (Phase C).

사용자가 화면에서 지정한 스케줄대로 ingest_inbox() 를 자동 실행한다.
지원 모드
  - interval : N시간마다 (예: 1시간마다)
  - times    : 매일 지정한 여러 시각 (예: 09:00, 14:00, 19:00)
  - weekly   : 매주 지정 요일·시각 1회

설계 원칙
  - 자동 수집·분류·Worker 실행까지 수행한다. 발송은 LLM 제안만으로 실행하지 않고
    AUTO_SEND_ENABLED, 허용 도메인, 첨부·근거 등 Policy Gate를 모두 통과해야 한다.
  - 스케줄 설정은 파일(data/schedule_config.json)에 저장해 재시작 후에도 유지.
  - APScheduler 미설치/오류 시에도 앱은 정상 동작(스케줄만 비활성).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DATA_DIR

CONFIG_PATH = DATA_DIR / "schedule_config.json"
_TZ = "Asia/Seoul"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "mode": "times",                    # interval | times | weekly
    "interval_hours": 1,                # mode=interval
    "times": ["09:00", "14:00", "19:00"],  # mode=times
    "weekday": 0,                       # mode=weekly (0=월 ... 6=일)
    "weekly_time": "09:00",             # mode=weekly
    "last_run": None,
    "last_summary": None,
    "last_error": None,
    "last_reason": None,
}

_scheduler = None            # APScheduler BackgroundScheduler (지연 생성)
_lock = threading.Lock()     # 동시 실행 방지


# ---------------------------------------------------------------------------
# 설정 파일 입출력
# ---------------------------------------------------------------------------

def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 검증
# ---------------------------------------------------------------------------

def _valid_hhmm(value: str) -> bool:
    try:
        h, m = value.split(":")
        return 0 <= int(h) <= 23 and 0 <= int(m) <= 59
    except (ValueError, AttributeError):
        return False


def normalize_config(incoming: dict[str, Any]) -> dict[str, Any]:
    """사용자 입력을 검증·정규화해 저장 가능한 설정으로 만든다."""
    cfg = load_config()
    cfg["enabled"] = bool(incoming.get("enabled", cfg["enabled"]))
    mode = incoming.get("mode", cfg["mode"])
    if mode not in ("interval", "times", "weekly"):
        raise ValueError("mode 는 interval / times / weekly 중 하나여야 합니다.")
    cfg["mode"] = mode

    if mode == "interval":
        n = int(incoming.get("interval_hours", cfg["interval_hours"]))
        if not (1 <= n <= 168):
            raise ValueError("interval_hours 는 1~168 사이여야 합니다.")
        cfg["interval_hours"] = n
    elif mode == "times":
        times = incoming.get("times", cfg["times"])
        times = [t.strip() for t in times if t and t.strip()]
        if not times:
            raise ValueError("times 에 최소 1개의 시각(HH:MM)이 필요합니다.")
        for t in times:
            if not _valid_hhmm(t):
                raise ValueError(f"잘못된 시각 형식: {t} (HH:MM)")
        cfg["times"] = sorted(dict.fromkeys(times))  # 중복 제거·정렬
    elif mode == "weekly":
        wd = int(incoming.get("weekday", cfg["weekday"]))
        if not (0 <= wd <= 6):
            raise ValueError("weekday 는 0(월)~6(일) 여야 합니다.")
        wt = incoming.get("weekly_time", cfg["weekly_time"])
        if not _valid_hhmm(wt):
            raise ValueError(f"잘못된 시각 형식: {wt}")
        cfg["weekday"] = wd
        cfg["weekly_time"] = wt
    return cfg


# ---------------------------------------------------------------------------
# 스케줄러
# ---------------------------------------------------------------------------

def _get_scheduler():
    global _scheduler
    if _scheduler is None:
        from apscheduler.schedulers.background import BackgroundScheduler

        _scheduler = BackgroundScheduler(timezone=_TZ)
    return _scheduler


def _run_job(reason: str = "schedule") -> dict[str, Any]:
    """수신함 수집·분류·Agent 실행 1회(스케줄/수동 공용)."""
    if not _lock.acquire(blocking=False):
        return {"skipped": "이미 실행 중"}
    try:
        from .inbox_pipeline import ingest_inbox
        from .deadline_agent import run_deadline_agent

        result = ingest_inbox()
        deadline_result = run_deadline_agent()
        summary = {
            "fetched": result["fetched"],
            "processed_new": result["processed_new"],
            "by_status": result["by_status"],
            "by_category": result.get("by_category", {}),
            "automation": result.get("automation", {}),
            "deadline_agent": deadline_result,
        }
        cfg = load_config()
        cfg["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cfg["last_summary"] = summary
        cfg["last_error"] = None
        cfg["last_reason"] = reason
        save_config(cfg)
        return summary
    except Exception as exc:  # noqa: BLE001 - 잡 실패가 스케줄러를 죽이지 않도록
        cfg = load_config()
        cfg["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cfg["last_error"] = str(exc)
        cfg["last_reason"] = reason
        save_config(cfg)
        return {"error": str(exc)}
    finally:
        _lock.release()


def _register_jobs(cfg: dict[str, Any]) -> None:
    """설정에 맞춰 잡을 재등록한다(기존 잡 모두 제거 후)."""
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    sched = _get_scheduler()
    sched.remove_all_jobs()
    if not cfg.get("enabled"):
        return

    common = dict(max_instances=1, coalesce=True, misfire_grace_time=3600)
    mode = cfg["mode"]
    if mode == "interval":
        sched.add_job(
            _run_job, IntervalTrigger(hours=cfg["interval_hours"], timezone=_TZ),
            id="inbox_interval", replace_existing=True, **common,
        )
    elif mode == "times":
        for i, t in enumerate(cfg["times"]):
            h, m = (int(x) for x in t.split(":"))
            sched.add_job(
                _run_job, CronTrigger(hour=h, minute=m, timezone=_TZ),
                id=f"inbox_time_{i}", replace_existing=True, **common,
            )
    elif mode == "weekly":
        h, m = (int(x) for x in cfg["weekly_time"].split(":"))
        sched.add_job(
            _run_job,
            CronTrigger(day_of_week=cfg["weekday"], hour=h, minute=m, timezone=_TZ),
            id="inbox_weekly", replace_existing=True, **common,
        )


def start() -> None:
    """앱 시작 시 호출. 저장된 설정으로 스케줄러를 켠다(실패해도 앱은 정상)."""
    try:
        cfg = load_config()
        sched = _get_scheduler()
        if not sched.running:
            sched.start()
        _register_jobs(cfg)
    except Exception as exc:  # 앱은 살리되 UI에서 원인을 확인할 수 있게 기록
        cfg = load_config()
        cfg["last_error"] = f"scheduler_start_failed: {exc}"
        save_config(cfg)


def apply(incoming: dict[str, Any]) -> dict[str, Any]:
    """화면에서 받은 설정을 검증·저장·반영하고 상태를 돌려준다."""
    cfg = normalize_config(incoming)
    save_config(cfg)
    sched = _get_scheduler()
    if not sched.running:
        sched.start()
    _register_jobs(cfg)
    return status()


def run_now() -> dict[str, Any]:
    """지금 즉시 1회 수집(스케줄과 무관)."""
    return _run_job(reason="manual")


def status() -> dict[str, Any]:
    """현재 설정 + 다음 실행 예정 시각 + 마지막 실행 결과."""
    cfg = load_config()
    next_runs: list[str] = []
    running = False
    try:
        sched = _get_scheduler()
        running = bool(sched.running)
        jobs = sorted(
            (j for j in sched.get_jobs() if j.next_run_time),
            key=lambda j: j.next_run_time,
        )
        next_runs = [j.next_run_time.strftime("%Y-%m-%d %H:%M") for j in jobs[:5]]
    except Exception:  # noqa: BLE001
        pass
    return {
        "config": {
            "enabled": cfg["enabled"],
            "mode": cfg["mode"],
            "interval_hours": cfg["interval_hours"],
            "times": cfg["times"],
            "weekday": cfg["weekday"],
            "weekly_time": cfg["weekly_time"],
        },
        "running": running,
        "next_runs": next_runs,
        "last_run": cfg.get("last_run"),
        "last_summary": cfg.get("last_summary"),
        "last_error": cfg.get("last_error"),
        "last_reason": cfg.get("last_reason"),
    }
