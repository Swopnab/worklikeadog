"""
jobs/discovery/greenhouse_board.py
Scrapes public Greenhouse job boards for target tech companies using official Greenhouse API.
"""
import logging
from typing import List, Optional
import httpx

from jobs.discovery.base import DiscoverySource, DiscoveredJob
from jobs.dedupe import normalize_url
from agent.safety import is_blacklisted

logger = logging.getLogger(__name__)

# Curated list of target company Greenhouse board tokens
TARGET_GREENHOUSE_BOARDS = [
    "stripe",
    "figma",
    "datadog",
    "cloudflare",
    "scaleai",
    "vercel",
    "supabase",
    "anthropic",
    "openai",
    "postman",
    "hashicorp",
    "robinhood",
    "pinterest",
]


class GreenhouseBoardScraper(DiscoverySource):
    """Fetches job listings directly from public Greenhouse board APIs."""

    def __init__(self, board_tokens: Optional[List[str]] = None, timeout: int = 15):
        self.board_tokens = board_tokens or TARGET_GREENHOUSE_BOARDS
        self.timeout = timeout

    async def discover(self) -> List[DiscoveredJob]:
        """Queries all configured Greenhouse board APIs."""
        all_jobs: List[DiscoveredJob] = []

        headers = {
            "User-Agent": "WorkLikeDog-JobDiscovery/1.0",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for token in self.board_tokens:
                api_url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
                try:
                    resp = await client.get(api_url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        jobs = self._parse_greenhouse_jobs(data, company_token=token)
                        logger.info("Discovered %d relevant jobs from Greenhouse board '%s'", len(jobs), token)
                        all_jobs.extend(jobs)
                    else:
                        logger.debug("Greenhouse board '%s' returned status %d", token, resp.status_code)
                except Exception as e:
                    logger.debug("Failed fetching Greenhouse board '%s': %s", token, e)

        return all_jobs

    def _parse_greenhouse_jobs(self, data: dict, company_token: str) -> List[DiscoveredJob]:
        """Filters and maps Greenhouse JSON job items."""
        discovered = []
        raw_jobs = data.get("jobs", [])
        company_name = company_token.capitalize()

        for j in raw_jobs:
            title = j.get("title", "")
            url = j.get("absolute_url", "")
            location_obj = j.get("location", {})
            location_name = location_obj.get("name", "United States") if isinstance(location_obj, dict) else str(location_obj)

            if not url or not title:
                continue

            # Check blacklist
            if is_blacklisted(company_name) or is_blacklisted(title):
                continue

            # Focus on Software / Backend / Cloud / AI / Intern / New Grad roles
            title_lower = title.lower()
            relevant_keywords = [
                "software", "engineer", "intern", "backend", "full stack", "fullstack",
                "frontend", "developer", "cloud", "ai", "machine learning", "data", "infrastructure"
            ]
            if not any(kw in title_lower for kw in relevant_keywords):
                continue

            # Skip senior/staff/director/executive roles
            senior_keywords = ["senior", "sr.", "staff", "principal", "lead", "director", "vp", "manager"]
            if any(sk in title_lower for sk in senior_keywords):
                continue

            discovered.append(
                DiscoveredJob(
                    url=normalize_url(url),
                    company=company_name,
                    job_title=title,
                    location=location_name or "United States",
                    source=f"greenhouse:{company_token}",
                    external_job_id=str(j.get("id", "")),
                )
            )

        return discovered
