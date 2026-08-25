"""
backend/api/webhooks.py
Webhook integration endpoints for n8n automation workflows, external scrapers, and event listeners.
"""
import hmac
import hashlib
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Header, Request, Depends
from pydantic import BaseModel

from config.settings import settings
from database.connection import db_session
from database.models import JobQueue
from jobs.dedupe import normalize_url
from backend.services.webhook import dispatch_webhook_event, generate_hmac_signature

logger = logging.getLogger(__name__)

router = APIRouter()


class InboundJobPayload(BaseModel):
    url: str
    company: Optional[str] = None
    job_title: Optional[str] = None
    priority: Optional[int] = 2
    source: Optional[str] = "n8n_webhook"
    location: Optional[str] = None
    description: Optional[str] = None


class TestWebhookRequest(BaseModel):
    target_url: Optional[str] = None
    event_type: Optional[str] = "APPLICATION_SUBMITTED"


def verify_webhook_signature(payload_bytes: bytes, signature_header: Optional[str], secret: str) -> bool:
    """Validates HMAC-SHA256 signature header if secret is configured."""
    if not secret:
        return True  # Open if no secret is enforced
    if not signature_header:
        return False

    expected_sig = generate_hmac_signature(payload_bytes, secret)
    # Header format: sha256=<hex> or raw <hex>
    clean_header = signature_header.replace("sha256=", "").strip()
    return hmac.compare_digest(expected_sig, clean_header)


@router.post("/enqueue")
async def inbound_enqueue_job(
    request: Request,
    x_jobagent_signature: Optional[str] = Header(None),
):
    """
    Inbound webhook receiver: Enqueues jobs sent from n8n workflows, RSS parsers, or browser extensions.
    Validates HMAC signature if settings.webhook_secret is set.
    """
    raw_body = await request.body()
    secret = getattr(settings, "webhook_secret", "")

    if secret and not verify_webhook_signature(raw_body, x_jobagent_signature, secret):
        logger.warning("Inbound webhook signature verification failed")
        raise HTTPException(status_code=401, detail="Invalid HMAC-SHA256 signature")

    try:
        data = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    url = data.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Field 'url' is required")

    clean_url = normalize_url(url)

    async with db_session() as session:
        from sqlalchemy import select
        existing = (
            await session.execute(
                select(JobQueue).where(
                    (JobQueue.job_url == clean_url) | (JobQueue.job_url == url)
                )
            )
        ).scalar_one_or_none()

        if existing and not existing.processed:
            return {
                "ok": True,
                "enqueued": False,
                "message": "Job already pending in queue",
                "queue_id": existing.id,
                "url": clean_url,
            }

        job = JobQueue(
            job_url=clean_url,
            company=data.get("company"),
            job_title=data.get("job_title"),
            source=data.get("source", "n8n_webhook"),
            priority=data.get("priority", 2),
            queued_at=datetime.now(timezone.utc),
            processed=False,
        )
        session.add(job)
        await session.commit()

        logger.info("Inbound webhook enqueued job #%d: %s (%s)", job.id, job.job_title, job.company)

        return {
            "ok": True,
            "enqueued": True,
            "queue_id": job.id,
            "url": clean_url,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.post("/test")
async def test_outbound_webhook(req: TestWebhookRequest):
    """Triggers a test webhook event dispatch to verify n8n webhook listener connectivity."""
    test_data = {
        "company": "Stripe",
        "job_title": "Software Engineering Intern",
        "match_score": 92.5,
        "status": "SUBMITTED",
        "notes": "Test webhook dispatch from JobAgent",
    }
    result = await dispatch_webhook_event(
        event_type=req.event_type or "APPLICATION_SUBMITTED",
        data=test_data,
        webhook_url=req.target_url or getattr(settings, "webhook_url", ""),
    )
    return result


@router.get("/config")
async def get_webhook_config():
    """Returns current webhook configuration status."""
    return {
        "webhook_enabled": getattr(settings, "webhook_enabled", False),
        "webhook_url": getattr(settings, "webhook_url", ""),
        "has_secret": bool(getattr(settings, "webhook_secret", "")),
        "enabled_events": getattr(settings, "webhook_events", []),
    }
