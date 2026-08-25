"""
jobs/discovery/linkedin.py
LinkedIn Jobs US Internship Discovery.

Follows human-in-the-loop security rules:
- Never attempts to bypass LinkedIn authentication, CAPTCHA, or rate limits.
- Detects sign-in requirement and triggers human handoff.
- Scrapes public or authenticated US internship search results.
"""
import re
import logging
from datetime import datetime, timezone
from typing import List, Optional
from playwright.async_api import Page

from jobs.discovery.base import DiscoveredJob, DiscoverySource
from jobs.dedupe import normalize_url

logger = logging.getLogger(__name__)


class LinkedInDiscovery(DiscoverySource):
    """Scrapes US Software Engineering & Tech internships from LinkedIn Jobs."""

    SEARCH_URL = "https://www.linkedin.com/jobs/search?keywords=Software%20Engineer%20Intern&location=United%20States&f_E=1"

    def __init__(self):
        super().__init__()

    async def discover(self) -> List[DiscoveredJob]:
        """Discovers jobs from LinkedIn."""
        return await self.fetch_jobs(None)

    async def check_auth_required(self, page: Page) -> bool:
        """Detects if LinkedIn presents a login wall or security challenge."""
        login_indicators = [
            "input#session_key",
            "button[data-id='sign-in-form__submit-btn']",
            "div.sign-in-modal",
            "text='Join LinkedIn'",
            "text='Security Verification'",
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
        """Scrapes LinkedIn US internship search results."""
        if not page:
            logger.info("LinkedIn discovery requires a Playwright page.")
            return []

        logger.info("Navigating to LinkedIn search: %s", self.SEARCH_URL)
        try:
            await page.goto(self.SEARCH_URL, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            logger.warning("Error loading LinkedIn page: %s", e)
            return []

        if await self.check_auth_required(page):
            logger.warning("LinkedIn requires user authentication.")
            return []

        jobs: List[DiscoveredJob] = []
        try:
            cards = page.locator("ul.jobs-search__results-list li, div.base-card")
            count = await cards.count()

            for i in range(min(count, 20)):
                card = cards.nth(i)
                try:
                    title_elem = card.locator("h3.base-search-card__title, h3").first
                    title = (await title_elem.inner_text()).strip() if await title_elem.count() > 0 else ""

                    if not re.search(r"\b(intern|internship|co-op|coop)\b", title.lower()):
                        continue

                    comp_elem = card.locator("h4.base-search-card__subtitle, a[data-tracking-control-name*='company']").first
                    company = (await comp_elem.inner_text()).strip() if await comp_elem.count() > 0 else "Unknown"

                    loc_elem = card.locator("span.job-search-card__location").first
                    location = (await loc_elem.inner_text()).strip() if await loc_elem.count() > 0 else "United States"

                    link_elem = card.locator("a.base-card__full-link, a[href*='/jobs/view/']").first
                    href = await link_elem.get_attribute("href") if await link_elem.count() > 0 else ""

                    if href:
                        job_url = normalize_url(href)
                        jobs.append(DiscoveredJob(
                            company=company,
                            job_title=title,
                            job_url=job_url,
                            location=location,
                            country="United States",
                            employment_type="internship",
                            source="linkedin",
                            discovered_at=datetime.now(timezone.utc),
                        ))
                except Exception as e:
                    logger.debug("Error parsing LinkedIn card %d: %s", i, e)
        except Exception as e:
            logger.warning("Error extracting LinkedIn cards: %s", e)

        return jobs
