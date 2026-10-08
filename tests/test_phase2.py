"""
tests/test_phase2.py
Automated test suite for Phase 2:
- Job deduplication & URL canonicalization
- Hard eligibility verification
- Deterministic 100-point match scoring
- Blacklist enforcement during project ranking
- API endpoints for job analysis and saving
"""
import pytest
import asyncio
import json
from pathlib import Path

from jobs.dedupe import normalize_url, compute_job_fingerprint
from jobs.eligibility import EligibilityChecker
from jobs.scoring import JobMatchEngine
from agent.safety import is_blacklisted
from ai.matcher import MatchCoordinator


# Load test profile
profile = json.loads(Path("tests/fixtures/profile.json").read_text())
registry = json.loads(Path("profile/project_registry.json").read_text())


def test_url_normalization():
    """Test tracking parameter stripping and canonicalization."""
    raw_url = "https://www.linkedin.com/jobs/view/123456?refId=abc&trackingId=xyz&utm_source=feed"
    clean = normalize_url(raw_url)
    assert "utm_source" not in clean
    assert "trackingId" not in clean
    assert "refId" not in clean
    assert clean == "https://linkedin.com/jobs/view/123456"


def test_fingerprint_generation():
    """Test deterministic fingerprint generation."""
    fp1 = compute_job_fingerprint("Microsoft", "AI Software Engineering Intern", "Python, React, AWS")
    fp2 = compute_job_fingerprint("Microsoft Inc.", "AI Software Engineering Intern", "Python, React, AWS")
    assert fp1 == fp2  # Normalization handles 'Inc.'


def test_eligibility_checks():
    """Test hard eligibility gates."""
    checker = EligibilityChecker(profile)

    # 1. Valid Internship - should PASS
    valid_job = {
        "job_title": "Software Engineering Intern",
        "company": "Stripe",
        "job_description": "We are seeking a summer 2026 software engineering intern pursuing a Bachelor's degree in Computer Science. Experience with Python or JavaScript."
    }
    res = checker.evaluate(valid_job)
    assert res.passed is True, f"Expected pass, got: {res.reasons}"

    # 2. Staff/Senior role requiring 8+ years - should FAIL
    senior_job = {
        "job_title": "Staff Backend Engineer",
        "company": "Amazon",
        "job_description": "Requires 8+ years of professional software development experience. Must lead cross-functional architecture."
    }
    res_senior = checker.evaluate(senior_job)
    assert res_senior.passed is False
    assert any("senior" in r.lower() or "experience" in r.lower() for r in res_senior.reasons)

    # 3. Security Clearance role - should FAIL
    clearance_job = {
        "job_title": "Software Engineer Intern",
        "company": "Defense Corp",
        "job_description": "Must possess active Top Secret clearance / TS/SCI."
    }
    res_clearance = checker.evaluate(clearance_job)
    assert res_clearance.passed is False
    assert any("security clearance" in r.lower() for r in res_clearance.reasons)

    # 4. Ph.D. Only role - should FAIL
    phd_job = {
        "job_title": "AI Research Scientist Intern",
        "company": "ResearchLab",
        "job_description": "Must have a Ph.D. in Computer Science or Mathematics. Doctorates required."
    }
    res_phd = checker.evaluate(phd_job)
    assert res_phd.passed is False
    assert any("ph.d" in r.lower() or "doctorate" in r.lower() or "intern" in r.lower() for r in res_phd.reasons)


def test_scoring_engine():
    """Test deterministic 100-point scoring and project recommendations."""
    engine = JobMatchEngine(profile, registry)

    job_data = {
        "job_title": "AI Software Engineering Intern",
        "company": "Microsoft",
        "required_skills": ["Python", "React", "REST APIs", "SQL"],
        "preferred_skills": ["AWS", "Docker", "Terraform"],
        "technologies": ["Python", "React", "REST APIs", "SQL", "AWS", "Docker"],
        "location": "Remote",
        "job_description": "AI Software Engineering Intern working on Python, React, AWS, and REST APIs."
    }

    breakdown = engine.score(job_data)
    
    # Assert score bounds
    assert 0.0 <= breakdown.total_score <= 100.0
    assert breakdown.total_score >= 70.0  # Strong match for candidate skills

    # Check skills matching
    assert "Python" in breakdown.matched_required_skills
    assert "React" in breakdown.matched_required_skills
    assert "Terraform" in breakdown.missing_preferred_skills

    # Check project selection
    assert len(breakdown.selected_project_ids) > 0
    # Blacklisted projects MUST NEVER appear
    for pid in breakdown.selected_project_ids:
        assert not is_blacklisted(pid), f"SAFETY VIOLATION: {pid} is blacklisted!"
    for p in breakdown.project_rankings:
        assert not is_blacklisted(p["id"]), f"SAFETY VIOLATION: {p['id']} is blacklisted!"


@pytest.mark.asyncio
async def test_match_coordinator_e2e():
    """Test full end-to-end evaluation pipeline."""
    coord = MatchCoordinator()
    jd = """
    Software Engineering Intern - Summer 2026
    Location: Remote, US
    Requirements:
    - Currently enrolled in a B.S. in Computer Science
    - Proficient with Python and JavaScript
    - Experience building web applications and REST APIs
    - Familiarity with cloud platforms (AWS) and Git
    """

    res = await coord.evaluate_job(
        job_description=jd,
        job_title="Software Engineering Intern",
        company="Datadog",
        location="Remote"
    )

    assert res["company"] == "Datadog"
    assert res["eligibility"]["passed"] is True
    assert res["match_score"] > 65.0
    assert res["decision"] == "apply"
    assert len(res["selected_projects"]) >= 2
