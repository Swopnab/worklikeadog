"""
tests/test_phase7.py
Automated test suite for Phase 7:
- GitHub feed markdown table parser (PittCSC / Simplify format)
- Greenhouse and Lever board scrapers & filters
- DiscoveryManager deduplication, priority mapping, and database queue sync
- Manual URL enqueuing and queue management APIs
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from database.connection import AsyncSessionLocal
from database.models import JobQueue, Application
from jobs.discovery.github_feed import GitHubFeedScraper
from jobs.discovery.greenhouse_board import GreenhouseBoardScraper
from jobs.discovery.lever_board import LeverBoardScraper
from jobs.discovery.manager import DiscoveryManager
from jobs.discovery.base import DiscoveredJob


def test_github_feed_markdown_parsing():
    """Verify markdown table parsing from curated GitHub repos."""
    sample_markdown = """
# Summer 2025 Internships

| Company | Role | Location | Application/Link | Date Posted |
| :--- | :--- | :--- | :--- | :--- |
| **[Stripe](https://stripe.com)** | Software Engineering Intern | San Francisco, CA | [Apply](https://boards.greenhouse.io/stripe/jobs/101) | Jul 15 |
| **[Figma](https://figma.com)** | Backend Intern | New York, NY | [Apply](https://jobs.lever.co/figma/202) | Jul 16 |
| **[London AI](https://london.ai)** | AI Intern | London, UK | [Apply](https://example.com/uk) | Jul 17 |
| **[Rock-Paper-Scissor Lab](https://rps.com)** | Intern | Remote | [Apply](https://rps.com/apply) | Jul 18 |
"""
    scraper = GitHubFeedScraper()
    jobs = scraper.parse_markdown_table(sample_markdown)

    assert len(jobs) >= 2
    # Check Stripe job parsed
    stripe_job = next((j for j in jobs if "Stripe" in j.company), None)
    assert stripe_job is not None
    assert "stripe" in stripe_job.url
    assert "San Francisco" in stripe_job.location

    # Check that international only (London, UK) was filtered out
    assert not any("London AI" in j.company for j in jobs)

    # Check that blacklisted (Rock-Paper-Scissor) was strictly filtered out
    assert not any("Rock-Paper-Scissor" in j.company for j in jobs)


def test_greenhouse_board_parsing():
    """Verify Greenhouse JSON board parsing."""
    sample_data = {
        "jobs": [
            {
                "id": 12345,
                "title": "Software Engineer Intern - Summer 2026",
                "absolute_url": "https://boards.greenhouse.io/stripe/jobs/12345",
                "location": {"name": "San Francisco, CA"},
            },
            {
                "id": 67890,
                "title": "Senior Director of Engineering",
                "absolute_url": "https://boards.greenhouse.io/stripe/jobs/67890",
                "location": {"name": "Seattle, WA"},
            },
        ]
    }
    scraper = GreenhouseBoardScraper()
    jobs = scraper._parse_greenhouse_jobs(sample_data, "stripe")

    # Should keep the intern role and filter out the Senior Director role
    assert len(jobs) == 1
    assert jobs[0].company == "Stripe"
    assert "Intern" in jobs[0].job_title
    assert jobs[0].external_job_id == "12345"


def test_lever_board_parsing():
    """Verify Lever JSON board parsing."""
    sample_postings = [
        {
            "id": "lever-111",
            "text": "Junior Cloud Infrastructure Engineer",
            "hostedUrl": "https://jobs.lever.co/palantir/lever-111",
            "categories": {"location": "Austin, TX"},
        },
        {
            "id": "lever-222",
            "text": "Vice President of Sales",
            "hostedUrl": "https://jobs.lever.co/palantir/lever-222",
            "categories": {"location": "Remote"},
        },
    ]
    scraper = LeverBoardScraper()
    jobs = scraper._parse_lever_jobs(sample_postings, "palantir")

    # Should keep the engineer role and filter out the VP role
    assert len(jobs) == 1
    assert jobs[0].company == "Palantir"
    assert "Infrastructure" in jobs[0].job_title


@pytest.mark.asyncio
async def test_discovery_manager_dedupe_and_enqueue():
    """Verify DiscoveryManager deduplicates against existing applications and assigns priority."""
    mgr = DiscoveryManager(sources=[])
    run_id = int(datetime.now(timezone.utc).timestamp() * 1000)

    discovered = [
        DiscoveredJob(
            url=f"https://boards.greenhouse.io/datadog/jobs/99001_{run_id}",
            company="Datadog",
            job_title="Software Engineering Intern",
            location="New York, NY",
            source="greenhouse:datadog",
        ),
        DiscoveredJob(
            url=f"https://jobs.lever.co/affirm/99002_{run_id}",
            company="Affirm",
            job_title="Backend Developer",
            location="Remote",
            source="lever:affirm",
        ),
    ]

    async with AsyncSessionLocal() as session:
        # Enqueue discovered jobs
        enqueued_count = await mgr._enqueue_unique_jobs(discovered, session)
        assert enqueued_count == 2

        # Re-enqueuing the same batch should return 0 new jobs (deduplication)
        duplicate_count = await mgr._enqueue_unique_jobs(discovered, session)
        assert duplicate_count == 0

        # Verify Datadog was assigned high priority (2) because of 'Intern' keyword
        q_item = (
            await session.execute(
                select(JobQueue).where(JobQueue.job_url == f"https://boards.greenhouse.io/datadog/jobs/99001_{run_id}")
            )
        ).scalar_one_or_none()
        assert q_item is not None
        assert q_item.priority == 2


@pytest.mark.asyncio
async def test_manual_enqueue_url():
    """Verify manual URL enqueuing."""
    mgr = DiscoveryManager(sources=[])
    run_id = int(datetime.now(timezone.utc).timestamp() * 1000)
    res = await mgr.enqueue_manual_url(
        url=f"https://boards.greenhouse.io/cloudflare/jobs/manual-test-{run_id}",
        company="Cloudflare",
        job_title="Systems Engineer Intern",
        priority=1,
    )
    assert res["enqueued"] is True
    assert "id" in res
