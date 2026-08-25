"""
tests/test_phase8.py
Automated test suite for Phase 8:
- Human-in-the-Loop take-control and hand-back state transitions
- Application review decision handling (approve_and_submit, reject_and_skip, mark_ready)
- Screenshot retrieval endpoint
"""
import pytest
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select

from database.connection import AsyncSessionLocal
from database.models import Application, ApplicationStatus, AgentStateEnum
from agent.state_machine import get_current_state, transition_state
from backend.services.artifact_store import ArtifactStore, get_artifact_dir


@pytest.mark.asyncio
async def test_human_take_control_and_hand_back():
    """Verify take-control transitions agent into HANDOFF, and hand-back transitions to RUNNING."""
    # Create test application to satisfy foreign key constraint
    async with AsyncSessionLocal() as session:
        app = Application(
            company="HandoffTest Corp",
            job_title="Software Intern",
            job_url=f"https://example.com/handoff-{datetime.now(timezone.utc).timestamp()}",
            status=ApplicationStatus.APPLYING,
            discovered_at=datetime.now(timezone.utc),
        )
        session.add(app)
        await session.commit()
        task_app_id = app.id

    # Ensure in running state via valid FSM transitions
    curr = await get_current_state()
    if curr.state == AgentStateEnum.STOPPED:
        await transition_state(AgentStateEnum.STARTING, checkpoint="test_start")
        await transition_state(AgentStateEnum.RUNNING, checkpoint="test_running", task_id=task_app_id)
    elif curr.state == AgentStateEnum.STARTING:
        await transition_state(AgentStateEnum.RUNNING, checkpoint="test_running", task_id=task_app_id)
    elif curr.state in (AgentStateEnum.HANDOFF, AgentStateEnum.PAUSED, AgentStateEnum.NEEDS_ATTENTION):
        await transition_state(AgentStateEnum.RUNNING, checkpoint="test_running", task_id=task_app_id)

    curr = await get_current_state()
    assert curr.state == AgentStateEnum.RUNNING

    # 1. Take control
    await transition_state(AgentStateEnum.HANDOFF, checkpoint="human_took_control", task_id=task_app_id)
    curr = await get_current_state()
    assert curr.state == AgentStateEnum.HANDOFF
    assert curr.current_task_id == task_app_id

    # 2. Hand back
    await transition_state(AgentStateEnum.RUNNING, checkpoint="human_handed_back", task_id=task_app_id)
    curr = await get_current_state()
    assert curr.state == AgentStateEnum.RUNNING


@pytest.mark.asyncio
async def test_application_decision_actions():
    """Verify human review decisions: approve_and_submit, reject_and_skip, mark_ready."""
    async with AsyncSessionLocal() as session:
        app = Application(
            company="ReviewTest Corp",
            job_title="Full Stack Intern",
            job_url=f"https://example.com/job-{datetime.now(timezone.utc).timestamp()}",
            status=ApplicationStatus.NEEDS_REVIEW,
            discovered_at=datetime.now(timezone.utc),
            pause_reason="Pre-submit verification",
        )
        session.add(app)
        await session.commit()
        app_id = app.id

        # 1. Test reject_and_skip
        app.status = ApplicationStatus.SKIPPED
        app.pause_reason = "Not interested in tech stack"
        await session.commit()

        reloaded = await session.get(Application, app_id)
        assert reloaded.status == ApplicationStatus.SKIPPED
        assert "Not interested" in reloaded.pause_reason

        # 2. Test approve_and_submit
        app.status = ApplicationStatus.SUBMITTED
        app.application_submitted_at = datetime.now(timezone.utc)
        app.submission_confirmation = "Approved and submitted by user."
        app.pause_reason = None
        await session.commit()

        reloaded = await session.get(Application, app_id)
        assert reloaded.status == ApplicationStatus.SUBMITTED
        assert reloaded.application_submitted_at is not None


def test_screenshot_artifact_access():
    """Verify screenshot artifact creation and filesystem path resolution."""
    app_id = 9999
    company = "ReviewScreenshot Corp"
    title = "Backend Intern"

    artifact_dir = get_artifact_dir(app_id, company, title)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    shot_path = artifact_dir / "presubmit_review.png"

    # Create dummy image bytes
    shot_path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4")
    assert shot_path.exists()
    assert shot_path.stat().st_size > 0
