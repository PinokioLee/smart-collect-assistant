"""마감 임박/초과 Collection Job의 미제출자를 판단하고 리마인드한다."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from . import job_store, store
from .config import settings
from .tools.email_tools import EmailSendRequest, send_email
from .tools.guide_tools import generate_reminder_message


def _parse_deadline(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _allowed(recipients: list[dict], enabled: bool) -> bool:
    if not enabled or not settings.auto_send_allowed_domains:
        return False
    emails = [str(r.get("email") or "").lower() for r in recipients]
    return bool(emails) and all(
        "@" in email and email.rsplit("@", 1)[-1] in settings.auto_send_allowed_domains
        for email in emails
    )


def run_deadline_agent(
    *, now: datetime | None = None, db_path: str | Path | None = None,
    prefer_llm: bool = True, auto_send_enabled: bool | None = None,
) -> dict:
    now = now or datetime.now()
    store.init_db(db_path)
    enabled = settings.auto_send_enabled if auto_send_enabled is None else auto_send_enabled
    jobs = [j for j in job_store.list_jobs(db_path=db_path) if j.get("status") in {"collecting", "partial"}]
    created = sent = skipped = 0
    details = []
    for job in jobs:
        deadline = _parse_deadline(job.get("deadline"))
        if not deadline or deadline > now + timedelta(hours=settings.reminder_window_hours):
            continue
        event_id = f"REMINDER-{job['job_id']}-{now:%Y%m%d}"
        if job_store.list_actions(event_id, db_path):
            skipped += 1
            continue
        accepted = {
            str(s.get("sender") or "").lower()
            for s in job_store.list_submissions(job["job_id"], db_path)
            if s.get("status") == "accepted"
        }
        missing = [
            r for r in job.get("recipients", [])
            if str(r.get("email") or "").lower() not in accepted
        ]
        if not missing:
            continue
        draft = generate_reminder_message(
            missing, job.get("deadline"), job.get("title") or "",
            prefer_llm=prefer_llm,
        )
        subject = f"[{job['job_id']}] {draft['reminder_mail_subject']}"
        body = draft["reminder_mail_body"]
        auto = _allowed(missing, bool(enabled))
        send_result = None
        if auto:
            send_result = send_email(EmailSendRequest(
                to=[r["email"] for r in missing if r.get("email")],
                subject=subject, body=body,
                attachment_paths=[job["template_path"]] if job.get("template_path") and Path(job["template_path"]).exists() else [],
            ))
            sent += 1
            status = "sent"
        else:
            created += 1
            status = "draft_ready"
        record = {
            "message_id": event_id, "sender": "Deadline Agent", "subject": subject,
            "received_at": now.strftime("%Y-%m-%d %H:%M"),
            "classification": "취합업무메일", "intent": "reminder",
            "confidence": 1.0, "tier": "auto", "status": status,
            "draft_subject": subject, "draft_body": body, "recipients": missing,
            "reasons": ["마감 24시간 이내 또는 마감 초과", f"미제출 {len(missing)}명"],
            "risk_flags": [], "source": "deadline-policy", "sent": auto,
            "sent_message_id": (send_result or {}).get("message_id"), "error": None,
            "processed_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "grounding": {"flags": [], "score": 1.0}, "sources": ["collection_jobs", "job_submissions"],
            "decision": {"action": "auto_send" if auto else "review", "source": "deadline-policy"},
            "artifacts": {
                "job_id": job["job_id"], "send_result": send_result or {},
                "attachment_paths": [job["template_path"]] if job.get("template_path") else [],
            },
        }
        store.upsert_record(record, db_path)
        job_store.log_action(
            event_id, "Deadline/Communication Agent", "send_reminder" if auto else "draft_reminder",
            "success", {"missing": len(missing), "deadline": job.get("deadline")},
            job_id=job["job_id"], db_path=db_path,
        )
        details.append({"job_id": job["job_id"], "missing": len(missing), "action": record["decision"]["action"]})
    return {"jobs_checked": len(jobs), "drafted": created, "sent": sent, "skipped": skipped, "details": details}
