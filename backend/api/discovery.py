"""
backend/api/discovery.py
API endpoints for job discovery, feed sync, and JobQueue management.
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select, desc, func
from datetime import datetime, timezone

from database.connection import db_session
from database.models import JobQueue
from jobs.discovery.manager import discovery_manager

router = APIRouter()


class ManualEnqueueRequest(BaseModel):
    url: str
    company: Optional[str] = None
    job_title: Optional[str] = None
    priority: Optional[int] = 1


@router.post("/sync")
async def trigger_discovery_sync(background_tasks: BackgroundTasks):
    """
    Triggers an asynchronous multi-source job discovery sync.
    Scrapes GitHub feeds, Greenhouse boards, and Lever boards into JobQueue.
    """
    background_tasks.add_task(discovery_manager.sync_all_sources)
    return {
        "ok": True,
        "message": "Discovery sync started in background.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/status")
async def get_discovery_status():
    """Returns discovery sync status, source breakdown, and queue size."""
    async with db_session() as session:
        pending_count = (
            await session.execute(
                select(func.count()).where(JobQueue.processed == False)
            )
        ).scalar_one()
        processed_count = (
            await session.execute(
                select(func.count()).where(JobQueue.processed == True)
            )
        ).scalar_one()

    return {
        "pending_queue_count": pending_count,
        "processed_queue_count": processed_count,
        "last_sync_time": discovery_manager.last_sync_time.isoformat() if discovery_manager.last_sync_time else None,
        "last_sync_enqueued_count": discovery_manager.last_sync_count,
        "sources_enabled": [s.__class__.__name__ for s in discovery_manager.sources],
    }


@router.get("/queue")
async def list_job_queue(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    processed: Optional[bool] = Query(False),
):
    """Lists jobs in the discovery queue with pagination."""
    async with db_session() as session:
        base_query = select(JobQueue)
        if processed is not None:
            base_query = base_query.where(JobQueue.processed == processed)

        total = (
            await session.execute(
                select(func.count()).select_from(base_query.subquery())
            )
        ).scalar_one()

        items = (
            await session.execute(
                base_query.order_by(JobQueue.priority.asc(), JobQueue.queued_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "id": item.id,
                    "url": item.job_url,
                    "company": item.company or "Unknown",
                    "job_title": item.job_title or "Software Engineer",
                    "source": item.source,
                    "priority": item.priority,
                    "queued_at": item.queued_at.isoformat() if item.queued_at else None,
                    "processed": item.processed,
                    "processed_at": item.processed_at.isoformat() if item.processed_at else None,
                    "application_id": item.application_id,
                }
                for item in items
            ],
        }


@router.post("/queue/add")
async def add_to_queue(request: ManualEnqueueRequest):
    """Manually adds a job posting URL into the processing queue."""
    if not request.url or not request.url.strip():
        raise HTTPException(status_code=400, detail="Job URL is required")

    result = await discovery_manager.enqueue_manual_url(
        url=request.url.strip(),
        company=request.company,
        job_title=request.job_title,
        priority=request.priority or 1,
    )
    return result


@router.delete("/queue/{item_id}")
async def delete_queue_item(item_id: int):
    """Deletes an item from the job queue."""
    async with db_session() as session:
        item = await session.get(JobQueue, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Queue item not found")
        await session.delete(item)
        await session.commit()
        return {"ok": True, "deleted_id": item_id}
