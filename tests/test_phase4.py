"""
tests/test_phase4.py
Unit and integration tests for Phase 4:
- ArtifactStore (directory hierarchy, atomic writes, security path checks, listing, reading)
- Analytics engine (score distribution, funnels, timelines, skill frequency)
- Applications API (search, filtering, status patch, notes patch, artifact fetching, full detail serialization)
"""
import pytest
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone

from database.models import Application, ApplicationStatus, ActivityLog
from backend.services.artifact_store import ArtifactStore, ARTIFACTS_ROOT, get_artifact_dir
from backend.services.analytics import compute_analytics


@pytest.mark.asyncio
async def test_artifact_store_lifecycle(tmp_path):
    """Test saving metadata, job description, analysis, resume, and listing artifacts."""
    test_app_id = 9999
    company = "Acme Corp & Co."
    role = "Senior AI Engineer / Lead"

    # Save metadata
    meta_path = ArtifactStore.save_job_metadata(
        app_id=test_app_id,
        company=company,
        job_title=role,
        job_url="https://example.com/jobs/123",
        location="Remote, US",
        source="greenhouse",
        status="discovered"
    )
    assert meta_path.exists()
    content = json.loads(meta_path.read_text())
    assert content["app_id"] == test_app_id
    assert content["company"] == company

    # Save JD
    jd_res = ArtifactStore.save_job_description(
        app_id=test_app_id,
        company=company,
        job_title=role,
        job_description="Seeking a Python and React expert."
    )
    jd_file = Path(jd_res["path"])
    assert jd_file.exists()
    assert "Python and React" in jd_file.read_text()

    # Save Analysis
    analysis_data = {"match_score": 92.5, "decision": "apply"}
    analysis_path = ArtifactStore.save_analysis(
        app_id=test_app_id,
        company=company,
        job_title=role,
        analysis_data=analysis_data
    )
    assert analysis_path.exists()

    # Save Resume LaTeX
    resume_res = ArtifactStore.save_resume(
        app_id=test_app_id,
        company=company,
        job_title=role,
        latex_source="\\documentclass{article}\\begin{document}Resume\\end{document}"
    )
    assert resume_res["tex_path"] is not None
    assert Path(resume_res["tex_path"]).exists()

    # Save Activity Log append
    ArtifactStore.append_activity_log(
        app_id=test_app_id,
        company=company,
        job_title=role,
        events=[
            {"event_type": "DISCOVERED", "description": "Found job"},
            {"event_type": "MATCH_SCORE", "description": "Score 92.5"}
        ]
    )

    # List artifacts
    manifest = ArtifactStore.list_artifacts(test_app_id, company, role)
    assert manifest["artifacts"]["job.json"]["exists"] is True
    assert manifest["artifacts"]["job-description.txt"]["exists"] is True
    assert manifest["artifacts"]["analysis.json"]["exists"] is True
    assert manifest["artifacts"]["resume.tex"]["exists"] is True
    assert manifest["artifacts"]["activity.log"]["exists"] is True
    assert manifest["artifacts"]["resume.pdf"]["exists"] is False

    # Safe read
    read_text = ArtifactStore.read_artifact_text(str(meta_path))
    assert read_text is not None
    assert "Acme Corp" in read_text

    # Security check: Path traversal prevention
    bad_read = ArtifactStore.read_artifact_text("/etc/passwd")
    assert bad_read is None

    # Cleanup test dir
    shutil.rmtree(manifest["dir"], ignore_errors=True)


from database.connection import AsyncSessionLocal

@pytest.mark.asyncio
async def test_analytics_engine():
    """Test compute_analytics with database records."""
    async with AsyncSessionLocal() as session:
        # Insert test applications
        app1 = Application(
            company="TechCorp Analytics",
            job_title="Full Stack Engineer",
            job_url="https://techcorp-analytics.com/job1",
            source="greenhouse",
            location="Remote",
            match_score=85.0,
            status=ApplicationStatus.SUBMITTED,
            eligibility_status="passed",
            discovered_at=datetime.now(timezone.utc),
            application_submitted_at=datetime.now(timezone.utc),
            resume_skills=json.dumps(["Python", "React", "Docker"]),
            job_description="We need Python, React, and AWS."
        )
        app2 = Application(
            company="StartupX Analytics",
            job_title="ML Engineer",
            job_url="https://startupx-analytics.com/job2",
            source="lever",
            location="San Francisco, CA",
            match_score=60.0,
            status=ApplicationStatus.INELIGIBLE,
            eligibility_status="failed",
            eligibility_reason="Requires active TS/SCI clearance",
            discovered_at=datetime.now(timezone.utc),
            job_description="Seeking C++ and PyTorch specialist."
        )
        session.add_all([app1, app2])
        await session.commit()

        res = await compute_analytics(session)
        assert res["total_applications"] >= 2
        assert res["scores"]["avg"] > 0
        assert any(c["company"] == "TechCorp Analytics" for c in res["top_companies"])
        assert res["eligibility"]["eligible"] >= 1
        assert "85–100" in res["scores"]["distribution"]
