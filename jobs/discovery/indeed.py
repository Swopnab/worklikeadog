"""
jobs/discovery/indeed.py
Indeed Jobs US Internship Discovery.

Follows human-in-the-loop security rules:
- Respects Cloudflare challenges & login barriers with human handoff.
- Scrapes US Software Engineer / Tech internship results.
"""
import re
import logging
from datetime import datetime, timezone
from typing import List, Optional
from playwright.async_api import Page

from jobs.discovery.base import DiscoveredJob, DiscoverySource
from jobs.dedupe import normalize_url

logger = logging.getLogger(__name__)


class IndeedDiscovery(DiscoverySource):
    """Scrapes US internships from Indeed."""

    SEARCH_URL = "https://www.indeed.com/jobs?q=software+engineer+intern&l=United+States&sc=0kf%3Ajt%28internship%29%3B"

    def __init__(self):
        super().__init__()

    async def discover(self) -> List[DiscoveredJob]:
        """Discovers jobs from Indeed."""
        return await self.fetch_jobs(None)

    async def check_auth_required(self, page: Page) -> bool:
        """Detects if Indeed requires login or presents Cloudflare challenge."""
        indicators = [
            "iframe[src*='cloudflare']",
            "div#challenge-running",
            "a[href*='account/login']",
            "input[type='password']",
            "text='Verify you are human'",
        ]
        for sel in indicators:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    return True
            except Exception:
                continue
        return False

    async def fetch_jobs(self, page: Optional[Page] = None) -> List[DiscoveredJob]:
        """Scrapes Indeed internship search results."""
        if not page:
            logger.info("Indeed discovery requires a Playwright page.")
            return []

        logger.info("Navigating to Indeed search: %s", self.SEARCH_URL)
        try:
            await page.goto(self.SEARCH_URL, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            logger.warning("Error loading Indeed page: %s", e)
            return []

        if await self.check_auth_required(page):
            logger.warning("Indeed requires user authentication or Cloudflare solve.")
            return []

        jobs: List[DiscoveredJob] = []
        try:
            cards = page.locator("div.job_seen_beacon, div.cardOutline")
            count = await cards.count()

            for i in range(min(count, 20)):
                card = cards.nth(i)
                try:
                    title_elem = card.locator("h2.jobTitle, a[data-jk]").first
                    title = (await title_elem.inner_text()).strip() if await title_elem.count() > 0 else ""

                    if not re.search(r"\b(intern|internship|co-op|coop)\b", title.lower()):
                        continue

                    comp_elem = card.locator("span[data-testid='company-name']").first
                    company = (await comp_elem.inner_text()).strip() if await comp_elem.count() > 0 else "Unknown"

                    loc_elem = card.locator("div[data-testid='text-location']").first
                    location = (await loc_elem.inner_text()).strip() if await loc_elem.count() > 0 else "United States"

                    link_elem = card.locator("a[data-jk]").first
                    href = await link_elem.get_attribute("href") if await link_elem.count() > 0 else ""
                    if href and not href.startswith("http"):
                        href = f"https://www.indeed.com{href}"

                    if href:
                        job_url = normalize_url(href)
                        jobs.append(DiscoveredJob(
                            company=company,
                            job_title=title,
                            job_url=job_url,
                            location=location,
                            country="United States",
                            employment_type="internship",
                            source="indeed",
                            discovered_at=datetime.now(timezone.utc),
                        ))
                except Exception as e:
                    logger.debug("Error parsing Indeed card %d: %s", i, e)
        except Exception as e:
            logger.warning("Error extracting Indeed cards: %s", e)

        return jobs
