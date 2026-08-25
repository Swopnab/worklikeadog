"""
jobs/discovery/github_feed.py
Scrapes and parses curated GitHub internship and new-grad job repositories.

Parses markdown tables from sources like:
- SimplifyJobs / Pitt CSC Summer Internship lists
- SimplifyJobs New Grad lists
- Community curated tech internship feeds
"""
import re
import logging
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse
import httpx

from jobs.discovery.base import DiscoverySource, DiscoveredJob
from jobs.dedupe import normalize_url
from agent.safety import is_blacklisted

logger = logging.getLogger(__name__)

# Curated GitHub raw markdown feed URLs
GITHUB_FEED_URLS = [
    # SimplifyJobs / PittCSC Summer 2025/2026 Internships
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2025-Internships/dev/README.md",
    "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md",
]


class GitHubFeedScraper(DiscoverySource):
    """Parses markdown job tables from community-curated GitHub repositories."""

    def __init__(self, feed_urls: Optional[List[str]] = None, timeout: int = 15):
        self.feed_urls = feed_urls or GITHUB_FEED_URLS
        self.timeout = timeout

    async def discover(self) -> List[DiscoveredJob]:
        """Fetches and parses all configured GitHub markdown tables."""
        all_jobs: List[DiscoveredJob] = []

        headers = {
            "User-Agent": "WorkLikeDog-JobDiscovery/1.0",
            "Accept": "text/plain, text/markdown",
        }

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for feed_url in self.feed_urls:
                try:
                    logger.info("Fetching GitHub feed: %s", feed_url)
                    resp = await client.get(feed_url, headers=headers)
                    if resp.status_code == 200:
                        jobs = self.parse_markdown_table(resp.text, source=feed_url)
                        logger.info("Discovered %d jobs from %s", len(jobs), feed_url)
                        all_jobs.extend(jobs)
                    else:
                        logger.warning("GitHub feed %s returned status %d", feed_url, resp.status_code)
                except Exception as e:
                    logger.warning("Failed fetching GitHub feed %s: %s", feed_url, e)

        return all_jobs

    def parse_markdown_table(self, markdown_text: str, source: str = "github_feed") -> List[DiscoveredJob]:
        """
        Extracts rows from markdown tables matching:
        | Company | Role | Location | Application/Link | Date Posted |
        """
        discovered: List[DiscoveredJob] = []

        # Find markdown table rows (lines starting and ending with |)
        lines = markdown_text.splitlines()
        for line in lines:
            line_clean = line.strip()
            if not line_clean.startswith("|") or not line_clean.endswith("|"):
                continue

            cells = [c.strip() for c in line_clean.split("|")[1:-1]]
            if len(cells) < 3:
                continue

            # Skip header or divider rows
            if "company" in cells[0].lower() or "---" in cells[0] or ":---" in cells[0]:
                continue

            company_cell = cells[0]
            role_cell = cells[1] if len(cells) > 1 else ""
            location_cell = cells[2] if len(cells) > 2 else ""
            link_cell = cells[3] if len(cells) > 3 else ""

            # Extract clean company name (strip markdown links e.g. **[Google](url)** -> Google)
            company = self._clean_markdown_text(company_cell)
            role = self._clean_markdown_text(role_cell)
            location = self._clean_markdown_text(location_cell)

            # Extract application URL from link_cell or other cells
            target_url = self._extract_url_from_markdown(link_cell) or self._extract_url_from_markdown(role_cell) or self._extract_url_from_markdown(company_cell)
            if not target_url:
                continue

            target_url = normalize_url(target_url)

            # Apply Blacklist Guard
            if is_blacklisted(company) or is_blacklisted(role):
                continue

            # Location filter check (if clearly outside US, skip)
            if location and re.search(r"\b(uk|london|berlin|germany|canada|toronto|india|bangalore|singapore|australia|sydney)\b", location.lower()):
                if not re.search(r"\b(us|united states|remote|tx|ca|ny|wa|ma|il|co|wa)\b", location.lower()):
                    continue

            discovered.append(
                DiscoveredJob(
                    url=target_url,
                    company=company,
                    job_title=role or "Software Engineering Intern",
                    location=location or "United States",
                    source=f"github:{urlparse(source).path.split('/')[-1]}",
                )
            )

        return discovered

    def _clean_markdown_text(self, text: str) -> str:
        """Strips markdown links, bolding, italics, emojis, and HTML tags."""
        # Replace [Text](url) with Text
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # Remove bold, italics, HTML tags
        text = re.sub(r"[*_`]", "", text)
        text = re.sub(r"<[^>]+>", "", text)
        # Remove common markdown link wrappers like 🔒, ⏳
        text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
        return text.strip()

    def _extract_url_from_markdown(self, text: str) -> Optional[str]:
        """Extracts direct http/https URL from markdown string."""
        # Find href="..." or (https://...)
        match = re.search(r'href=["\'](https?://[^"\']+)["\']', text)
        if match:
            return match.group(1)

        match = re.search(r'\((https?://[^)]+)\)', text)
        if match:
            return match.group(1)

        match = re.search(r'(https?://[^\s|<>"]+)', text)
        if match:
            return match.group(1)

        return None
