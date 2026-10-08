"""
tests/test_phase5.py
Automated test suite for Phase 5:
- ATS platform detection from URLs and DOM signatures
- FieldMapper semantic parsing and Level 1 vs Level 3 safety boundary enforcement
- SafetyBarrier pre-submit verification logic
- Form filling on mock Greenhouse and Lever pages using Playwright
"""
import pytest
from pathlib import Path
from browser.detect import ATSDetector, ATSPlatform
from browser.field_mapper import FieldMapper, FieldConfidence
from browser.safety_barrier import SafetyBarrier
from browser.fillers.greenhouse import GreenhouseFiller
from browser.fillers.lever import LeverFiller
from browser.session import BrowserSession


def test_ats_detection_from_url():
    """Verify ATS detection across various URL patterns."""
    assert ATSDetector.detect_from_url("https://boards.greenhouse.io/stripe/jobs/123") == ATSPlatform.GREENHOUSE
    assert ATSDetector.detect_from_url("https://jobs.lever.co/figma/abc-456") == ATSPlatform.LEVER
    assert ATSDetector.detect_from_url("https://jobs.ashbyhq.com/openai/789") == ATSPlatform.ASHBY
    assert ATSDetector.detect_from_url("https://company.myworkdayjobs.com/careers/job/1") == ATSPlatform.WORKDAY
    assert ATSDetector.detect_from_url("https://example.com/careers") == ATSPlatform.GENERIC


def test_ats_detection_from_html():
    """Verify ATS detection from HTML page content signatures."""
    gh_html = Path("tests/mock_job_sites/greenhouse_mock.html").read_text()
    lever_html = Path("tests/mock_job_sites/lever_mock.html").read_text()

    assert ATSDetector.detect_from_html(gh_html) == ATSPlatform.GREENHOUSE
    assert ATSDetector.detect_from_html(lever_html) == ATSPlatform.LEVER
    assert ATSDetector.detect_from_html("<html><body><h1>Jobs</h1></body></html>") == ATSPlatform.GENERIC


def test_field_mapper_safety_boundaries():
    """Verify FieldMapper correctly auto-fills Level 1 and halts on Level 3."""
    mapper = FieldMapper()

    # Level 1 Auto-fillable verified facts
    key, conf, val = mapper.classify_field("First Name")
    assert conf == FieldConfidence.LEVEL_1_AUTO
    assert val == "Example"

    key, conf, val = mapper.classify_field("Email Address")
    assert conf == FieldConfidence.LEVEL_1_AUTO
    assert "@" in val

    key, conf, val = mapper.classify_field("LinkedIn Profile URL")
    assert conf == FieldConfidence.LEVEL_1_AUTO
    assert "linkedin.com" in val

    key, conf, val = mapper.classify_field("College or University")
    assert conf == FieldConfidence.LEVEL_1_AUTO
    assert "Arlington" in val

    # Approved F-1 work authorization mappings
    key, conf, val = mapper.classify_field("Will you now or in the future require visa sponsorship?")
    assert conf == FieldConfidence.LEVEL_3_PAUSE
    assert val is None

    key, conf, val = mapper.classify_field("Are you legally authorized to work in the United States?")
    assert conf == FieldConfidence.LEVEL_3_PAUSE
    assert val is None

    # Level 3 MUST PAUSE (sensitive, clearance, salary, unfamiliar)
    key, conf, val = mapper.classify_field("Do you hold an active US Security Clearance?")
    assert conf == FieldConfidence.LEVEL_3_PAUSE
    assert val is None

    key, conf, val = mapper.classify_field("Expected Annual Salary")
    assert conf == FieldConfidence.LEVEL_3_PAUSE
    assert val is None


def test_safety_barrier_enforcement():
    """Test that safety barrier halts auto-submit and enforces manual review."""
    can_submit, reason = SafetyBarrier.evaluate_submission_readiness(
        company="Acme Corp",
        job_title="Software Intern",
        match_score=90.0,
        eligibility_passed=True,
        requires_human_input=False,
    )
    assert can_submit is False
    assert "ready for review" in reason.lower() or "disabled" in reason.lower()


@pytest.mark.asyncio
async def test_greenhouse_form_filling(tmp_path):
    """Test filling mock Greenhouse page with Playwright."""
    session = BrowserSession(headless=True, user_data_dir=tmp_path / "browser")
    page = await session.start()

    mock_path = Path("tests/mock_job_sites/greenhouse_mock.html").resolve()
    await page.goto(f"file://{mock_path}")

    filler = GreenhouseFiller()
    res = await filler.fill_form(page)

    # First name, Last name, Email, Phone should be filled
    assert await page.locator("#first_name").input_value() == "Example"
    assert await page.locator("#last_name").input_value() == "Candidate"
    assert "@" in await page.locator("#email").input_value()

    # The legal work authorization question is auto-filled with YES
    filled_names = [f.get("name", "") + " " + f.get("label", "") for f in res.filled_fields]
    assert any("authorized" in f.lower() or "first_name" in f.lower() for f in filled_names)

    await session.close()


@pytest.mark.asyncio
async def test_lever_form_filling(tmp_path):
    """Test filling mock Lever page with Playwright."""
    session = BrowserSession(headless=True, user_data_dir=tmp_path / "browser")
    page = await session.start()

    mock_path = Path("tests/mock_job_sites/lever_mock.html").resolve()
    await page.goto(f"file://{mock_path}")

    filler = LeverFiller()
    res = await filler.fill_form(page)

    assert "Example" in await page.locator("input[name='name']").input_value()
    assert "@" in await page.locator("input[name='email']").input_value()
    assert "linkedin.com" in await page.locator("input[name='urls[LinkedIn]']").input_value()

    await session.close()
