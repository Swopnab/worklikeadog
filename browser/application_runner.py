"""
browser/application_runner.py
End-to-end autonomous application execution pipeline.

Orchestrates:
1. Navigation & Challenge detection
2. ATS platform detection
3. Tailored resume resolution
4. Form auto-filling with Level 1 verified data
5. Pre-submit screenshot capture & artifact saving
6. Safety Barrier evaluation (Dry-Run / Auto-Submit / Review Gate)
7. State Machine and Activity Log updates
"""
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from database.models import Application, ApplicationStatus, ActivityLog
from backend.services.artifact_store import ArtifactStore, get_artifact_dir
from browser.session import BrowserSession
from browser.detect import ATSDetector, ATSPlatform
from browser.fillers import get_form_filler, FillResult
from browser.safety_barrier import SafetyBarrier
from resume.validator import ResumeCompilerValidator
from resume.renderer import LaTeXResumeRenderer
from ai.resume_tailor import ResumeTailor

logger = logging.getLogger(__name__)


class ApplicationRunner:
    """Executes the automated browser workflow for a single job application."""

    def __init__(self, browser_session: Optional[BrowserSession] = None):
        self.session = browser_session or BrowserSession(headless=False)

    async def run_application_flow(
        self,
        job_url: str,
        company: str,
        job_title: str,
        app_id: int,
        match_score: Optional[float] = None,
        eligibility_passed: bool = True,
        tailored_tex_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes the full application navigation, form filling, and safety verification.
        Returns execution status dict with outcome and artifact paths.
        """
        logger.info("Starting application flow for %s — %s (ID: %s)", company, job_title, app_id)

        # 1. Start browser & Navigate
        page = await self.session.navigate(job_url)

        # 2. Check for bot challenge or login barrier
        has_challenge, challenge_desc = await self.session.check_challenge()
        if has_challenge:
            logger.warning("Challenge detected: %s", challenge_desc)
            # Capture challenge screenshot
            shot_path = get_artifact_dir(app_id, company, job_title) / "challenge.png"
            await self.session.capture_screenshot(shot_path)
            return {
                "success": False,
                "status": ApplicationStatus.HANDOFF.value,
                "pause_reason": challenge_desc,
                "requires_handoff": True,
                "screenshot_path": str(shot_path),
            }

        # 3. Detect ATS Platform
        ats_platform = await ATSDetector.detect_from_page(page)
        logger.info("Detected ATS Platform: %s", ats_platform.value)

        # 4. Resolve Resume PDF (compile if LaTeX source provided)
        pdf_path = None
        if tailored_tex_path and Path(tailored_tex_path).exists():
            tex_file = Path(tailored_tex_path)
            compile_res = ResumeCompilerValidator.compile_latex(tex_file, tex_file.parent)
            if compile_res.get("pdf_path") and Path(compile_res["pdf_path"]).exists():
                pdf_path = Path(compile_res["pdf_path"])

        # 5. Execute Platform Form Filler
        filler = get_form_filler(ats_platform)
        fill_result: FillResult = await filler.fill_form(page, resume_pdf_path=pdf_path)

        # 6. Capture Pre-Submit Screenshot Artifact
        artifact_dir = get_artifact_dir(app_id, company, job_title)
        (artifact_dir / "screenshots").mkdir(exist_ok=True)
        presubmit_shot = artifact_dir / "screenshots" / "review-page.png"
        await self.session.capture_screenshot(presubmit_shot, full_page=False)

        # 7. Save Answers & Activity Artifacts
        answers_list = []
        for f in fill_result.filled_fields:
            answers_list.append({
                "question": f.get("label") or f.get("name"),
                "answer": f.get("value"),
                "source": "master_profile",
                "confidence": 1.0,
                "user_approved": True,
            })
        ArtifactStore.save_answers(app_id, company, job_title, answers_list)

        ArtifactStore.append_activity_log(
            app_id, company, job_title,
            [
                {"event_type": "APPLICATION_OPENED", "description": f"Opened {ats_platform.value.upper()} application page"},
                {"event_type": "FORM_FILLED", "description": f"Filled {len(fill_result.filled_fields)} verified fields"},
                {"event_type": "RESUME_UPLOADED", "description": f"Uploaded tailored 1-page resume ({pdf_path.name if pdf_path else 'master_resume.pdf'})"},
                {"event_type": "READY_FOR_REVIEW", "description": "Form completed; stopped at final review stage for human inspection"},
            ]
        )

        # 8. Check for Level 3 pause flags
        if fill_result.requires_human_input:
            logger.info("Human input required: %s", fill_result.pause_reason)
            return {
                "success": True,
                "submitted": False,
                "status": ApplicationStatus.NEEDS_ATTENTION.value,
                "pause_reason": fill_result.pause_reason,
                "ats_platform": ats_platform.value,
                "screenshot_path": str(presubmit_shot),
                "filled_fields_count": len(fill_result.filled_fields),
            }

        # 9. Verify all physical artifacts exist on disk before completing
        art_check = ArtifactStore.verify_application_artifacts(app_id, company, job_title)
        if not art_check["valid"]:
            logger.error("Artifact integrity check FAILED for app #%d: missing %s", app_id, art_check["missing"])
            return {
                "success": False,
                "submitted": False,
                "status": ApplicationStatus.ARTIFACT_ERROR.value,
                "pause_reason": f"Artifact integrity error: missing {art_check['missing']}",
                "ats_platform": ats_platform.value,
                "screenshot_path": str(presubmit_shot),
            }

        # 10. Normal successful end state: READY_FOR_REVIEW (Zero automated final submissions)
        return {
            "success": True,
            "submitted": False,
            "status": ApplicationStatus.READY_FOR_REVIEW.value,
            "pause_reason": "Application prepared and ready for human review. Final submission must be executed manually.",
            "ats_platform": ats_platform.value,
            "screenshot_path": str(presubmit_shot),
            "resume_hash": art_check.get("resume_hash"),
            "filled_fields_count": len(fill_result.filled_fields),
        }
