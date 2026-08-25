"""
jobs/discovery/manual.py
Manual job importer: extracts clean text, company name, role title, and metadata
from a pasted URL or pasted raw job description text.
"""
import re
import logging
from typing import Optional, Dict, Any
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup

from jobs.discovery.base import DiscoveredJob
from jobs.dedupe import normalize_url

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"


class ManualJobImporter:
    """
    Extracts structured job posting content from URLs or raw pasted text.
    """

    @staticmethod
    async def fetch_url_content(url: str, timeout: int = 15) -> Dict[str, Any]:
        """
        Fetches web page content and cleans HTML into readable text description.
        """
        clean_url = normalize_url(url)
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                html = resp.text
        except Exception as e:
            logger.error("Failed to fetch job URL %s: %s", url, e)
            raise ValueError(f"Could not fetch job posting at {url}: {str(e)}")

        return ManualJobImporter.parse_html(html, source_url=str(resp.url))

    @staticmethod
    def parse_html(html: str, source_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Parses HTML string into structured fields (title, company, description, location).
        """
        soup = BeautifulSoup(html, "html.parser")

        # Strip scripts, styles, navigations, footers
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
            tag.decompose()

        # Try to infer company & title
        page_title = soup.title.string.strip() if soup.title and soup.title.string else ""
        company = ""
        job_title = ""

        # Common job title patterns like "Software Engineer - Company" or "Company: SWE"
        if " - " in page_title:
            parts = page_title.split(" - ")
            job_title = parts[0].strip()
            company = parts[1].strip()
        elif " | " in page_title:
            parts = page_title.split(" | ")
            job_title = parts[0].strip()
            company = parts[1].strip()
        elif " at " in page_title:
            parts = page_title.split(" at ")
            job_title = parts[0].strip()
            company = parts[1].strip()
        else:
            job_title = page_title

        # Check meta tags for company/title (OpenGraph / schema.org)
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            job_title = og_title["content"].strip()
            
        og_site_name = soup.find("meta", property="og:site_name")
        if og_site_name and og_site_name.get("content"):
            company = og_site_name["content"].strip()

        # If source URL is known, detect provider
        source = "web"
        if source_url:
            parsed = urlparse(source_url)
            domain = parsed.netloc.lower()
            if "greenhouse.io" in domain:
                source = "greenhouse"
                # greenhouse URL typically: boards.greenhouse.io/<company>/jobs/<id>
                path_parts = [p for p in parsed.path.split("/") if p]
                if path_parts:
                    company = company or path_parts[0].capitalize()
            elif "lever.co" in domain:
                source = "lever"
                path_parts = [p for p in parsed.path.split("/") if p]
                if path_parts:
                    company = company or path_parts[0].capitalize()
            elif "ashbyhq.com" in domain:
                source = "ashby"
            elif "linkedin.com" in domain:
                source = "linkedin"
            elif "myworkdayjobs.com" in domain:
                source = "workday"

        # Extract text content
        # Check for main container
        main_content = soup.find("main") or soup.find("article") or soup.find(id=re.compile(r"content|job-description|posting", re.I)) or soup.body
        
        if main_content:
            text = main_content.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)

        # Collapse excess empty lines
        clean_text = re.sub(r"\n{3,}", "\n\n", text)

        return {
            "job_title": job_title or "Software Engineering Role",
            "company": company or "Unknown Company",
            "job_description": clean_text,
            "source": source,
            "job_url": source_url or "",
            "canonical_url": normalize_url(source_url or ""),
        }
