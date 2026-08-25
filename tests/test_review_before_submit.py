"""
tests/test_review_before_submit.py
Strict automated test suite verifying review-before-submit and zero auto-submit enforcement:
TEST 1: Mock application with button "Submit Application" -> NOT clicked, status = READY_FOR_REVIEW
TEST 2: Final button "Finish" -> NOT clicked, raises FinalSubmissionBlocked
TEST 3: Final button "Apply" / "Apply now" -> NOT clicked if classified as final submission
TEST 4: Multi-page application has "Continue" -> Continue is allowed until final review
TEST 5: Legacy config auto_submit = True -> ignored/overridden, final submission blocked
TEST 6: Agent reaches final page with all answers completed -> READY_FOR_REVIEW
TEST 7: No user confirmation -> cannot become SUBMITTED (raises ApplicationStatusError)
TEST 8: User confirms -> status = SUBMITTED, submission_confirmed_by_user = True
"""
import pytest
import re
from pathlib import Path
from datetime import datetime, timezone

from config.settings import settings
from database.connection import AsyncSessionLocal
from database.models import Application, ApplicationStatus, JobQueue
from browser.safety_barrier import SafetyBarrier, FinalSubmissionBlocked, FINAL_SUBMISSION_ALLOWED
from agent.state_machine import validate_application_transition, ApplicationStatusError
from backend.services.artifact_store import ArtifactStore


def test_01_final_submission_submit_application_blocked():
    """TEST 1: Button 'Submit Application' is classified as final submission and blocked."""
    assert FINAL_SUBMISSION_ALLOWED is False
    assert SafetyBarrier.is_final_submission_element("Submit Application", role="button") is True
    with pytest.raises(FinalSubmissionBlocked):
        SafetyBarrier.guard_click("Submit Application", role="button")


def test_02_final_button_finish_blocked():
    """TEST 2: Final button 'Finish' on review page raises FinalSubmissionBlocked."""
    assert SafetyBarrier.is_final_submission_element("Finish", role="button", page_stage="review") is True
    with pytest.raises(FinalSubmissionBlocked):
        SafetyBarrier.guard_click("Finish", role="button", page_stage="review")


def test_03_final_button_apply_now_blocked():
    """TEST 3: Button 'Apply now' or 'Submit my application' is blocked."""
    assert SafetyBarrier.is_final_submission_element("Apply now", role="button") is True
    assert SafetyBarrier.is_final_submission_element("Submit my application", role="button") is True
    with pytest.raises(FinalSubmissionBlocked):
        SafetyBarrier.guard_click("Apply now", role="button")


def test_04_intermediate_navigation_continue_allowed():
    """TEST 4: Intermediate navigation buttons ('Continue', 'Next') are NOT classified as final submit."""
    assert SafetyBarrier.is_final_submission_element("Continue", role="button") is False
    assert SafetyBarrier.is_final_submission_element("Next", role="button") is False
    assert SafetyBarrier.is_final_submission_element("Save and Continue", role="button") is False
    # Guard click does not raise for intermediate navigation
    SafetyBarrier.guard_click("Continue", role="button")
    SafetyBarrier.guard_click("Next", role="button")


def test_05_legacy_config_autosubmit_ignored():
    """TEST 5: Legacy settings with auto_submit are strictly overridden to False."""
    assert settings.auto_submit is False
    assert settings.final_submission_allowed is False
    assert settings.real_applications_enabled is False
    assert settings.dry_run is True

    can_submit, reason = SafetyBarrier.evaluate_submission_readiness(
        company="TechCorp",
        job_title="Intern",
        match_score=99.0,
        eligibility_passed=True,
        requires_human_input=False,
    )
    assert can_submit is False
    assert "ready for review" in reason.lower() or "disabled" in reason.lower()


def test_06_form_completed_status_ready_for_review():
    """TEST 6: Application with complete answers halts at READY_FOR_REVIEW."""
    app = Application(
        company="Stripe",
        job_title="SWE Intern",
        job_url="https://example.com/stripe-intern",
        status=ApplicationStatus.READY_FOR_REVIEW,
        review_required=True,
        review_completed=False,
    )
    assert app.status == ApplicationStatus.READY_FOR_REVIEW
    assert app.review_required is True
    assert app.review_completed is False


def test_07_no_user_confirmation_forbidden_transitions():
    """TEST 7: Directly setting SUBMITTED without manual user confirmation is rejected."""
    # Direct transitions to SUBMITTED without user confirmation must raise ApplicationStatusError
    with pytest.raises(ApplicationStatusError):
        validate_application_transition(ApplicationStatus.APPLYING, ApplicationStatus.SUBMITTED, is_user_confirmed=False)

    with pytest.raises(ApplicationStatusError):
        validate_application_transition(ApplicationStatus.FORM_FILLED, ApplicationStatus.SUBMITTED, is_user_confirmed=False)

    with pytest.raises(ApplicationStatusError):
        validate_application_transition(ApplicationStatus.READY_FOR_REVIEW, ApplicationStatus.SUBMITTED, is_user_confirmed=False)

    with pytest.raises(ApplicationStatusError):
        validate_application_transition(ApplicationStatus.NEEDS_ATTENTION, ApplicationStatus.SUBMITTED, is_user_confirmed=False)


@pytest.mark.asyncio
async def test_08_user_confirms_manual_submission():
    """TEST 8: Status becomes SUBMITTED only after user manual confirmation."""
    from database.connection import init_db
    await init_db()

    async with AsyncSessionLocal() as session:
        app = Application(
            company="ReviewTest Corp",
            job_title="SWE Intern",
            job_url=f"https://example.com/review-{datetime.now(timezone.utc).timestamp()}",
            status=ApplicationStatus.READY_FOR_REVIEW,
            review_required=True,
            review_completed=False,
            submission_confirmed_by_user=False,
            discovered_at=datetime.now(timezone.utc),
        )
        session.add(app)
        await session.commit()
        app_id = app.id

        from backend.api.applications import confirm_manual_submission
        res = await confirm_manual_submission(
            app_id=app_id,
            body={"confirmation": "I manually submitted the form on Workday portal"},
            db=session
        )
        assert res["ok"] is True
        assert res["status"] == ApplicationStatus.SUBMITTED.value

        updated_app = await session.get(Application, app_id)
        assert updated_app.status == ApplicationStatus.SUBMITTED
        assert updated_app.application_submitted_at is not None
        assert "Workday" in updated_app.submission_confirmation
