"""
resume/validator.py
Local LaTeX compilation, one-page enforcement, selectable text validation, and ATS compliance check.
"""
import os
import shutil
import subprocess
import logging
import hashlib
import copy
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

import pypdf

from resume.renderer import LaTeXResumeRenderer
from resume.ats_checker import ATSChecker

logger = logging.getLogger(__name__)


COMMON_TEX_PATHS = [
    "/Library/TeX/texbin",
    "/usr/local/texlive/bin/universal-darwin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
    "/usr/bin",
]


def find_latex_binary(bin_name: str) -> Optional[str]:
    """Finds a LaTeX binary in PATH or standard system TeX directories."""
    found = shutil.which(bin_name)
    if found:
        return found
    for p in COMMON_TEX_PATHS:
        candidate = Path(p) / bin_name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def is_latex_compiler_available() -> Tuple[bool, str, Optional[str]]:
    """
    Checks if latexmk, pdflatex, or xelatex is available on the system.
    Returns (is_available, compiler_name, binary_path).
    Preference:
    1. latexmk -pdf
    2. pdflatex
    3. xelatex
    """
    # 1. Prefer latexmk
    lmk = find_latex_binary("latexmk")
    if lmk:
        return True, "latexmk", lmk

    # 2. Fall back to pdflatex
    pdf_tex = find_latex_binary("pdflatex")
    if pdf_tex:
        return True, "pdflatex", pdf_tex

    # 3. Fall back to xelatex
    xe_tex = find_latex_binary("xelatex")
    if xe_tex:
        return True, "xelatex", xe_tex

    return False, "none", None


class ResumeCompilerValidator:
    """
    Compiles, validates, and enforces the strict one-page hard requirement on resumes.
    """

    @classmethod
    def compile_latex(cls, tex_path: Path, output_dir: Path, timeout: int = 30) -> Dict[str, Any]:
        """
        Compiles .tex file to .pdf using local latexmk, pdflatex, or xelatex.
        """
        is_avail, compiler, bin_path = is_latex_compiler_available()
        if not is_avail:
            return {
                "success": False,
                "pdf_path": None,
                "compiler": compiler,
                "status": "RESUME_COMPILE_ERROR",
                "error": "LaTeX compiler not found. Install BasicTeX with: brew install --cask basictex",
                "is_compiled": False,
            }

        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_name = tex_path.stem + ".pdf"
        expected_pdf_path = output_dir / pdf_name

        expected_pdf_path.unlink(missing_ok=True)
        try:
            if compiler == "latexmk":
                cmd = [
                    bin_path,
                    "-pdf",
                    "-interaction=nonstopmode",
                    f"-outdir={output_dir.resolve()}",
                    str(tex_path.resolve()),
                ]
            else:
                cmd = [
                    bin_path,
                    "-interaction=nonstopmode",
                    f"-output-directory={output_dir.resolve()}",
                    str(tex_path.resolve()),
                ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(output_dir),
            )

            # Cleanup auxiliary latex files (.aux, .log, .out, .fls, .fdb_latexmk)
            for ext in [".aux", ".log", ".out", ".fls", ".fdb_latexmk"]:
                aux_file = output_dir / (tex_path.stem + ext)
                if aux_file.exists():
                    try:
                        aux_file.unlink()
                    except Exception:
                        pass

            if result.returncode == 0 and expected_pdf_path.exists() and expected_pdf_path.stat().st_size > 0:
                with open(expected_pdf_path, "rb") as f:
                    pdf_hash = hashlib.sha256(f.read()).hexdigest()
                return {
                    "success": True,
                    "pdf_path": str(expected_pdf_path),
                    "pdf_hash": pdf_hash,
                    "compiler": compiler,
                    "error": None,
                    "is_compiled": True,
                }
            else:
                return {
                    "success": False,
                    "pdf_path": None,
                    "compiler": compiler,
                    "status": "RESUME_COMPILE_ERROR",
                    "error": f"Compilation failed: {result.stderr or result.stdout[-500:]}",
                    "is_compiled": False,
                }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "pdf_path": None,
                "compiler": compiler,
                "status": "RESUME_COMPILE_ERROR",
                "error": "LaTeX compilation timed out.",
                "is_compiled": False,
            }
        except Exception as e:
            return {
                "success": False,
                "pdf_path": None,
                "compiler": compiler,
                "status": "RESUME_COMPILE_ERROR",
                "error": str(e),
                "is_compiled": False,
            }

    @classmethod
    def validate_pdf(cls, pdf_path: Path) -> Dict[str, Any]:
        """
        Validates generated PDF:
        - Page count == 1 (HARD REQUIREMENT)
        - Selectable text extraction
        - Section header presence (Education, Projects, Skills)
        - Computes SHA-256 hash
        """
        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            return {
                "valid": False,
                "page_count": 0,
                "selectable_text": False,
                "text_snippet": "",
                "error": "PDF file does not exist or is empty.",
            }

        try:
            reader = pypdf.PdfReader(str(pdf_path))
            page_count = len(reader.pages)
            
            full_text = ""
            for p in reader.pages:
                full_text += p.extract_text() or ""

            has_selectable_text = len(full_text.strip()) > 50

            # One-page check
            is_one_page = (page_count == 1)

            # Section headers check
            required_sections = ["education", "project", "skill"]
            text_lower = full_text.lower()
            missing_sections = [s for s in required_sections if s not in text_lower]

            with open(pdf_path, "rb") as f:
                pdf_hash = hashlib.sha256(f.read()).hexdigest()

            is_valid = is_one_page and has_selectable_text and len(missing_sections) == 0

            error_msg = None
            if not is_one_page:
                error_msg = f"Resume exceeded 1 page (actual: {page_count} pages)."
            elif missing_sections:
                error_msg = f"Missing required resume sections: {missing_sections}"
            elif not has_selectable_text:
                error_msg = "PDF does not contain selectable text."

            return {
                "valid": is_valid,
                "page_count": page_count,
                "is_one_page": is_one_page,
                "selectable_text": has_selectable_text,
                "text_length": len(full_text),
                "text_snippet": full_text[:400],
                "pdf_hash": pdf_hash,
                "missing_sections": missing_sections,
                "error": error_msg,
            }
        except Exception as e:
            return {
                "valid": False,
                "page_count": 0,
                "selectable_text": False,
                "error": f"PDF validation error: {str(e)}",
            }

    @classmethod
    def generate_and_enforce_one_page(
        cls,
        profile: Dict[str, Any],
        tailored_plan: Dict[str, Any],
        output_dir: Path,
        base_name: str = "tailored_resume"
    ) -> Dict[str, Any]:
        """
        Renders LaTeX, compiles PDF, and applies the one-page reduction algorithm
        if compilation produces more than 1 page.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        tex_path = output_dir / f"{base_name}.tex"

        current_plan = copy.deepcopy(tailored_plan)
        reduction_step = 0
        max_reduction_steps = 4
        last_compile_result = {}
        last_pdf_val = {}

        while reduction_step <= max_reduction_steps:
            # 1. Render LaTeX
            latex_code = LaTeXResumeRenderer.render(profile, current_plan)
            tex_path.write_text(latex_code, encoding="utf-8")

            # 2. Check ATS heuristics
            ats_result = ATSChecker.check_latex_source(latex_code)

            # 3. Check if compiler is available
            is_avail, compiler, _ = is_latex_compiler_available()
            if not is_avail:
                # When compiler is not installed, return clean LaTeX with ATS analysis
                return {
                    "latex_path": str(tex_path),
                    "latex_code": latex_code,
                    "pdf_path": None,
                    "is_compiled": False,
                    "compiler_available": False,
                    "ats_result": ats_result,
                    "page_count": None,
                    "is_one_page": False,
                    "reduction_steps_applied": reduction_step,
                    "notes": "LaTeX generated and ATS-verified. Install BasicTeX to enable automated local PDF rendering."
                }

            # 4. Compile PDF
            last_compile_result = cls.compile_latex(tex_path, output_dir)
            if not last_compile_result["success"]:
                # Compilation failed
                return {
                    "latex_path": str(tex_path),
                    "latex_code": latex_code,
                    "pdf_path": None,
                    "is_compiled": False,
                    "compiler_available": True,
                    "compile_error": last_compile_result.get("error"),
                    "ats_result": ats_result,
                    "page_count": 0,
                    "is_one_page": False,
                    "reduction_steps_applied": reduction_step,
                }

            # 5. Validate PDF & Page Count
            pdf_path = Path(last_compile_result["pdf_path"])
            last_pdf_val = cls.validate_pdf(pdf_path)

            if last_pdf_val.get("valid"):
                return {
                    "latex_path": str(tex_path),
                    "latex_code": latex_code,
                    "pdf_path": str(pdf_path),
                    "is_compiled": True,
                    "compiler_available": True,
                    "ats_result": ats_result,
                    "page_count": 1,
                    "is_one_page": True,
                    "selectable_text": last_pdf_val["selectable_text"],
                    "pdf_valid": True,
                    "reduction_steps_applied": reduction_step,
                    "notes": "Resume compiled and validated: exactly 1 page."
                }

            if last_pdf_val.get("page_count", 0) <= 1:
                return {
                    "latex_path": str(tex_path), "latex_code": latex_code,
                    "pdf_path": None, "is_compiled": True, "compiler_available": True,
                    "ats_result": ats_result, "page_count": last_pdf_val.get("page_count", 0),
                    "is_one_page": last_pdf_val.get("page_count") == 1,
                    "pdf_valid": False, "compile_error": last_pdf_val.get("error"),
                    "reduction_steps_applied": reduction_step,
                }

            if reduction_step == max_reduction_steps:
                break

            # If page count > 1, apply reduction rule:
            reduction_step += 1
            projects = current_plan.get("selected_projects", [])

            if reduction_step == 1:
                # Step 1: Trim certifications to top 2
                certs = current_plan.get("certifications", [])
                if len(certs) > 2:
                    current_plan["certifications"] = certs[:2]
            elif reduction_step == 2:
                # Step 2: Trim longest bullet from the lowest-priority (3rd) project
                if len(projects) >= 3 and len(projects[2].get("bullets", [])) > 1:
                    projects[2]["bullets"] = projects[2]["bullets"][:1]
            elif reduction_step == 3:
                # Step 3: Trim 2nd project bullets to top 1
                if len(projects) >= 2 and len(projects[1].get("bullets", [])) > 1:
                    projects[1]["bullets"] = projects[1]["bullets"][:1]
            elif reduction_step == 4:
                # Step 4: Drop 3rd project completely (retain 2 strongest projects)
                if len(projects) > 2:
                    current_plan["selected_projects"] = projects[:2]

        # Return best effort
        return {
            "latex_path": str(tex_path),
            "latex_code": latex_code,
            "pdf_path": None,
            "is_compiled": last_compile_result.get("is_compiled", False),
            "compiler_available": True,
            "ats_result": ats_result,
            "page_count": last_pdf_val.get("page_count", 0),
            "is_one_page": last_pdf_val.get("page_count") == 1,
            "pdf_valid": False,
            "compile_error": last_pdf_val.get("error", "Resume did not pass PDF validation."),
            "reduction_steps_applied": reduction_step,
        }
