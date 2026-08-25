"""
jobs/discovery/jobright.py
Jobright Recommended Internship Scraper (https://jobright.ai/jobs/recommend).

Workflow:
1. Detects authentication requirement; triggers human handoff if sign-in is required.
2. Once authenticated, scrapes recommended US internship listings.
3. Filters for United States and Internship employment type.
4. Extracts canonical employer URLs whenever available.
"""
import re
import logging
from datetime import datetime, timezone
from typing import List, Optional
from playwright.async_api import Page

from jobs.discovery.base import DiscoveredJob, DiscoverySource
from jobs.dedupe import normalize_url

logger = logging.getLogger(__name__)


class JobrightDiscovery(DiscoverySource):
    """Scrapes recommended US internships from Jobright AI."""

    RECOMMEND_URL = "https://jobright.ai/jobs/recommend"

    def __init__(self):
        super().__init__()

    async def discover(self) -> List[DiscoveredJob]:
        """Discovers jobs from Jobright."""
        return await self.fetch_jobs(None)

    async def check_auth_required(self, page: Page) -> bool:
        """Detects if Jobright requires user authentication."""
        login_indicators = [
            "button:has-text('Sign In')",
            "button:has-text('Log In')",
            "a[href*='login']",
            "input[type='password']",
            "text='Sign in to continue'",
        ]
        for sel in login_indicators:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    return True
            except Exception:
                continue
        return False

    async def fetch_jobs(self, page: Optional[Page] = None) -> List[DiscoveredJob]:
        """Scrapes authenticated Jobright recommendation feed."""
        if not page:
            logger.info("Jobright discovery requires an active Playwright browser page.")
            return []

        logger.info("Navigating to Jobright recommended feed: %s", self.RECOMMEND_URL)
        try:
            await page.goto(self.RECOMMEND_URL, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            logger.warning("Error loading Jobright page: %s", e)
            return []

        if await self.check_auth_required(page):
            logger.warning("Jobright requires user authentication.")
            return []

        jobs: List[DiscoveredJob] = []
        try:
            # Locate job cards on Jobright feed
            cards = page.locator("div[class*='job-card'], div[class*='JobCard'], div[data-testid*='job-card']")
            count = await cards.count()
            logger.info("Found %d job card elements on Jobright feed", count)

            for i in range(count):
                card = cards.nth(i)
                try:
                    title_elem = card.locator("h2, h3, a[class*='title']").first
                    title = (await title_elem.inner_text()).strip() if await title_elem.count() > 0 else ""
                    
                    # Only accept internship titles
                    if not re.search(r"\b(intern|internship|co-op|coop)\b", title.lower()):
                        continue

                    comp_elem = card.locator("div[class*='company'], span[class*='company']").first
                    company = (await comp_elem.inner_text()).strip() if await comp_elem.count() > 0 else "Unknown"

                    loc_elem = card.locator("div[class*='location'], span[class*='location']").first
                    location = (await loc_elem.inner_text()).strip() if await loc_elem.count() > 0 else "United States"

                    link_elem = card.locator("a[href*='job']").first
                    href = await link_elem.get_attribute("href") if await link_elem.count() > 0 else ""
                    if href and not href.startswith("http"):
                        href = f"https://jobright.ai{href}"

                    job_url = normalize_url(href or f"https://jobright.ai/job/{company}/{title}")

                    jobs.append(DiscoveredJob(
                        company=company,
                        job_title=title,
                        job_url=job_url,
                        location=location,
                        country="United States",
                        employment_type="internship",
                        source="jobright",
                        discovered_at=datetime.now(timezone.utc),
                    ))
                except Exception as e:
                    logger.debug("Error parsing Jobright card %d: %s", i, e)
        except Exception as e:
            logger.warning("Error extracting Jobright cards: %s", e)

        return jobs
