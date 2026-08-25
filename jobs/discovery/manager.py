"""
jobs/discovery/manager.py
Discovery Manager & Queue Sync Engine.

Aggregates all enabled discovery sources:
- GitHub Markdown Feeds (Pitt CSC / SimplifyJobs Internships & New Grad)
- Greenhouse Public Boards
- Lever Public Boards
- Manual URL submissions

Deduplicates discovered jobs against existing Applications and JobQueue records,
assigns processing priorities, and bulk-inserts into JobQueue.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import AsyncSessionLocal
from database.models import JobQueue, Application
from jobs.discovery.base import DiscoverySource, DiscoveredJob
from jobs.discovery.github_feed import GitHubFeedScraper
from jobs.discovery.greenhouse_board import GreenhouseBoardScraper
from jobs.discovery.lever_board import LeverBoardScraper
from jobs.discovery.jobright import JobrightDiscovery
from jobs.discovery.linkedin import LinkedInDiscovery
from jobs.discovery.indeed import IndeedDiscovery
from jobs.dedupe import normalize_url

logger = logging.getLogger(__name__)


class DiscoveryManager:
    """Manages multi-source job discovery, deduplication, and queue synchronization."""

    def __init__(self, sources: Optional[List[DiscoverySource]] = None):
        self.sources = sources or [
            GreenhouseBoardScraper(),
            LeverBoardScraper(),
            GitHubFeedScraper(),
            JobrightDiscovery(),
            LinkedInDiscovery(),
            IndeedDiscovery(),
        ]
        self.last_sync_time: Optional[datetime] = None
        self.last_sync_count: int = 0

    async def sync_all_sources(self) -> Dict[str, Any]:
        """
        Runs discovery across all sources and enqueues new unique jobs.
        Returns summary statistics of the sync.
        """
        logger.info("Starting multi-source job discovery sync...")
        start_time = datetime.now(timezone.utc)

        # 1. Run all scrapers concurrently
        tasks = [source.discover() for source in self.sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_discovered: List[DiscoveredJob] = []
        for i, res in enumerate(results):
            source_name = self.sources[i].__class__.__name__
            if isinstance(res, Exception):
                logger.error("Discovery error in %s: %s", source_name, res)
            elif isinstance(res, list):
                logger.info("%s yielded %d candidates", source_name, len(res))
                all_discovered.extend(res)

        # 2. Deduplicate and enqueue in database
        async with AsyncSessionLocal() as db:
            enqueued_count = await self._enqueue_unique_jobs(all_discovered, db)

        self.last_sync_time = datetime.now(timezone.utc)
        self.last_sync_count = enqueued_count
        duration_sec = (self.last_sync_time - start_time).total_seconds()

        logger.info(
            "Discovery sync complete in %0.1fs. Candidates: %d, Enqueued new: %d",
            duration_sec, len(all_discovered), enqueued_count
        )

        return {
            "success": True,
            "candidates_found": len(all_discovered),
            "new_jobs_enqueued": enqueued_count,
            "duration_seconds": round(duration_sec, 2),
            "timestamp": self.last_sync_time.isoformat(),
        }

    async def _enqueue_unique_jobs(self, jobs: List[DiscoveredJob], db: AsyncSession) -> int:
        """Filters out already known URLs and inserts new records into JobQueue."""
        if not jobs:
            return 0

        # Gather existing URLs from JobQueue and Applications
        existing_q_urls = set(
            (await db.execute(select(JobQueue.job_url))).scalars().all()
        )
        existing_app_urls = set(
            (await db.execute(select(Application.job_url))).scalars().all()
        )
        existing_canonical_urls = set(
            (await db.execute(select(Application.canonical_job_url))).scalars().all()
        )

        seen_in_batch = set()
        new_queue_items = []

        for j in jobs:
            norm_url = normalize_url(j.url)
            if not norm_url or norm_url in seen_in_batch:
                continue
            if norm_url in existing_q_urls or norm_url in existing_app_urls or norm_url in existing_canonical_urls:
                continue
            if j.url in existing_q_urls or j.url in existing_app_urls:
                continue

            seen_in_batch.add(norm_url)

            # Assign priority based on source & keywords
            priority = 5  # default medium priority
            title_lower = (j.job_title or "").lower()
            if "intern" in title_lower or "internship" in title_lower or "summer" in title_lower:
                priority = 2  # Higher priority for internships
            if j.source.startswith("greenhouse:") or j.source.startswith("lever:"):
                priority = min(priority, 3)  # Verified direct ATS board links

            item = JobQueue(
                job_url=norm_url,
                company=j.company,
                job_title=j.job_title,
                source=j.source,
                priority=priority,
                queued_at=datetime.now(timezone.utc),
                processed=False,
            )
            new_queue_items.append(item)

        if new_queue_items:
            db.add_all(new_queue_items)
            await db.commit()

        return len(new_queue_items)

    async def enqueue_manual_url(
        self,
        url: str,
        company: Optional[str] = None,
        job_title: Optional[str] = None,
        priority: int = 1,
    ) -> Dict[str, Any]:
        """Manually adds a user-specified job URL to the front of the queue."""
        clean_url = normalize_url(url)
        async with AsyncSessionLocal() as db:
            # Check if exists
            existing = (
                await db.execute(
                    select(JobQueue).where(
                        (JobQueue.job_url == clean_url) | (JobQueue.job_url == url)
                    )
                )
            ).scalar_one_or_none()

            if existing and not existing.processed:
                return {"enqueued": False, "reason": "Job is already pending in queue", "id": existing.id}

            item = JobQueue(
                job_url=clean_url,
                company=company,
                job_title=job_title,
                source="manual_entry",
                priority=priority,
                queued_at=datetime.now(timezone.utc),
                processed=False,
            )
            db.add(item)
            await db.commit()
            return {"enqueued": True, "id": item.id, "url": clean_url}


# Global discovery manager singleton
discovery_manager = DiscoveryManager()
