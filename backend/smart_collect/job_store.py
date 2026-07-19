"""자율 취합 Job, 제출물, Agent action 감사로그 저장소."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .store import DEFAULT_DB


@contextmanager
def _connect(db_path: str | Path | None = None):
    path = Path(db_path) if db_path else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_job_tables(db_path: str | Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS collection_jobs (
            job_id TEXT PRIMARY KEY,
            source_message_id TEXT,
            source_thread_id TEXT,
            title TEXT,
            deadline TEXT,
            recipients TEXT,
            required_fields TEXT,
            validation_rule TEXT,
            template_id TEXT,
            template_path TEXT,
            status TEXT,
            created_at TEXT,
            updated_at TEXT,
            result TEXT
        );
        CREATE TABLE IF NOT EXISTS job_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            message_id TEXT UNIQUE,
            sender TEXT,
            attachment_paths TEXT,
            status TEXT,
            errors TEXT,
            submitted_at TEXT,
            FOREIGN KEY(job_id) REFERENCES collection_jobs(job_id)
        );
        CREATE TABLE IF NOT EXISTS agent_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT,
            job_id TEXT,
            seq INTEGER,
            agent TEXT,
            action TEXT,
            outcome TEXT,
            detail TEXT,
            created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_actions_event ON agent_actions(event_id, seq);
        CREATE INDEX IF NOT EXISTS idx_submissions_job ON job_submissions(job_id);
        """)
        conn.commit()


def _loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _job(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for key, default in (
        ("recipients", []), ("required_fields", []),
        ("validation_rule", {}), ("result", {}),
    ):
        out[key] = _loads(out.get(key), default)
    return out


def create_job(job: dict, db_path: str | Path | None = None) -> dict:
    init_job_tables(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = {
        "job_id": job["job_id"],
        "source_message_id": job.get("source_message_id"),
        "source_thread_id": job.get("source_thread_id"),
        "title": job.get("title"),
        "deadline": job.get("deadline"),
        "recipients": json.dumps(job.get("recipients", []), ensure_ascii=False),
        "required_fields": json.dumps(job.get("required_fields", []), ensure_ascii=False),
        "validation_rule": json.dumps(job.get("validation_rule", {}), ensure_ascii=False),
        "template_id": job.get("template_id"),
        "template_path": job.get("template_path"),
        "status": job.get("status", "collecting"),
        "created_at": job.get("created_at", now),
        "updated_at": now,
        "result": json.dumps(job.get("result", {}), ensure_ascii=False),
    }
    cols = list(row)
    with _connect(db_path) as conn:
        conn.execute(
            f"INSERT INTO collection_jobs ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
            "ON CONFLICT(job_id) DO UPDATE SET "
            + ", ".join(f"{c}=excluded.{c}" for c in cols if c not in {"job_id", "created_at"}),
            [row[c] for c in cols],
        )
        conn.commit()
    return get_job(job["job_id"], db_path) or {}


def get_job(job_id: str, db_path: str | Path | None = None) -> dict | None:
    init_job_tables(db_path)
    with _connect(db_path) as conn:
        return _job(conn.execute("SELECT * FROM collection_jobs WHERE job_id=?", (job_id,)).fetchone())


def list_jobs(status: str | None = None, db_path: str | Path | None = None) -> list[dict]:
    init_job_tables(db_path)
    with _connect(db_path) as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM collection_jobs WHERE status=? ORDER BY updated_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM collection_jobs ORDER BY updated_at DESC").fetchall()
    return [_job(row) or {} for row in rows]


def update_job(
    job_id: str, *, status: str | None = None, result: dict | None = None,
    db_path: str | Path | None = None,
) -> None:
    fields = ["updated_at=?"]
    values: list[Any] = [datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    if status is not None:
        fields.append("status=?")
        values.append(status)
    if result is not None:
        fields.append("result=?")
        values.append(json.dumps(result, ensure_ascii=False))
    values.append(job_id)
    with _connect(db_path) as conn:
        conn.execute(f"UPDATE collection_jobs SET {', '.join(fields)} WHERE job_id=?", values)
        conn.commit()


def find_job_for_message(
    text: str, thread_id: str = "", db_path: str | Path | None = None
) -> dict | None:
    """제목/본문 Job ID 또는 원본 thread, 단일 활성 Job 순으로 안전하게 매칭."""
    import re

    match = re.search(r"\[(SC-[0-9A-Za-z_-]+)\]", text or "")
    if match:
        found = get_job(match.group(1), db_path)
        if found:
            return found
    jobs = [j for j in list_jobs(db_path=db_path) if j.get("status") in {"collecting", "partial"}]
    if thread_id:
        matched = [j for j in jobs if j.get("source_thread_id") == thread_id]
        if len(matched) == 1:
            return matched[0]
    return jobs[0] if len(jobs) == 1 else None


def add_submission(submission: dict, db_path: str | Path | None = None) -> None:
    init_job_tables(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO job_submissions
            (job_id,message_id,sender,attachment_paths,status,errors,submitted_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(message_id) DO UPDATE SET
            status=excluded.status, errors=excluded.errors, attachment_paths=excluded.attachment_paths""",
            (
                submission["job_id"], submission["message_id"], submission.get("sender"),
                json.dumps(submission.get("attachment_paths", []), ensure_ascii=False),
                submission.get("status"), json.dumps(submission.get("errors", []), ensure_ascii=False),
                submission.get("submitted_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()


def list_submissions(job_id: str, db_path: str | Path | None = None) -> list[dict]:
    init_job_tables(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM job_submissions WHERE job_id=? ORDER BY submitted_at", (job_id,)
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["attachment_paths"] = _loads(item.get("attachment_paths"), [])
        item["errors"] = _loads(item.get("errors"), [])
        out.append(item)
    return out


def log_action(
    event_id: str, agent: str, action: str, outcome: str,
    detail: dict | None = None, *, job_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict:
    init_job_tables(db_path)
    with _connect(db_path) as conn:
        seq = conn.execute(
            "SELECT COALESCE(MAX(seq),0)+1 FROM agent_actions WHERE event_id=?", (event_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO agent_actions(event_id,job_id,seq,agent,action,outcome,detail,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                event_id, job_id, seq, agent, action, outcome,
                json.dumps(detail or {}, ensure_ascii=False),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
    return {"seq": seq, "agent": agent, "action": action, "outcome": outcome, "detail": detail or {}}


def list_actions(event_id: str, db_path: str | Path | None = None) -> list[dict]:
    init_job_tables(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM agent_actions WHERE event_id=? ORDER BY seq", (event_id,)
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["detail"] = _loads(item.get("detail"), {})
        out.append(item)
    return out
