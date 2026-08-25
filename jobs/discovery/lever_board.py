"""
jobs/discovery/lever_board.py
Scrapes public Lever job postings for target tech companies using Lever JSON API.
"""
import logging
from typing import List, Optional
import httpx

from jobs.discovery.base import DiscoverySource, DiscoveredJob
from jobs.dedupe import normalize_url
from agent.safety import is_blacklisted

logger = logging.getLogger(__name__)

TARGET_LEVER_BOARDS = [
    "netflix",
    "palantir",
    "atlassian",
    "affirm",
    "auth0",
    "box",
    "reddit",
    "spotify",
    "databricks",
]


class LeverBoardScraper(DiscoverySource):
    """Fetches job listings directly from public Lever postings APIs."""

    def __init__(self, board_tokens: Optional[List[str]] = None, timeout: int = 15):
        self.board_tokens = board_tokens or TARGET_LEVER_BOARDS
        self.timeout = timeout

    async def discover(self) -> List[DiscoveredJob]:
        """Queries all configured Lever board APIs."""
        all_jobs: List[DiscoveredJob] = []

        headers = {
            "User-Agent": "WorkLikeDog-JobDiscovery/1.0",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for token in self.board_tokens:
                api_url = f"https://api.lever.co/v0/postings/{token}?mode=json"
                try:
                    resp = await client.get(api_url, headers=headers)
                    if resp.status_code == 200:
                        postings = resp.json()
                        if isinstance(postings, list):
                            jobs = self._parse_lever_jobs(postings, company_token=token)
                            logger.info("Discovered %d relevant jobs from Lever board '%s'", len(jobs), token)
                            all_jobs.extend(jobs)
                    else:
                        logger.debug("Lever board '%s' returned status %d", token, resp.status_code)
                except Exception as e:
                    logger.debug("Failed fetching Lever board '%s': %s", token, e)

        return all_jobs

    def _parse_lever_jobs(self, postings: list, company_token: str) -> List[DiscoveredJob]:
        """Filters and maps Lever JSON job items."""
        discovered = []
        company_name = company_token.capitalize()

        for p in postings:
            title = p.get("text", "")
            url = p.get("hostedUrl", "") or p.get("applyUrl", "")
            categories = p.get("categories", {})
            location_name = categories.get("location", "United States")

            if not url or not title:
                continue

            if is_blacklisted(company_name) or is_blacklisted(title):
                continue

            title_lower = title.lower()
            relevant_keywords = [
                "software", "engineer", "intern", "backend", "full stack", "fullstack",
                "frontend", "developer", "cloud", "ai", "machine learning", "data", "infrastructure"
            ]
            if not any(kw in title_lower for kw in relevant_keywords):
                continue

            senior_keywords = ["senior", "sr.", "staff", "principal", "lead", "director", "vp", "manager"]
            if any(sk in title_lower for sk in senior_keywords):
                continue

            discovered.append(
                DiscoveredJob(
                    url=normalize_url(url),
                    company=company_name,
                    job_title=title,
                    location=location_name or "United States",
                    source=f"lever:{company_token}",
                    external_job_id=str(p.get("id", "")),
                )
            )

        return discovered
