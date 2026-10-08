"""
backend/api/resume.py
Resume generation, tailoring, ATS verification, and compilation endpoints.
"""
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from ai.matcher import load_candidate_data
from ai.resume_tailor import ResumeTailor
from resume.renderer import LaTeXResumeRenderer
from resume.validator import ResumeCompilerValidator, is_latex_compiler_available
from resume.ats_checker import ATSChecker
from config.settings import settings

router = APIRouter()

MASTER_TEX_PATH = Path(settings.master_resume_path)
GENERATED_DIR = Path(settings.resume_generated_dir)


class ResumeTailorRequest(BaseModel):
    job_description: str
    job_title: str = "Software Engineer"
    company: str = "Company"
    required_skills: list[str] = []
    preferred_skills: list[str] = []
    technologies: list[str] = []


@router.get("/master")
async def get_master_resume():
    """Get master resume source, compiler status, and ATS analysis."""
    if not MASTER_TEX_PATH.exists():
        raise HTTPException(status_code=404, detail="master_resume.tex not found")

    tex_source = MASTER_TEX_PATH.read_text(encoding="utf-8")
    is_avail, compiler, _ = is_latex_compiler_available()
    ats_analysis = ATSChecker.check_latex_source(tex_source)

    return {
        "master_tex_exists": True,
        "master_tex_path": str(MASTER_TEX_PATH),
        "latex_compiler_available": is_avail,
        "compiler_name": compiler,
        "ats_analysis": ats_analysis,
        "latex_source": tex_source,
    }


@router.post("/master")
async def create_master_resume():
    """Create a starting source from saved facts, without replacing an existing baseline."""
    if MASTER_TEX_PATH.exists():
        raise HTTPException(409, "A master résumé already exists. Edit that baseline directly.")
    profile, registry = load_candidate_data()
    if not profile.get("identity", {}).get("email"):
        raise HTTPException(409, "Save your candidate profile first.")
    tailor = ResumeTailor(profile, registry)
    plan = tailor._deterministic_tailor({}, [])
    MASTER_TEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    MASTER_TEX_PATH.write_text(LaTeXResumeRenderer.render(profile, plan), encoding="utf-8")
    return {"ok": True, "message": "Master résumé source created. Review it before using it."}


@router.post("/tailor")
async def generate_tailored_resume(request: ResumeTailorRequest):
    """
    Generates a truthful, tailored 1-page LaTeX resume for a specific job posting.
    Validates ATS compliance, verifies truthfulness against master profile,
    and compiles locally if pdflatex is installed.
    """
    if not request.job_description or not request.job_description.strip():
        raise HTTPException(status_code=400, detail="job_description is required")

    profile, registry = load_candidate_data()
    if not profile.get("identity", {}).get("email"):
        raise HTTPException(409, "Save your candidate profile first.")
    tailor = ResumeTailor(profile, registry)

    job_analysis = {
        "job_title": request.job_title,
        "company": request.company,
        "job_description": request.job_description,
        "required_skills": request.required_skills,
        "preferred_skills": request.preferred_skills,
        "technologies": request.technologies,
    }

    # 1. Generate structured tailored plan (truthful, validated)
    tailored_plan = await tailor.tailor(job_analysis)

    # 2. Render LaTeX, enforce 1-page requirement, compile if compiler present
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    slug = f"{request.company.lower().replace(' ', '_')}_{request.job_title.lower().replace(' ', '_')}"[:40]
    slug = "".join(c for c in slug if c.isalnum() or c == "_")
    base_name = f"resume_{slug}" if slug else "tailored_resume"

    result = ResumeCompilerValidator.generate_and_enforce_one_page(
        profile=profile,
        tailored_plan=tailored_plan,
        output_dir=GENERATED_DIR,
        base_name=base_name,
    )

    return {
        "success": True,
        "tailored_plan": tailored_plan,
        "ats_result": result["ats_result"],
        "latex_code": result["latex_code"],
        "latex_path": result["latex_path"],
        "pdf_path": result["pdf_path"],
        "is_compiled": result["is_compiled"],
        "compiler_available": result["compiler_available"],
        "page_count": result["page_count"],
        "is_one_page": result["is_one_page"],
        "notes": result.get("notes"),
        "compile_error": result.get("compile_error"),
        "pdf_valid": result.get("pdf_valid", False),
    }


@router.post("/compile-master")
async def compile_master_resume():
    """Attempts local compilation of the master LaTeX resume."""
    if not MASTER_TEX_PATH.exists():
        raise HTTPException(status_code=404, detail="master_resume.tex not found")

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    result = ResumeCompilerValidator.compile_latex(MASTER_TEX_PATH, GENERATED_DIR)

    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error"),
            "compiler": result.get("compiler"),
        }

    pdf_path = Path(result["pdf_path"])
    val = ResumeCompilerValidator.validate_pdf(pdf_path)

    return {
        "success": val.get("valid", False),
        "pdf_path": str(pdf_path),
        "compiler": result["compiler"],
        "validation": val,
        "error": val.get("error"),
    }


@router.get("/download")
async def download_file(path: str = Query(...)):
    """Serve generated resume files (.tex or .pdf)."""
    file_path = Path(path).resolve()
    allowed_roots = [GENERATED_DIR.resolve(), Path(settings.applications_dir).resolve()]
    allowed = file_path == MASTER_TEX_PATH.resolve() or any(file_path.is_relative_to(root) for root in allowed_roots)
    if not allowed or file_path.suffix.lower() not in {".pdf", ".tex"}:
        raise HTTPException(status_code=403, detail="Access denied.")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    if file_path.suffix.lower() == ".pdf":
        return FileResponse(str(file_path), media_type="application/pdf", filename=file_path.name)
    elif file_path.suffix.lower() == ".tex":
        return PlainTextResponse(file_path.read_text(encoding="utf-8"), media_type="text/plain")
    
    return FileResponse(str(file_path), filename=file_path.name)
