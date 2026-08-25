"""
tests/test_phase10.py
Automated test suite for Phase 10:
- Outbound Webhook Dispatcher payload formatting & HMAC-SHA256 signature generation
- Inbound Webhook Receiver enqueue endpoint & signature verification
- Webhook config status endpoint
"""
import pytest
import json
from datetime import datetime, timezone
from sqlalchemy import select

from database.connection import AsyncSessionLocal
from database.models import JobQueue
from backend.services.webhook import generate_hmac_signature, dispatch_webhook_event
from backend.api.webhooks import verify_webhook_signature


def test_hmac_signature_generation_and_verification():
    """Verify HMAC-SHA256 signature computation and matching."""
    secret = "super_secret_n8n_token_123"
    payload = json.dumps({"event": "TEST", "data": {"key": "val"}}).encode("utf-8")

    sig = generate_hmac_signature(payload, secret)
    assert sig is not None
    assert len(sig) == 64  # SHA256 hex string length

    # Verify matching with sha256= prefix
    assert verify_webhook_signature(payload, f"sha256={sig}", secret) is True
    assert verify_webhook_signature(payload, sig, secret) is True

    # Verify rejection on tampered payload or wrong secret
    tampered_payload = json.dumps({"event": "TAMPERED"}).encode("utf-8")
    assert verify_webhook_signature(tampered_payload, sig, secret) is False
    assert verify_webhook_signature(payload, sig, "wrong_secret") is False


@pytest.mark.asyncio
async def test_dispatch_webhook_event_disabled():
    """Verify dispatcher safely returns when no webhook URL is configured."""
    res = await dispatch_webhook_event("APPLICATION_SUBMITTED", {"job": "test"}, webhook_url="")
    assert res["sent"] is False
    assert "No webhook URL" in res.get("reason", "")


@pytest.mark.asyncio
async def test_inbound_enqueue_job_database_insertion():
    """Verify inbound webhook adds valid job item to JobQueue."""
    from backend.api.webhooks import inbound_enqueue_job
    from fastapi import Request
    from unittest.mock import AsyncMock

    run_id = int(datetime.now(timezone.utc).timestamp() * 1000)
    test_url = f"https://boards.greenhouse.io/openai/jobs/n8n_test_{run_id}"

    payload_dict = {
        "url": test_url,
        "company": "OpenAI",
        "job_title": "AI Research Engineer Intern",
        "priority": 1,
        "source": "n8n_workflow",
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")

    # Mock FastAPI Request
    mock_request = AsyncMock(spec=Request)
    mock_request.body.return_value = payload_bytes

    response = await inbound_enqueue_job(mock_request, x_jobagent_signature=None)
    assert response["ok"] is True
    assert response["enqueued"] is True
    assert "queue_id" in response

    # Verify record in SQLite database
    async with AsyncSessionLocal() as session:
        job = (
            await session.execute(
                select(JobQueue).where(JobQueue.job_url == test_url)
            )
        ).scalar_one_or_none()
        assert job is not None
        assert job.company == "OpenAI"
        assert job.source == "n8n_workflow"
        assert job.priority == 1
