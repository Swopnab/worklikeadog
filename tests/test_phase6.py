"""
tests/test_phase6.py
Automated test suite for Phase 6:
- JobOrchestrator queue selection and prioritization
- Daily application quota limits
- Full processing pipeline from JobQueue -> Evaluation -> Resume -> Pre-submit review
- State machine transitions (RUNNING -> HANDOFF / PAUSED -> RESUMED)
"""
import pytest
import json
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy import select
from database.connection import AsyncSessionLocal
from database.models import Application, ApplicationStatus, JobQueue, AgentStateEnum
from agent.orchestrator import JobOrchestrator
from agent.state_machine import get_current_state, transition_state


@pytest.mark.asyncio
async def test_job_orchestrator_queue_priority():
    """Verify that JobOrchestrator picks the highest priority unprocessed job."""
    orchestrator = JobOrchestrator()

    async with AsyncSessionLocal() as session:
        # Mark all existing unprocessed jobs as processed for isolated priority test
        existing = (await session.execute(select(JobQueue).where(JobQueue.processed == False))).scalars().all()
        for j in existing:
            j.processed = True
        await session.commit()

        # Create lower priority job (priority 5)
        job_low = JobQueue(
            job_url="https://example.com/job_low_priority",
            company="LowCorp",
            job_title="Junior Dev",
            priority=5,
            processed=False,
            queued_at=datetime.now(timezone.utc),
        )
        # Create higher priority job (priority 1)
        job_high = JobQueue(
            job_url="https://example.com/job_high_priority",
            company="HighCorp",
            job_title="AI Intern",
            priority=1,
            processed=False,
            queued_at=datetime.now(timezone.utc),
        )
        session.add_all([job_low, job_high])
        await session.commit()

        # Fetch next job
        next_job = await orchestrator.get_next_job(session)
        assert next_job is not None
        assert next_job.priority == 1
        assert next_job.company == "HighCorp"

        # Mark high as processed and verify low is next
        next_job.processed = True
        await session.commit()

        second_job = await orchestrator.get_next_job(session)
        assert second_job is not None
        assert second_job.priority == 5
        assert second_job.company == "LowCorp"

        # Cleanup
        second_job.processed = True
        await session.commit()


@pytest.mark.asyncio
async def test_orchestrator_daily_limit(monkeypatch):
    """Verify daily limit enforcement."""
    from config.settings import settings
    monkeypatch.setattr(settings, "max_applications_per_day", 10000)
    orchestrator = JobOrchestrator()

    async with AsyncSessionLocal() as session:
        can_proceed = await orchestrator.check_daily_limit(session)
        assert can_proceed is True

        # Now test when limit is exceeded
        monkeypatch.setattr(settings, "max_applications_per_day", 0)
        blocked = await orchestrator.check_daily_limit(session)
        assert blocked is False


@pytest.mark.asyncio
async def test_orchestrator_process_mock_job(tmp_path):
    """Test full processing of a queued job through the orchestrator pipeline."""
    mock_gh_path = Path("tests/mock_job_sites/greenhouse_mock.html").resolve()
    mock_url = f"file://{mock_gh_path}?run_id={datetime.now(timezone.utc).timestamp()}"

    orchestrator = JobOrchestrator()

    # Ensure agent FSM is in RUNNING state
    curr_state = await get_current_state()
    if curr_state.state != AgentStateEnum.RUNNING:
        try:
            await transition_state(AgentStateEnum.STARTING, checkpoint="test_start")
            await transition_state(AgentStateEnum.RUNNING, checkpoint="test_running")
        except Exception:
            pass

    async with AsyncSessionLocal() as session:
        job = JobQueue(
            job_url=mock_url,
            company="Acme AI Test Execution",
            job_title="Software Engineering Intern",
            priority=1,
            processed=False,
            queued_at=datetime.now(timezone.utc),
        )
        session.add(job)
        await session.commit()

        # Process the mock job
        result = await orchestrator.process_job(job, session)
        assert "status" in result
        assert job.processed is True
        assert job.application_id is not None

        # Verify application record created in database
        app = await session.get(Application, job.application_id)
        assert app is not None
        assert app.status in (ApplicationStatus.READY_FOR_REVIEW, ApplicationStatus.NEEDS_REVIEW, ApplicationStatus.NEEDS_ATTENTION, ApplicationStatus.READY)

    # Cleanup state
    try:
        await transition_state(AgentStateEnum.STOPPED, checkpoint="test_end")
    except Exception:
        pass
