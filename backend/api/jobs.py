"""
backend/api/jobs.py
Job processing, URL fetching, job description parsing, and evaluation endpoints.
"""
from typing import Optional
import json
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from database.connection import get_db
from database.models import Application, ApplicationStatus, JobQueue, ActivityLog, ActivityEventType
from ai.matcher import MatchCoordinator
from jobs.discovery.manual import ManualJobImporter
from jobs.dedupe import check_duplicate, normalize_url
from agent.safety import compute_content_hash

router = APIRouter()
coordinator = MatchCoordinator()


class JobAnalyzeRequest(BaseModel):
    job_description: str
    job_title: Optional[str] = ""
    company: Optional[str] = ""
    job_url: Optional[str] = ""
    location: Optional[str] = ""


class FetchUrlRequest(BaseModel):
    url: str


@router.get("/queue")
async def get_job_queue(db: AsyncSession = Depends(get_db)):
    """Get pending jobs in the queue."""
    result = await db.execute(
        select(JobQueue)
        .where(JobQueue.processed == False)
        .order_by(JobQueue.priority, JobQueue.queued_at)
        .limit(50)
    )
    jobs = result.scalars().all()
    return {
        "items": [
            {
                "id": j.id,
                "url": j.job_url,
                "company": j.company,
                "job_title": j.job_title,
                "source": j.source,
                "priority": j.priority,
                "queued_at": j.queued_at.isoformat() if j.queued_at else None,
            }
            for j in jobs
        ]
    }


@router.post("/fetch-url")
async def fetch_job_url(request: FetchUrlRequest):
    """
    Fetches web content for a job URL and extracts clean company, title, and description.
    """
    if not request.url or not request.url.strip():
        raise HTTPException(status_code=400, detail="Job URL is required.")
    
    try:
        data = await ManualJobImporter.fetch_url_content(request.url.strip())
        return data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/analyze")
async def analyze_job_description(request: JobAnalyzeRequest):
    """
    Runs full parsing, eligibility check, and deterministic 100-point scoring on a job description.
    """
    if not request.job_description or not request.job_description.strip():
        raise HTTPException(status_code=400, detail="Job description text is required.")

    try:
        result = await coordinator.evaluate_job(
            job_description=request.job_description,
            job_title=request.job_title or "",
            company=request.company or "",
            job_url=request.job_url or "",
            location=request.location or "",
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.post("/save-application")
async def save_evaluated_application(
    request: JobAnalyzeRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Evaluates and saves a job directly to the applications table.
    Checks for duplicates first.
    """
    if not request.job_description or not request.job_description.strip():
        raise HTTPException(status_code=400, detail="Job description is required.")

    # 1. Run evaluation
    eval_result = await coordinator.evaluate_job(
        job_description=request.job_description,
        job_title=request.job_title or "",
        company=request.company or "",
        job_url=request.job_url or "",
        location=request.location or "",
    )

    company = eval_result["company"]
    job_title = eval_result["job_title"]
    job_url = request.job_url or f"manual://{company.lower().replace(' ', '')}"
    canonical_url = normalize_url(job_url)

    # 2. Check for duplicate
    is_dup, existing, dup_reason = await check_duplicate(
        session=db,
        company=company,
        job_title=job_title,
        job_url=job_url,
        job_description=request.job_description,
    )

    if is_dup and existing:
        return {
            "duplicate": True,
            "message": f"Duplicate posting detected: {dup_reason}",
            "existing_id": existing.id,
            "status": existing.status.value,
            "evaluation": eval_result,
        }

    # 3. Determine status
    eligibility_passed = eval_result["eligibility"]["passed"]
    match_score = eval_result["match_score"]
    decision = eval_result["decision"]

    if not eligibility_passed:
        status = ApplicationStatus.INELIGIBLE
    elif decision == "skip":
        status = ApplicationStatus.SKIPPED
    else:
        status = ApplicationStatus.ANALYZED

    desc_hash = compute_content_hash(request.job_description)

    # 4. Create application
    app = Application(
        company=company,
        job_title=job_title,
        job_url=job_url,
        canonical_job_url=canonical_url,
        source="manual",
        location=eval_result.get("location"),
        job_description=request.job_description,
        job_description_hash=desc_hash,
        eligibility_status="passed" if eligibility_passed else "failed",
        eligibility_reason=eval_result["eligibility"]["reason"],
        match_score=match_score,
        match_details=json.dumps(eval_result["score_breakdown"]),
        decision=decision,
        status=status,
        resume_projects=json.dumps(eval_result["selected_projects"]),
        resume_skills=json.dumps(eval_result["skills"]["matched_required"]),
    )
    db.add(app)
    await db.flush()

    # Log the discovery & analysis
    log1 = ActivityLog(
        application_id=app.id,
        event_type=ActivityEventType.DISCOVERED.value,
        description=f"Discovered {company} — {job_title}",
    )
    log2 = ActivityLog(
        application_id=app.id,
        event_type=ActivityEventType.ELIGIBILITY_PASSED.value if eligibility_passed else ActivityEventType.ELIGIBILITY_FAILED.value,
        description=f"Eligibility: {eval_result['eligibility']['reason']}",
    )
    log3 = ActivityLog(
        application_id=app.id,
        event_type=ActivityEventType.MATCH_SCORE.value,
        description=f"Calculated Match Score: {match_score}%",
        details=json.dumps(eval_result["score_breakdown"]),
    )
    db.add_all([log1, log2, log3])
    await db.flush()

    return {
        "duplicate": False,
        "application_id": app.id,
        "company": app.company,
        "job_title": app.job_title,
        "status": app.status.value,
        "match_score": app.match_score,
        "evaluation": eval_result,
    }
