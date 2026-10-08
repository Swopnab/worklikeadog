"""
agent/orchestrator.py
Autonomous job processing orchestrator.

Coordinates the complete end-to-end pipeline for queued jobs:
1. Dequeues jobs by priority and timestamp
2. Checks daily submission rate limits
3. Fetches posting content and normalizes URLs
4. Verifies hard eligibility gates
5. Computes 100-point match score and ranks verified projects
6. Generates tailored 1-page LaTeX resume
7. Executes browser form filling & pre-submit screenshot archiving
8. Evaluates safety barrier and manages human handoff
9. Applies human-like rate limiting delays between jobs
"""
import asyncio
import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from database.connection import AsyncSessionLocal
from database.models import (
    Application,
    ApplicationStatus,
    JobQueue,
    ActivityLog,
    AgentStateEnum,
)
from agent.state_machine import (
    transition_state,
    should_stop,
    should_pause,
    get_current_state,
)
from jobs.dedupe import normalize_url, compute_job_fingerprint
from jobs.eligibility import EligibilityChecker
from ai.matcher import MatchCoordinator, load_candidate_data
from ai.resume_tailor import ResumeTailor
from resume.renderer import LaTeXResumeRenderer
from resume.validator import ResumeCompilerValidator
from resume.ats_checker import ATSChecker
from backend.services.artifact_store import ArtifactStore, get_artifact_dir
from browser.session import BrowserSession
from browser.application_runner import ApplicationRunner

logger = logging.getLogger(__name__)


class JobOrchestrator:
    """Manages the autonomous execution loop processing jobs from the queue."""

    def __init__(self, browser_session: Optional[BrowserSession] = None):
        self.browser_session = browser_session or BrowserSession(headless=settings.dry_run)
        self.runner = ApplicationRunner(browser_session=self.browser_session)
        self.matcher = MatchCoordinator()

    async def get_next_job(self, db: AsyncSession) -> Optional[JobQueue]:
        """Fetches the next unprocessed job ordered by priority and queue date."""
        query = (
            select(JobQueue)
            .where(JobQueue.processed == False)
            .order_by(JobQueue.priority.asc(), JobQueue.queued_at.asc())
            .limit(1)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def check_daily_limit(self, db: AsyncSession) -> bool:
        """Returns True if within daily limit, False if limit reached."""
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        query = select(func.count()).where(
            Application.status == ApplicationStatus.SUBMITTED,
            Application.application_submitted_at >= today_start,
        )
        count = (await db.execute(query)).scalar_one()
        max_daily = getattr(settings, "max_applications_per_day", 15)
        if count >= max_daily:
            logger.info("Daily application limit reached (%d/%d)", count, max_daily)
            return False
        return True

    async def process_job(self, job: JobQueue, db: AsyncSession) -> Dict[str, Any]:
        """Runs the complete application pipeline on a single job."""
        logger.info("Processing job ID #%d: %s", job.id, job.job_url)

        # 1. Deduplication check
        canonical_url = normalize_url(job.job_url)
        existing_app_res = await db.execute(
            select(Application).where(
                (Application.canonical_job_url == canonical_url) |
                (Application.job_url == job.job_url)
            )
        )
        existing_app = existing_app_res.scalar_one_or_none()
        if existing_app and existing_app.status in (ApplicationStatus.SUBMITTED, ApplicationStatus.APPLYING):
            logger.info("Job already applied / applying: %s", canonical_url)
            job.processed = True
            job.processed_at = datetime.now(timezone.utc)
            await db.commit()
            return {"skipped": True, "reason": "Already applied"}

        # 2. Extract description & Evaluate
        app = existing_app or Application(
            company=job.company or "Unknown Company",
            job_title=job.job_title or "Software Engineer",
            job_url=job.job_url,
            canonical_job_url=canonical_url,
            source=job.source or "queue",
            status=ApplicationStatus.DISCOVERED,
            discovered_at=datetime.now(timezone.utc),
        )
        if not existing_app:
            db.add(app)
            await db.flush()

        job.application_id = app.id
        await db.commit()

        # Update FSM checkpoint
        await transition_state(AgentStateEnum.RUNNING, checkpoint=f"analyzing_job_{app.id}", task_id=app.id)

        # 3. Match Evaluation & Eligibility
        evaluation = await self.matcher.evaluate_job(
            job_description=app.job_description or "",
            job_url=app.job_url,
            company=app.company,
            job_title=app.job_title,
        )

        app.company = evaluation.get("company", app.company)
        app.job_title = evaluation.get("job_title", app.job_title)
        app.job_description = evaluation.get("job_description", app.job_description)
        app.match_score = evaluation.get("match_score", 0.0)
        app.match_details = json.dumps(evaluation.get("score_breakdown", {}))

        eligibility = evaluation.get("eligibility", {})
        elig_passed = eligibility.get("passed", True)
        elig_reason = eligibility.get("reason", "")
        app.eligibility_status = "passed" if elig_passed else "failed"
        app.eligibility_reason = elig_reason

        skills = evaluation.get("skills", {})
        matched_req = skills.get("matched_required", [])
        matched_pref = skills.get("matched_preferred", [])
        app.resume_skills = json.dumps(matched_req + matched_pref)

        project_rankings = evaluation.get("project_rankings", [])
        app.resume_projects = json.dumps(project_rankings[:3])

        # Save initial analysis artifacts
        ArtifactStore.save_job_metadata(
            app.id, app.company, app.job_title, app.job_url,
            app.location or "", app.source or "queue", app.status.value
        )
        ArtifactStore.save_job_description(app.id, app.company, app.job_title, app.job_description or "")
        ArtifactStore.save_analysis(app.id, app.company, app.job_title, evaluation)

        # Check Hard Eligibility Gate
        if not elig_passed:
            logger.info("Job #%d failed eligibility: %s", app.id, elig_reason)
            app.status = ApplicationStatus.INELIGIBLE
            job.processed = True
            job.processed_at = datetime.now(timezone.utc)
            await db.commit()
            return {"success": False, "status": "ineligible", "reason": elig_reason}

        # Check Match Score Threshold
        min_score = getattr(settings, "min_match_score", 60.0)
        if app.match_score < min_score:
            logger.info("Job #%d match score (%0.1f) below threshold (%0.1f)", app.id, app.match_score, min_score)
            app.status = ApplicationStatus.SKIPPED
            job.processed = True
            job.processed_at = datetime.now(timezone.utc)
            await db.commit()
            return {"success": False, "status": "skipped", "reason": "Score below minimum"}

        # 4. Generate Tailored 1-Page Resume
        profile, registry = load_candidate_data()
        tailor = ResumeTailor(profile, registry)
        parsed_reqs = evaluation.get("parsed_requirements", {})
        job_analysis = {
            "job_title": app.job_title,
            "company": app.company,
            "job_description": app.job_description or "",
            "required_skills": matched_req,
            "preferred_skills": matched_pref,
            "technologies": parsed_reqs.get("technologies", []),
        }
        tailored_plan = await tailor.tailor(job_analysis)
        latex_source = LaTeXResumeRenderer.render(profile, tailored_plan)
        initial_save = ArtifactStore.save_resume(app.id, app.company, app.job_title, latex_source=latex_source)
        tex_path = initial_save["tex_path"]

        # Compile resume to PDF
        tex_file = Path(tex_path)
        comp_res = ResumeCompilerValidator.generate_and_enforce_one_page(
            profile, tailored_plan, tex_file.parent, base_name=tex_file.stem)
        pdf_path = None
        if comp_res.get("is_compiled") and comp_res.get("is_one_page") and comp_res.get("pdf_path"):
            candidate_pdf = Path(comp_res["pdf_path"])
            validation = ResumeCompilerValidator.validate_pdf(candidate_pdf)
            if validation.get("valid"):
                pdf_path = candidate_pdf
        # A project summary or unrelated master PDF cannot replace a failed tailored résumé.

        if not pdf_path or not Path(pdf_path).exists():
            error_detail = comp_res.get("compile_error") or comp_res.get("notes") or "Tailored résumé PDF could not be compiled and validated"
            logger.error("Resume compilation failed for app #%d: %s", app.id, error_detail)
            app.status = ApplicationStatus.RESUME_COMPILE_ERROR
            app.resume_compiler_error = error_detail
            app.pause_reason = f"LaTeX compilation error: {error_detail}"
            job.processed = True
            job.processed_at = datetime.now(timezone.utc)
            await db.commit()
            return {"success": False, "status": "resume_compile_error", "error": error_detail}

        latex_source = comp_res.get("latex_code", latex_source)
        save_res = ArtifactStore.save_resume(app.id, app.company, app.job_title, latex_source=latex_source, pdf_source_path=pdf_path)
        app.resume_path = save_res["pdf_path"] or save_res["tex_path"]
        app.resume_hash = save_res.get("resume_hash")
        app.status = ApplicationStatus.RESUME_GENERATED
        await db.commit()

        # 5. Run Browser Form Filling
        app.status = ApplicationStatus.APPLYING
        app.application_started_at = datetime.now(timezone.utc)
        await db.commit()
        await transition_state(AgentStateEnum.RUNNING, checkpoint=f"applying_job_{app.id}", task_id=app.id)

        flow_res = await self.runner.run_application_flow(
            job_url=app.job_url,
            company=app.company,
            job_title=app.job_title,
            app_id=app.id,
            match_score=app.match_score,
            eligibility_passed=elig_passed,
            tailored_tex_path=tex_path,
            prepared_pdf_path=str(pdf_path),
        )

        # 6. Process Flow Result & Enforce Review Gate (Never Auto-Submit)
        final_status = flow_res.get("status", ApplicationStatus.READY_FOR_REVIEW.value)
        try:
            app.status = ApplicationStatus(final_status)
        except ValueError:
            app.status = ApplicationStatus.READY_FOR_REVIEW

        app.pause_reason = flow_res.get("pause_reason")
        app.review_required = True
        app.review_completed = False
        app.submission_confirmed_by_user = False
        job.processed = True
        job.processed_at = datetime.now(timezone.utc)
        await db.commit()

        await db.commit()

        # Handle FSM state transitions for Handoff / Attention
        if flow_res.get("requires_handoff"):
            try:
                from backend.services.webhook import dispatch_webhook_event
                await dispatch_webhook_event("HANDOFF_REQUIRED", {
                    "application_id": app.id,
                    "company": app.company,
                    "job_title": app.job_title,
                    "reason": flow_res.get("pause_reason", "Challenge or login detected"),
                })
            except Exception:
                pass
            await transition_state(
                AgentStateEnum.HANDOFF,
                checkpoint=f"handoff_challenge_{app.id}",
                task_id=app.id,
            )
        elif final_status in (ApplicationStatus.NEEDS_ATTENTION.value, ApplicationStatus.PAUSED.value):
            try:
                from backend.services.webhook import dispatch_webhook_event
                await dispatch_webhook_event("HANDOFF_REQUIRED", {
                    "application_id": app.id,
                    "company": app.company,
                    "job_title": app.job_title,
                    "reason": app.pause_reason or "Pre-submit verification required",
                })
            except Exception:
                pass
            await transition_state(
                AgentStateEnum.NEEDS_ATTENTION,
                checkpoint=f"needs_attention_{app.id}",
                task_id=app.id,
            )

        return flow_res

    async def run_loop(self):
        """Continuous worker loop processing queued jobs until stopped or paused."""
        logger.info("JobOrchestrator run loop started.")

        try:
            while True:
                # 1. Check stop / pause signals
                if await should_stop():
                    logger.info("Stop requested in orchestrator loop.")
                    break

                if await should_pause():
                    logger.info("Pause requested in orchestrator loop.")
                    await transition_state(AgentStateEnum.PAUSED, checkpoint="paused_in_loop")
                    while True:
                        await asyncio.sleep(2)
                        st = await get_current_state()
                        if st.state == AgentStateEnum.RUNNING:
                            break
                        if st.state in (AgentStateEnum.STOPPED, AgentStateEnum.STOP_REQUESTED):
                            return

                # 2. Check Daily Limit
                async with AsyncSessionLocal() as db:
                    can_proceed = await self.check_daily_limit(db)
                    if not can_proceed:
                        logger.info("Daily limit reached. Pausing orchestrator loop.")
                        try:
                            from backend.services.webhook import dispatch_webhook_event
                            await dispatch_webhook_event("DAILY_LIMIT_REACHED", {
                                "max_limit": getattr(settings, "max_applications_per_day", 25)
                            })
                        except Exception:
                            pass
                        await transition_state(AgentStateEnum.PAUSED, checkpoint="daily_limit_reached")
                        await asyncio.sleep(60)
                        continue

                    # 3. Get next job
                    job = await self.get_next_job(db)
                    if not job:
                        # Queue empty — idle briefly
                        await asyncio.sleep(3)
                        continue

                    # 4. Process the job
                    result = await self.process_job(job, db)
                    logger.info("Job #%d processing finished: %s", job.id, result)

                # 5. Rate limiting throttle pause between applications (10–25s)
                throttle_sec = getattr(settings, "throttle_seconds", 12)
                await asyncio.sleep(throttle_sec)

        except asyncio.CancelledError:
            logger.warning("Orchestrator loop cancelled.")
        except Exception as e:
            logger.error("Error in orchestrator loop: %s", e, exc_info=True)
            try:
                await transition_state(AgentStateEnum.ERROR, error_message=str(e))
            except Exception:
                pass
        finally:
            await self.browser_session.close()
            logger.info("Orchestrator loop terminated and browser session closed.")
