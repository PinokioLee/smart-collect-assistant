"""처리 상태 저장소 — 수신함 파이프라인의 중복 방지 + 검토 큐(SQLite).

같은 메일을 매 실행마다 다시 처리하지 않도록 message_id 를 키로 처리 이력을
저장한다. 표준 라이브러리 sqlite3 만 사용한다(추가 의존성 없음).

status 값
  draft_ready   : 취합 요청으로 자동 분류 → 요청 메일 초안 생성 완료(승인 대기)
  needs_review  : 확신도 중간 → 사람이 취합 요청 여부 판단 필요
  general       : 일반 메일
  quarantined   : 스팸·피싱·프롬프트 인젝션 등 위험 메일 격리
  sent          : 검토 후 발송 완료
  submission_accepted : 정상 제출 등록(아직 일부 작성자 미제출)
  awaiting_final_reply : 최종 검증·병합 완료 후 최초 요청자 회신 대기(Job 상태)
  error         : 처리 중 오류
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import DATA_DIR

DEFAULT_DB = DATA_DIR / "inbox_store.db"

_COLUMNS = [
    "message_id", "sender", "subject", "received_at",
    "classification", "confidence", "tier", "status",
    "draft_subject", "draft_body", "recipients", "reasons",
    "source", "sent", "error", "processed_at",
    "grounding", "sources",
    "intent", "risk_flags", "decision", "artifacts", "sent_message_id",
]

# JSON 으로 직렬화하는 컬럼
_JSON_COLUMNS = (
    "recipients", "reasons", "grounding", "sources",
    "risk_flags", "decision", "artifacts",
)


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


def init_db(db_path: str | Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_mails (
                message_id    TEXT PRIMARY KEY,
                sender        TEXT,
                subject       TEXT,
                received_at   TEXT,
                classification TEXT,
                confidence    REAL,
                tier          TEXT,
                status        TEXT,
                draft_subject TEXT,
                draft_body    TEXT,
                recipients    TEXT,
                reasons       TEXT,
                source        TEXT,
                sent          INTEGER DEFAULT 0,
                error         TEXT,
                processed_at  TEXT,
                grounding     TEXT,
                sources       TEXT,
                intent        TEXT,
                risk_flags    TEXT,
                decision      TEXT,
                artifacts     TEXT,
                sent_message_id TEXT
            )
            """
        )
        # 기존 사용자 DB를 파괴하지 않고 필요한 컬럼만 증분 마이그레이션한다.
        existing = {
            row[1] for row in conn.execute("PRAGMA table_info(processed_mails)").fetchall()
        }
        migrations = {
            "intent": "TEXT", "risk_flags": "TEXT", "decision": "TEXT",
            "artifacts": "TEXT", "sent_message_id": "TEXT",
        }
        for name, sql_type in migrations.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE processed_mails ADD COLUMN {name} {sql_type}")
        conn.commit()


def is_processed(message_id: str, db_path: str | Path | None = None) -> bool:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "SELECT 1 FROM processed_mails WHERE message_id = ?", (message_id,)
        )
        return cur.fetchone() is not None


def _serialize(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    for key in _JSON_COLUMNS:
        if isinstance(out.get(key), (list, dict)):
            out[key] = json.dumps(out[key], ensure_ascii=False)
    out["sent"] = int(bool(out.get("sent", 0)))
    return out


def upsert_record(record: dict[str, Any], db_path: str | Path | None = None) -> None:
    row = _serialize(record)
    values = [row.get(c) for c in _COLUMNS]
    placeholders = ", ".join("?" for _ in _COLUMNS)
    updates = ", ".join(f"{c}=excluded.{c}" for c in _COLUMNS if c != "message_id")
    with _connect(db_path) as conn:
        conn.execute(
            f"INSERT INTO processed_mails ({', '.join(_COLUMNS)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT(message_id) DO UPDATE SET {updates}",
            values,
        )
        conn.commit()


def _deserialize(row: sqlite3.Row) -> dict[str, Any]:
    rec = dict(row)
    for key in _JSON_COLUMNS:
        raw = rec.get(key)
        default: Any = {} if key in {"grounding", "decision", "artifacts"} else []
        if raw:
            try:
                rec[key] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                rec[key] = default
        else:
            rec[key] = default
    rec["sent"] = bool(rec.get("sent"))
    return rec


def get_record(message_id: str, db_path: str | Path | None = None) -> dict | None:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM processed_mails WHERE message_id = ?", (message_id,)
        )
        row = cur.fetchone()
        return _deserialize(row) if row else None


def list_records(
    status: str | None = None, db_path: str | Path | None = None
) -> list[dict]:
    with _connect(db_path) as conn:
        if status:
            cur = conn.execute(
                "SELECT * FROM processed_mails WHERE status = ? "
                "ORDER BY processed_at DESC",
                (status,),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM processed_mails ORDER BY processed_at DESC"
            )
        return [_deserialize(r) for r in cur.fetchall()]


def mark_sent(
    message_id: str, sent_message_id: str | None = None,
    db_path: str | Path | None = None,
) -> bool:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE processed_mails SET status='sent', sent=1, sent_message_id=?, error=NULL "
            "WHERE message_id = ?",
            (sent_message_id, message_id),
        )
        conn.commit()
        return cur.rowcount > 0


def counts_by_status(db_path: str | Path | None = None) -> dict[str, int]:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "SELECT status, COUNT(*) AS n FROM processed_mails GROUP BY status"
        )
        return {row["status"]: row["n"] for row in cur.fetchall()}
