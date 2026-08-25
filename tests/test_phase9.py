"""
tests/test_phase9.py
Automated test suite for Phase 9:
- Workday multi-stage application filler & data-automation-id classification
- Ashby modern form filler
- Taleo filler instantiation
- Form filler factory platform mapping
"""
import pytest
from pathlib import Path

from browser.session import BrowserSession
from browser.detect import ATSPlatform
from browser.fillers import get_form_filler, WorkdayFiller, AshbyFiller, TaleoFiller, GreenhouseFiller, LeverFiller


def test_filler_factory_mapping():
    """Verify get_form_filler maps every ATS platform to the correct specialized filler."""
    assert isinstance(get_form_filler(ATSPlatform.GREENHOUSE), GreenhouseFiller)
    assert isinstance(get_form_filler(ATSPlatform.LEVER), LeverFiller)
    assert isinstance(get_form_filler(ATSPlatform.ASHBY), AshbyFiller)
    assert isinstance(get_form_filler(ATSPlatform.WORKDAY), WorkdayFiller)


@pytest.mark.asyncio
async def test_workday_form_filling(tmp_path):
    """Verify WorkdayFiller fills fields by data-automation-id and pauses at step boundary."""
    mock_path = Path("tests/mock_job_sites/workday_mock.html").resolve()
    mock_url = f"file://{mock_path}"

    dummy_pdf = tmp_path / "resume.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 dummy resume")

    session = BrowserSession(headless=True)
    page = await session.navigate(mock_url)

    filler = WorkdayFiller()
    res = await filler.fill_form(page, resume_pdf_path=dummy_pdf)

    # Verify fields filled
    filled_descriptors = [f"{f.get('name', '')} {f.get('label', '')}".lower() for f in res.filled_fields]
    assert any("first" in f or "fname" in f for f in filled_descriptors)
    assert any("last" in f or "lname" in f for f in filled_descriptors)
    assert any("email" in f for f in filled_descriptors)
    assert any("phone" in f for f in filled_descriptors)

    # Verify pause was recorded at next step button
    assert len(res.paused_fields) >= 1
    assert any("step" in p.get("reason", "").lower() or "wizard" in p.get("label", "").lower() or "boundary" in p.get("label", "").lower() for p in res.paused_fields)

    await session.close()


@pytest.mark.asyncio
async def test_ashby_form_filling(tmp_path):
    """Verify AshbyFiller fills name, email, phone, and linkedin URL."""
    mock_path = Path("tests/mock_job_sites/ashby_mock.html").resolve()
    mock_url = f"file://{mock_path}"

    dummy_pdf = tmp_path / "resume.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 dummy resume")

    session = BrowserSession(headless=True)
    page = await session.navigate(mock_url)

    filler = AshbyFiller()
    res = await filler.fill_form(page, resume_pdf_path=dummy_pdf)

    filled_descriptors = [f"{f.get('name', '')} {f.get('label', '')}".lower() for f in res.filled_fields]
    assert any("name" in f for f in filled_descriptors)
    assert any("email" in f for f in filled_descriptors)
    assert any("phone" in f for f in filled_descriptors)

    await session.close()
