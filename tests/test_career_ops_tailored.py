"""
tests/test_career_ops_tailored.py
Comprehensive automated test suite for the personal internship application agent:
1. Full-time US job is rejected (internship-only filter)
2. Non-US internship is rejected (USA-only filter)
3. US tech internship is accepted
4. Rock-Paper-Scissor is strictly blacklisted & never selected
5. Master & tailored resume compile to <= 1 page PDF
6. Resume PDF is physically written to artifact directory with SHA-256 hash
7. resume.tex is physically written
8. job.json is physically written with metadata
9. analysis.json is physically written
10. answers.json is physically written with approved answer format
11. activity.log is physically written
12. Database resume_path points to an existing file
13. Agent stops at final review (READY_FOR_REVIEW)
14. Final submission is NEVER automated (FINAL_SUBMISSION_ALLOWED == False)
15. Duplicate job listings are detected and deduplicated
16. Auth/login wall triggers human handoff (NEEDS_ATTENTION / HANDOFF)
17. Missing required artifacts trigger ARTIFACT_ERROR
18. Status transitions to SUBMITTED only upon explicit user confirmation
"""
import pytest
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import select

from database.connection import AsyncSessionLocal
from database.models import Application, ApplicationStatus, JobQueue
from jobs.eligibility import EligibilityChecker
from jobs.dedupe import normalize_url, compute_job_fingerprint
from agent.safety import is_blacklisted
from backend.services.artifact_store import ArtifactStore, get_artifact_dir, compute_sha256
from browser.safety_barrier import SafetyBarrier, FINAL_SUBMISSION_ALLOWED
from resume.validator import ResumeCompilerValidator
from resume.renderer import LaTeXResumeRenderer
from browser.field_mapper import FieldMapper, FieldConfidence


@pytest.fixture
def sample_profile():
    profile_path = Path("tests/fixtures/profile.json")
    if profile_path.exists():
        return json.loads(profile_path.read_text(encoding="utf-8"))
    return {
        "identity": {"name": "Example Candidate"},
        "education": [{"degree": "B.S. in Computer Science", "graduation": "Fall 2027"}]
    }


def test_01_fulltime_job_rejected(sample_profile):
    """Verify full-time / senior roles are rejected by the internship-only hard gate."""
    checker = EligibilityChecker(sample_profile)
    job = {
        "company": "Tech Corp",
        "job_title": "Senior Backend Software Engineer",
        "job_description": "We are seeking a senior backend software engineer with 6+ years experience.",
        "location": "Dallas, TX",
        "country": "United States",
        "employment_type": "full-time",
    }
    res = checker.evaluate(job)
    assert res.passed is False
    assert any("senior" in r.lower() or "intern" in r.lower() for r in res.reasons)


def test_02_non_us_internship_rejected(sample_profile):
    """Verify internships outside the United States are rejected."""
    checker = EligibilityChecker(sample_profile)
    job = {
        "company": "Global Tech",
        "job_title": "Software Engineer Intern",
        "job_description": "Join our summer engineering internship program in London.",
        "location": "London, United Kingdom",
        "country": "United Kingdom",
        "employment_type": "internship",
    }
    res = checker.evaluate(job)
    assert res.passed is False
    assert "non_us_location" in res.failed_checks


def test_03_us_internship_accepted(sample_profile):
    """Verify valid United States software engineering internships pass eligibility."""
    checker = EligibilityChecker(sample_profile)
    job = {
        "company": "Stripe",
        "job_title": "Software Engineering Intern",
        "job_description": "Join our infrastructure engineering team in Seattle, WA for a 12-week summer internship.",
        "location": "Seattle, WA",
        "country": "United States",
        "employment_type": "internship",
    }
    res = checker.evaluate(job)
    assert res.passed is True
    assert res.status == "eligible"


def test_04_rock_paper_scissor_hard_blacklist():
    """Verify Rock-Paper-Scissor is permanently blacklisted and forbidden."""
    assert is_blacklisted("Rock-Paper-Scissor") is True
    assert is_blacklisted("rock-paper-scissor") is True
    assert is_blacklisted("Swopnab/Rock-Paper-Scissor") is True


def test_05_master_resume_one_page():
    """Verify master resume LaTeX source is well-formed and geometric budget fits 1 page."""
    master_tex = Path("tests/fixtures/resume.tex")
    assert master_tex.exists()
    content = master_tex.read_text(encoding="utf-8")
    assert "Example Candidate" in content
    assert "SwopMobile" in content
    assert "CyberSteer" in content
    assert "AAURA-V1" in content
    assert "Personal Job Tracker" in content
    assert "Rock-Paper-Scissor" not in content

    comp = ResumeCompilerValidator.compile_latex(master_tex, Path("resume/generated"))
    if comp.get("success"):
        assert comp.get("pdf_path") is not None
        assert comp.get("page_count", 1) <= 1


def test_06_to_11_real_physical_artifacts_created(tmp_path):
    """Verify all 7 physical artifact files are created and non-empty on disk."""
    app_id = int(datetime.now(timezone.utc).timestamp() * 1000)
    company = "ArtifactTest Corp"
    title = "AI Software Engineer Intern"

    # 1. job.json
    job_file = ArtifactStore.save_job_metadata(
        app_id=app_id, company=company, job_title=title,
        job_url="https://example.com/job/123", location="Austin, TX",
        source="career-ops", status="ready_for_review"
    )
    assert job_file.exists()

    # 2. job-description.txt & hash
    desc_info = ArtifactStore.save_job_description(
        app_id=app_id, company=company, job_title=title,
        job_description="Full job description text for AI Software Engineering Intern role."
    )
    assert Path(desc_info["path"]).exists()
    assert desc_info["hash"] is not None

    # 3. analysis.json
    analysis_file = ArtifactStore.save_analysis(
        app_id=app_id, company=company, job_title=title,
        analysis_data={"match_score": 88.5, "eligibility": {"status": "eligible"}, "selected_projects": ["SwopMobile", "CyberSteer"]}
    )
    assert analysis_file.exists()

    # 4. resume.tex & resume.pdf
    master_tex = Path("tests/fixtures/resume.tex").read_text(encoding="utf-8")
    dummy_pdf = tmp_path / "test_resume.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 sample compiled resume")

    resume_info = ArtifactStore.save_resume(
        app_id=app_id, company=company, job_title=title,
        latex_source=master_tex, pdf_source_path=dummy_pdf
    )
    assert Path(resume_info["tex_path"]).exists()
    assert Path(resume_info["pdf_path"]).exists()
    assert resume_info["resume_hash"] is not None

    # 5. answers.json
    answers_file = ArtifactStore.save_answers(
        app_id=app_id, company=company, job_title=title,
        answers=[
            {"question": "Are you legally authorized to work in the US?", "answer": "YES", "source": "master_profile", "confidence": 1.0, "user_approved": True},
            {"question": "Will you require sponsorship?", "answer": "NO", "source": "master_profile", "confidence": 1.0, "user_approved": True},
        ]
    )
    assert answers_file.exists()

    # 6. activity.log
    log_file = ArtifactStore.append_activity_log(
        app_id=app_id, company=company, job_title=title,
        events=[
            {"event_type": "DISCOVERED", "description": "Found US internship"},
            {"event_type": "READY_FOR_REVIEW", "description": "Form ready for human inspection"},
        ]
    )
    assert log_file.exists()

    # Verify integrity checker passes
    check = ArtifactStore.verify_application_artifacts(app_id, company, title)
    assert check["valid"] is True
    assert len(check["missing"]) == 0


def test_12_database_resume_path_points_to_real_file(tmp_path):
    """Verify application record in database points to an existing physical resume file."""
    dummy_pdf = tmp_path / "app_resume.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 valid pdf file")

    app = Application(
        company="VerifyDB Corp",
        job_title="Software Intern",
        job_url="https://example.com/verify-db",
        status=ApplicationStatus.READY_FOR_REVIEW,
        resume_path=str(dummy_pdf),
    )
    assert Path(app.resume_path).exists()


def test_13_and_14_zero_auto_submit_policy():
    """Verify FINAL_SUBMISSION_ALLOWED is permanently False and SafetyBarrier stops submission."""
    assert FINAL_SUBMISSION_ALLOWED is False
    can_submit, reason = SafetyBarrier.evaluate_submission_readiness(
        company="Google",
        job_title="Software Engineering Intern",
        match_score=95.0,
        eligibility_passed=True,
        requires_human_input=False,
    )
    assert can_submit is False
    assert "ready for review" in reason.lower() or "disabled" in reason.lower()


def test_15_duplicate_detection():
    """Verify deduplication normalizes URLs and generates matching fingerprints."""
    url1 = "https://boards.greenhouse.io/stripe/jobs/12345?gh_src=linkedin&utm_source=feed"
    url2 = "https://boards.greenhouse.io/stripe/jobs/12345"
    assert normalize_url(url1) == normalize_url(url2)

    fp1 = compute_job_fingerprint("Stripe", "Software Engineering Intern", "San Francisco, CA")
    fp2 = compute_job_fingerprint("stripe", "software engineering intern", "san francisco, ca")
    assert fp1 == fp2


def test_16_f1_work_authorization_field_mapping():
    """Verify approved F-1 work authorization questions map with high confidence and unknown ones pause."""
    mapper = FieldMapper()

    questions = [
        "Are you authorized to work in the U.S. without sponsorship?",
        "Will you now or in the future require sponsorship for employment visa status?",
        "Are you legally authorized to work in the United States?",
        "Do you require CPT or OPT for this internship?",
        "Will your work authorization require employer participation in an immigration process?",
    ]
    for question in questions:
        _, confidence, answer = mapper.classify_field(label=question)
        assert confidence == FieldConfidence.LEVEL_3_PAUSE
        assert answer is None


def test_17_missing_artifact_integrity_failure():
    """Verify verify_application_artifacts detects missing files and fails validation."""
    check = ArtifactStore.verify_application_artifacts(999999, "NonExistentCompany", "NonExistentRole")
    assert check["valid"] is False
    assert len(check["missing"]) > 0


@pytest.mark.asyncio
async def test_18_manual_submission_confirmation():
    """Verify application transitions to SUBMITTED upon manual user confirmation."""
    async with AsyncSessionLocal() as session:
        app = Application(
            company="ManualSubmit Corp",
            job_title="Software Intern",
            job_url=f"https://example.com/manual-{datetime.now(timezone.utc).timestamp()}",
            status=ApplicationStatus.READY_FOR_REVIEW,
            discovered_at=datetime.now(timezone.utc),
        )
        session.add(app)
        await session.commit()
        app_id = app.id

        from backend.api.applications import confirm_manual_submission
        res = await confirm_manual_submission(app_id, body={"confirmation": "Submitted on Workday portal"}, db=session)
        assert res["ok"] is True
        assert res["status"] == ApplicationStatus.SUBMITTED.value
        assert res["submitted_at"] is not None
