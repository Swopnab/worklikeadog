"""
tests/test_phase3.py
Automated test suite for Phase 3:
- Deterministic LaTeX resume rendering
- ATS compliance and formatting heuristics
- Truthful project and skill tailoring
- Blacklist safety enforcement in resume generation
- LaTeX escaping of special characters
"""
import pytest
import json
from pathlib import Path

from resume.renderer import LaTeXResumeRenderer
from resume.ats_checker import ATSChecker
from resume.latex_escape import escape
from ai.resume_tailor import ResumeTailor
from resume.validator import ResumeCompilerValidator
from agent.safety import is_blacklisted, assert_not_blacklisted


profile = json.loads(Path("tests/fixtures/profile.json").read_text())
registry = json.loads(Path("profile/project_registry.json").read_text())


def test_latex_escape():
    """Test LaTeX character escaping."""
    assert escape("AWS S3 & IAM") == r"AWS S3 \& IAM"
    assert escape("99% accuracy") == r"99\% accuracy"
    assert escape("user_id") == r"user\_id"
    assert escape("#1 ranked") == r"\#1 ranked"
    assert escape("$100k") == r"\$100k"
    assert escape("{nested}") == r"\{nested\}"


def test_master_resume_ats_compliance():
    """Test that master_resume.tex scores 100% on ATS checks."""
    master_tex = Path("tests/fixtures/resume.tex").read_text()
    res = ATSChecker.check_latex_source(master_tex)
    
    assert res["is_ats_compliant"] is True
    assert res["ats_score"] == 100
    assert "Education" in res["found_sections"]
    assert "Technical Skills" in res["found_sections"]
    assert "Projects" in res["found_sections"]
    assert res["formatting_checks"]["single_column"] is True
    assert res["formatting_checks"]["no_images"] is True
    assert res["formatting_checks"]["no_complex_tables"] is True


@pytest.mark.asyncio
async def test_resume_tailor_truthfulness():
    """Test that resume tailor only includes verified candidate data."""
    tailor = ResumeTailor(profile, registry)

    job_analysis = {
        "job_title": "Full-Stack Engineer Intern",
        "company": "Figma",
        "job_description": "Looking for students skilled in React, TypeScript, Python, and cloud services.",
        "required_skills": ["React", "TypeScript", "Python"],
        "preferred_skills": ["AWS", "Docker"],
        "technologies": ["React", "TypeScript", "Python", "AWS", "Docker"],
    }

    plan = await tailor.tailor(job_analysis)
    
    # 1. Verify 3 projects selected
    assert len(plan["selected_projects"]) == 3

    # 2. Check no blacklisted projects are included
    for p in plan["selected_projects"]:
        pid = p["id"]
        assert not is_blacklisted(pid), f"SAFETY VIOLATION: Blacklisted project {pid} in resume!"
        assert not is_blacklisted(p["display_name"]), f"SAFETY VIOLATION: {p['display_name']} in resume!"

    # 3. Check skills ordering (matching skills should lead)
    languages = plan["skills"]["languages"]
    assert languages[0].lower() == "python"  # Python was required

    web_skills = plan["skills"]["web_and_backend"]
    assert "React" in web_skills[:2]  # React was required


def test_latex_renderer_output():
    """Test deterministic LaTeX rendering and structural integrity."""
    tailor = ResumeTailor(profile, registry)
    plan = {
        "selected_projects": [
            {
                "id": "swopmobile",
                "display_name": "SwopMobile — JWT Authentication, RBAC & AI Workspace",
                "subtitle": "Full-Stack Authentication and Multi-App Platform",
                "years": "2025--2026",
                "tech_stack": ["JavaScript", "Cloudflare Workers", "Hono", "Flask", "Ollama"],
                "bullets": [
                    "Built a serverless authentication platform supporting 3 RBAC roles with JWT access tokens and per-user data isolation.",
                    "Improved account security with PBKDF2-SHA256 password hashing and 15-minute access tokens."
                ]
            },
            {
                "id": "cybersteer",
                "display_name": "CyberSteer — Hand-Controlled Racing Game",
                "subtitle": "Computer Vision / Browser Game",
                "years": "2026",
                "tech_stack": ["JavaScript", "HTML5 Canvas", "MediaPipe Hands", "CSS3"],
                "bullets": [
                    "Built a real-time browser racing game by mapping 21 MediaPipe hand landmarks into steering controls."
                ]
            },
            {
                "id": "aaura-v1",
                "display_name": "AAURA-V1 — Advanced AI-Utilized Responsive Assistant",
                "subtitle": "Full-Stack AI Application",
                "years": "2024",
                "tech_stack": ["Python", "Django", "React", "TypeScript", "AWS", "OpenAI API"],
                "bullets": [
                    "Built a full-stack AI assistant with Django REST Framework, React, and OpenAI API integration."
                ]
            }
        ],
        "skills": {
            "languages": ["Python", "JavaScript", "TypeScript", "SQL"],
            "web_and_backend": ["React", "Django", "Flask", "REST APIs"],
            "ai_ml": ["PyTorch", "Google MediaPipe", "Ollama"],
            "cloud_databases": ["AWS S3", "Cloudflare Workers", "SQLite"],
            "security": ["JWT Authentication", "RBAC", "PBKDF2-SHA256"],
            "tools": ["Git", "GitHub", "Docker", "Linux"]
        },
        "certifications": [
            "Microsoft Azure Essentials Professional Certificate",
            "Career Essentials in Software Development"
        ]
    }

    latex_code = LaTeXResumeRenderer.render(profile, plan)
    
    # Assert standard LaTeX requirements
    assert r"\documentclass[10pt, letterpaper]{article}" in latex_code
    assert "Example Candidate" in latex_code
    assert "Example University in Arlington" in latex_code
    assert "Fall 2027" in latex_code
    assert r"\section{Education}" in latex_code
    assert r"\section{Technical Skills}" in latex_code
    assert r"\section{Projects}" in latex_code
    assert r"\section{Certifications}" in latex_code
    assert "Rock-Paper-Scissor" not in latex_code

    # ATS check on rendered output
    ats_res = ATSChecker.check_latex_source(latex_code)
    assert ats_res["is_ats_compliant"] is True
    assert ats_res["ats_score"] == 100


def test_blacklist_hard_enforcement():
    """Verify that renderer will actively reject any blacklisted project."""
    bad_plan = {
        "selected_projects": [
            {
                "id": "rock-paper-scissor",
                "display_name": "Rock-Paper-Scissor",
                "subtitle": "Game",
                "years": "2025",
                "tech_stack": ["HTML", "CSS", "JavaScript"],
                "bullets": ["Trivial game"]
            }
        ],
        "skills": {},
        "certifications": []
    }

    with pytest.raises(ValueError) as exc:
        LaTeXResumeRenderer.render(profile, bad_plan)
    assert "SAFETY VIOLATION" in str(exc.value)
