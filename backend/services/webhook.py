"""
backend/services/webhook.py
Outbound webhook dispatcher for n8n workflows and external integrations (Discord, Telegram, Slack).

Dispatches structured event payloads with HMAC-SHA256 signature verification.
"""
import hmac
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


def generate_hmac_signature(payload_bytes: bytes, secret: str) -> str:
    """Generates hex-encoded HMAC-SHA256 signature for payload verification."""
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


async def dispatch_webhook_event(
    event_type: str,
    data: Dict[str, Any],
    webhook_url: Optional[str] = None,
    secret: Optional[str] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Sends an outbound webhook event payload to the configured endpoint.
    """
    url = webhook_url or getattr(settings, "webhook_url", "")
    sec = secret if secret is not None else getattr(settings, "webhook_secret", "")

    if not url:
        logger.debug("Webhook dispatch skipped: No webhook URL configured")
        return {"sent": False, "reason": "No webhook URL configured"}

    allowed_events = getattr(settings, "webhook_events", [])
    if allowed_events and event_type not in allowed_events:
        logger.debug("Webhook dispatch skipped: Event %s not in enabled events", event_type)
        return {"sent": False, "reason": f"Event {event_type} not enabled"}

    payload = {
        "event": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "JobAgent",
        "data": data,
    }

    payload_bytes = json.dumps(payload, default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "JobAgent-Webhook/1.0",
        "X-JobAgent-Event": event_type,
        "X-JobAgent-Timestamp": payload["timestamp"],
    }

    if sec:
        sig = generate_hmac_signature(payload_bytes, sec)
        headers["X-JobAgent-Signature"] = f"sha256={sig}"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, content=payload_bytes, headers=headers)
            resp.raise_for_status()
            logger.info("Dispatched webhook event '%s' to %s (Status: %d)", event_type, url, resp.status_code)
            return {
                "sent": True,
                "status_code": resp.status_code,
                "event": event_type,
                "timestamp": payload["timestamp"],
            }
    except Exception as e:
        logger.warning("Failed dispatching webhook event '%s' to %s: %s", event_type, url, e)
        return {"sent": False, "error": str(e), "event": event_type}
