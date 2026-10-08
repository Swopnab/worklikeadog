"""
backend/api/applications.py
Application CRUD, activity log, artifact management, analytics, and history endpoints.
"""
import json
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from database.connection import get_db
from database.models import Application, ApplicationStatus, ActivityLog, JobQueue
from backend.services.artifact_store import ArtifactStore, get_artifact_dir
from backend.services.analytics import compute_analytics

router = APIRouter()


# ============================================================
# LIST & FILTER
# ============================================================

@router.get("/")
async def list_applications(
    status: Optional[str] = None,
    company: Optional[str] = None,
    min_score: Optional[float] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List applications with filtering, search, and pagination."""
    query = select(Application).order_by(desc(Application.discovered_at))

    if status:
        try:
            status_enum = ApplicationStatus(status)
            query = query.where(Application.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    if company:
        query = query.where(Application.company.ilike(f"%{company}%"))
    if min_score is not None:
        query = query.where(Application.match_score >= min_score)
    if source:
        query = query.where(Application.source == source)
    if search:
        query = query.where(
            Application.company.ilike(f"%{search}%") |
            Application.job_title.ilike(f"%{search}%") |
            Application.location.ilike(f"%{search}%")
        )

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    apps = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialize_app(a) for a in apps],
    }


# ============================================================
# STATS
# ============================================================

@router.get("/stats")
async def get_application_stats(db: AsyncSession = Depends(get_db)):
    """Dashboard statistics — counts by every status + today's submitted."""
    from datetime import datetime, timezone
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    stats = {}
    for status in ApplicationStatus:
        result = await db.execute(
            select(func.count()).where(Application.status == status)
        )
        stats[status.value] = result.scalar_one()

    today_submitted = await db.execute(
        select(func.count()).where(
            Application.status == ApplicationStatus.SUBMITTED,
            Application.application_submitted_at >= today_start,
        )
    )
    stats["submitted_today"] = today_submitted.scalar_one()
    stats["total"] = sum(v for k, v in stats.items() if k != "submitted_today")
    return stats


# ============================================================
# ANALYTICS
# ============================================================

@router.get("/analytics")
async def get_analytics(db: AsyncSession = Depends(get_db)):
    """Full analytics report: skill frequency, score distributions, timeline, company breakdowns."""
    return await compute_analytics(db)


# ============================================================
# SINGLE APPLICATION DETAIL
# ============================================================

@router.get("/{app_id}")
async def get_application(app_id: int, db: AsyncSession = Depends(get_db)):
    """Get full application detail including activity log and artifact manifest."""
    result = await db.execute(select(Application).where(Application.id == app_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    log_result = await db.execute(
        select(ActivityLog)
        .where(ActivityLog.application_id == app_id)
        .order_by(ActivityLog.created_at)
    )
    logs = log_result.scalars().all()

    # List local artifacts if available
    artifacts = {}
    try:
        artifact_info = ArtifactStore.list_artifacts(app_id, app.company, app.job_title)
        artifacts = artifact_info
    except Exception:
        pass

    # Parse match_details
    score_breakdown = {}
    if app.match_details:
        try:
            score_breakdown = json.loads(app.match_details)
        except Exception:
            pass

    selected_projects = []
    if app.resume_projects:
        try:
            selected_projects = json.loads(app.resume_projects)
        except Exception:
            pass

    matched_skills = []
    if app.resume_skills:
        try:
            matched_skills = json.loads(app.resume_skills)
        except Exception:
            pass

    return {
        **_serialize_app_full(app),
        "score_breakdown": score_breakdown,
        "selected_projects": selected_projects,
        "matched_skills": matched_skills,
        "activity_log": [_serialize_log(l) for l in logs],
        "artifacts": artifacts,
    }


# ============================================================
# ARTIFACT READING
# ============================================================

@router.get("/{app_id}/artifact")
async def get_artifact_content(
    app_id: int,
    file: str = Query(..., description="Artifact filename, e.g. 'analysis.json'"),
    db: AsyncSession = Depends(get_db),
):
    """Read a local artifact file for an application."""
    result = await db.execute(select(Application).where(Application.id == app_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    # Allowlist of safe artifact names
    allowed_files = {
        "job.json", "job-description.txt", "analysis.json",
        "resume.tex", "answers.json", "activity.log"
    }
    if file not in allowed_files:
        raise HTTPException(status_code=400, detail=f"Unsupported artifact file: {file}")

    dir_path = get_artifact_dir(app_id, app.company, app.job_title)
    artifact_path = dir_path / file

    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {file}")

    content = artifact_path.read_text(encoding="utf-8")
    media_type = "application/json" if file.endswith(".json") else "text/plain"
    return PlainTextResponse(content, media_type=media_type)


# ============================================================
# STATUS UPDATE & NOTES
# ============================================================

@router.patch("/{app_id}/status")
async def update_application_status(
    app_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Manually update application status (e.g., mark as submitted, withdrawn)."""
    result = await db.execute(select(Application).where(Application.id == app_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    new_status = body.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="status required")
    try:
        app.status = ApplicationStatus(new_status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {new_status}")

    if body.get("notes"):
        app.notes = body["notes"]

    from datetime import datetime, timezone
    if new_status == "submitted" and not app.application_submitted_at:
        app.application_submitted_at = datetime.now(timezone.utc)

    # Archive activity log update
    try:
        ArtifactStore.append_activity_log(
            app_id, app.company, app.job_title,
            [{"event_type": "STATUS_UPDATE", "description": f"Status manually updated to {new_status}"}]
        )
    except Exception:
        pass

    return {"ok": True, "id": app.id, "status": app.status.value}


@router.patch("/{app_id}/notes")
async def update_application_notes(
    app_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Update free-text notes for an application."""
    result = await db.execute(select(Application).where(Application.id == app_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    app.notes = body.get("notes", "")
    return {"ok": True}


# ============================================================
# HUMAN-IN-THE-LOOP SCREENSHOTS & ACTIONS
# ============================================================

from fastapi.responses import FileResponse

@router.get("/{app_id}/screenshot")
async def get_application_screenshot(
    app_id: int,
    name: str = Query("presubmit_review.png"),
    db: AsyncSession = Depends(get_db),
):
    """Serves captured application screenshot (presubmit_review.png, challenge.png, etc.)."""
    result = await db.execute(select(Application).where(Application.id == app_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    artifact_dir = get_artifact_dir(app_id, app.company, app.job_title)
    safe_filename = Path(name).name
    file_path = artifact_dir / safe_filename

    if not file_path.exists():
        # Fallback to any .png in the artifact dir
        pngs = list(artifact_dir.glob("*.png"))
        if pngs:
            file_path = pngs[0]
        else:
            raise HTTPException(status_code=404, detail=f"Screenshot '{name}' not found for application {app_id}")

    return FileResponse(str(file_path), media_type="image/png")


@router.post("/{app_id}/decision")
async def handle_application_decision(
    app_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Human-in-the-loop decision handler for paused or needs-review applications:
    - 'approve_and_submit': sets status to SUBMITTED
    - 'reject_and_skip': sets status to SKIPPED
    - 'mark_ready': sets status to READY for manual filling
    """
    action = body.get("action")
    result = await db.execute(select(Application).where(Application.id == app_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    from datetime import datetime, timezone
    if action == "approve_and_submit":
        app.status = ApplicationStatus.SUBMITTED
        app.application_submitted_at = datetime.now(timezone.utc)
        app.submission_confirmation = "Approved and submitted by user."
    elif action in ("mark_submitted", "approve_and_submit"):
        app.status = ApplicationStatus.SUBMITTED
        app.application_submitted_at = datetime.now(timezone.utc)
        app.submission_confirmation = body.get("confirmation", "Submitted manually by user")
        app.pause_reason = None
        desc = "Application confirmed as submitted by user"
    elif action == "reject_and_skip":
        app.status = ApplicationStatus.SKIPPED
        app.pause_reason = body.get("reason", "Skipped by user")
        desc = f"Application skipped by user: {app.pause_reason}"
    elif action == "mark_ready":
        app.status = ApplicationStatus.READY_FOR_REVIEW
        app.pause_reason = None
        desc = "Application marked ready for user review"
    else:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    try:
        ArtifactStore.append_activity_log(
            app_id, app.company, app.job_title,
            [{"event_type": "USER_CONFIRMED_SUBMITTED" if app.status == ApplicationStatus.SUBMITTED else "HUMAN_DECISION", "description": desc}]
        )
        ArtifactStore.save_application_state(
            app_id=app_id,
            company=app.company,
            job_title=app.job_title,
            status=app.status.value,
            submitted_at=app.application_submitted_at.isoformat() if app.application_submitted_at else None,
            submission_confirmation=app.submission_confirmation,
        )
    except Exception:
        pass

    await db.commit()
    return {"ok": True, "id": app.id, "status": app.status.value, "action": action}


@router.post("/{app_id}/confirm-submission")
async def confirm_manual_submission(app_id: int, body: dict = None, db: AsyncSession = Depends(get_db)):
    """User confirms they have manually submitted the application on the employer portal."""
    app = await db.get(Application, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    body = body or {}
    now = datetime.now(timezone.utc)
    app.status = ApplicationStatus.SUBMITTED
    app.application_submitted_at = now
    app.submission_confirmation = body.get("confirmation", "User manually submitted on employer site")
    app.pause_reason = None

    try:
        ArtifactStore.append_activity_log(
            app_id, app.company, app.job_title,
            [{"event_type": "USER_CONFIRMED_SUBMITTED", "description": f"User confirmed submission: {app.submission_confirmation}"}]
        )
        ArtifactStore.save_application_state(
            app_id=app_id,
            company=app.company,
            job_title=app.job_title,
            status=app.status.value,
            submitted_at=now.isoformat(),
            submission_confirmation=app.submission_confirmation,
        )
    except Exception as e:
        logger.warning("Error saving artifact state on confirm: %s", e)

    log_entry = ActivityLog(
        application_id=app.id,
        event_type="USER_CONFIRMED_SUBMITTED",
        description="User manually confirmed application submission on employer site",
    )
    db.add(log_entry)
    await db.commit()
    return {"ok": True, "id": app.id, "status": app.status.value, "submitted_at": now.isoformat()}


@router.get("/{app_id}/resume/preview")
async def preview_tailored_resume(app_id: int, db: AsyncSession = Depends(get_db)):
    """Serves the tailored resume.pdf for browser preview and returns SHA-256 hash."""
    from fastapi.responses import FileResponse
    app = await db.get(Application, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    dir_path = get_artifact_dir(app_id, app.company, app.job_title)
    pdf_file = dir_path / "resume.pdf"
    if not pdf_file.exists():
        # Fallback to master resume
        pdf_file = Path("resume/master_resume.pdf")
        if not pdf_file.exists():
            raise HTTPException(status_code=404, detail="Resume PDF artifact not found")

    from backend.services.artifact_store import compute_sha256
    pdf_hash = compute_sha256(pdf_file)
    return FileResponse(
        str(pdf_file),
        media_type="application/pdf",
        headers={
            "X-Resume-Hash": pdf_hash or "",
            "Content-Disposition": f'inline; filename="{app.company}_Tailored_Resume.pdf"',
        }
    )


@router.get("/{app_id}/resume/latex")
async def get_tailored_latex(app_id: int, db: AsyncSession = Depends(get_db)):
    """Returns the exact tailored resume.tex content."""
    app = await db.get(Application, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    dir_path = get_artifact_dir(app_id, app.company, app.job_title)
    tex_file = dir_path / "resume.tex"
    if not tex_file.exists():
        tex_file = Path("resume/master_resume.tex")
        if not tex_file.exists():
            raise HTTPException(status_code=404, detail="LaTeX source artifact not found")

    return PlainTextResponse(tex_file.read_text(encoding="utf-8"), media_type="text/plain")


@router.post("/{app_id}/resume/recompile")
async def recompile_tailored_resume(app_id: int, db: AsyncSession = Depends(get_db)):
    """Recompiles the application's resume.tex locally and validates 1-page PDF constraints."""
    from resume.validator import ResumeCompilerValidator
    app = await db.get(Application, app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    dir_path = get_artifact_dir(app_id, app.company, app.job_title)
    tex_file = dir_path / "resume.tex"
    if not tex_file.exists():
        raise HTTPException(status_code=404, detail="resume.tex not found in application directory")

    comp_res = ResumeCompilerValidator.compile_latex(tex_file, dir_path)
    if not comp_res.get("success"):
        app.status = ApplicationStatus.RESUME_COMPILE_ERROR
        app.resume_compiler_error = comp_res.get("error")
        await db.commit()
        return {
            "success": False,
            "status": "RESUME_COMPILE_ERROR",
            "error": comp_res.get("error"),
        }

    pdf_file = Path(comp_res["pdf_path"])
    val_res = ResumeCompilerValidator.validate_pdf(pdf_file)
    if not val_res.get("valid"):
        app.status = ApplicationStatus.RESUME_COMPILE_ERROR
        app.resume_path = None
        app.resume_hash = None
        app.resume_compiler_error = val_res.get("error", "PDF did not pass validation.")
        await db.commit()
        return {"success": False, "status": app.status.value,
                "error": app.resume_compiler_error, "validation": val_res}
    app.resume_path = str(pdf_file)
    app.resume_hash = val_res.get("pdf_hash")
    app.resume_compiler_error = None
    if app.status == ApplicationStatus.RESUME_COMPILE_ERROR:
        app.status = ApplicationStatus.READY_FOR_REVIEW

    await db.commit()
    return {
        "success": True,
        "status": app.status.value,
        "pdf_path": str(pdf_file),
        "pdf_hash": app.resume_hash,
        "page_count": val_res.get("page_count", 0),
        "valid": val_res.get("valid", False),
    }


# ============================================================
# QUEUE
# ============================================================

@router.post("/queue")
async def queue_job_url(body: dict, db: AsyncSession = Depends(get_db)):
    """Manually queue a job URL for the agent to process."""
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    job = JobQueue(
        job_url=url,
        source=body.get("source", "manual"),
        company=body.get("company"),
        job_title=body.get("job_title"),
        priority=body.get("priority", 5),
    )
    db.add(job)
    await db.flush()
    return {"ok": True, "queued_id": job.id, "url": url}


# ============================================================
# SERIALIZERS
# ============================================================

def _serialize_app(a: Application) -> dict:
    return {
        "id": a.id,
        "company": a.company,
        "job_title": a.job_title,
        "job_url": a.job_url,
        "source": a.source,
        "location": a.location,
        "match_score": a.match_score,
        "status": a.status.value,
        "eligibility_status": a.eligibility_status,
        "eligibility_reason": a.eligibility_reason,
        "discovered_at": a.discovered_at.isoformat() if a.discovered_at else None,
        "application_submitted_at": a.application_submitted_at.isoformat() if a.application_submitted_at else None,
        "resume_path": a.resume_path,
        "pause_reason": a.pause_reason,
        "failure_reason": a.failure_reason,
        "notes": a.notes,
    }


def _serialize_app_full(a: Application) -> dict:
    return {
        **_serialize_app(a),
        "canonical_job_url": a.canonical_job_url,
        "external_job_id": a.external_job_id,
        "remote_type": a.remote_type,
        "decision": a.decision,
        "job_description_hash": a.job_description_hash,
        "cover_letter_path": a.cover_letter_path,
        "answers_path": a.answers_path,
        "submission_confirmation": a.submission_confirmation,
        "last_updated_at": a.last_updated_at.isoformat() if a.last_updated_at else None,
        "application_started_at": a.application_started_at.isoformat() if a.application_started_at else None,
    }


def _serialize_log(l: ActivityLog) -> dict:
    return {
        "id": l.id,
        "event_type": l.event_type,
        "description": l.description,
        "details": l.details,
        "created_at": l.created_at.isoformat() if l.created_at else None,
    }
