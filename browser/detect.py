"""
browser/detect.py
ATS (Applicant Tracking System) platform detection.

Identifies the platform hosting a job application:
- Greenhouse (boards.greenhouse.io, embed iframes, greenhouse forms)
- Lever (jobs.lever.co, lever-form)
- Ashby (jobs.ashbyhq.com, ashby custom elements)
- Workday (myworkdayjobs.com)
- Generic (standard semantic career page / HTML form)
"""
import enum
import re
from typing import Optional, Dict, Any
from urllib.parse import urlparse


class ATSPlatform(str, enum.Enum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    WORKDAY = "workday"
    GENERIC = "generic"
    UNKNOWN = "unknown"


class ATSDetector:
    """Detects ATS platform from URL, page HTML, and DOM cues."""

    # URL domain indicators
    DOMAIN_PATTERNS = {
        ATSPlatform.GREENHOUSE: [
            r"boards\.greenhouse\.io",
            r"job-boards\.greenhouse\.io",
            r"grnh\.se",
        ],
        ATSPlatform.LEVER: [
            r"jobs\.lever\.co",
        ],
        ATSPlatform.ASHBY: [
            r"jobs\.ashbyhq\.com",
            r"ashbyhq\.com",
        ],
        ATSPlatform.WORKDAY: [
            r"myworkdayjobs\.com",
            r"workday\.com",
        ],
    }

    # DOM / HTML content signatures
    DOM_SIGNATURES = {
        ATSPlatform.GREENHOUSE: [
            r'id=["\']application_form["\']',
            r'id=["\']grnh_app["\']',
            r'class=["\'][^"\']*greenhouse[^"\']*["\']',
            r'src=["\'][^"\']*boards\.greenhouse\.io[^"\']*["\']',
            r'data-mapped=["\']true["\']',
        ],
        ATSPlatform.LEVER: [
            r'class=["\'][^"\']*lever-form[^"\']*["\']',
            r'id=["\']application-form["\']',
            r'class=["\'][^"\']*application-page[^"\']*["\']',
            r'action=["\'][^"\']*jobs\.lever\.co[^"\']*["\']',
        ],
        ATSPlatform.ASHBY: [
            r'ashby-application-form',
            r'data-ashby-',
            r'_ashby',
            r'class=["\'][^"\']*ashby[^"\']*["\']',
        ],
        ATSPlatform.WORKDAY: [
            r'data-automation-id=["\']',
            r'wd-app',
            r'workday',
        ],
    }

    @classmethod
    def detect_from_url(cls, url: str) -> ATSPlatform:
        """Fast ATS detection purely from URL patterns."""
        if not url:
            return ATSPlatform.UNKNOWN

        parsed = urlparse(url.lower())
        host = parsed.netloc

        for platform, patterns in cls.DOMAIN_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, host):
                    return platform

        # Path-based cues (e.g. company.com/careers/greenhouse/...)
        path = parsed.path
        if "greenhouse" in path:
            return ATSPlatform.GREENHOUSE
        if "lever" in path:
            return ATSPlatform.LEVER
        if "ashby" in path:
            return ATSPlatform.ASHBY
        if "workday" in path or "myworkday" in path:
            return ATSPlatform.WORKDAY

        return ATSPlatform.GENERIC

    @classmethod
    def detect_from_html(cls, html: str, url: Optional[str] = None) -> ATSPlatform:
        """Deep ATS detection using HTML page content combined with URL."""
        # Check URL first if available
        if url:
            url_match = cls.detect_from_url(url)
            if url_match not in (ATSPlatform.GENERIC, ATSPlatform.UNKNOWN):
                return url_match

        if not html:
            return ATSPlatform.UNKNOWN

        # Search for DOM signatures
        for platform, signatures in cls.DOM_SIGNATURES.items():
            for sig in signatures:
                if re.search(sig, html, re.IGNORECASE):
                    return platform

        return ATSPlatform.GENERIC

    @classmethod
    async def detect_from_page(cls, page: Any) -> ATSPlatform:
        """Inspects live Playwright Page instance to identify platform."""
        url = page.url
        url_match = cls.detect_from_url(url)
        if url_match not in (ATSPlatform.GENERIC, ATSPlatform.UNKNOWN):
            return url_match

        # Check for Greenhouse iframe or elements
        try:
            gh_elem = await page.query_selector("iframe[src*='greenhouse.io'], form#application_form, #grnh_app")
            if gh_elem:
                return ATSPlatform.GREENHOUSE
        except Exception:
            pass

        # Check for Lever elements
        try:
            lever_elem = await page.query_selector(".lever-form, form[action*='lever.co']")
            if lever_elem:
                return ATSPlatform.LEVER
        except Exception:
            pass

        # Check for Ashby elements
        try:
            ashby_elem = await page.query_selector("[data-ashby-application-form], [class*='ashby']")
            if ashby_elem:
                return ATSPlatform.ASHBY
        except Exception:
            pass

        # Check for Workday elements
        try:
            wd_elem = await page.query_selector("[data-automation-id='jobPostingPage'], [data-automation-id='applyButton']")
            if wd_elem:
                return ATSPlatform.WORKDAY
        except Exception:
            pass

        return ATSPlatform.GENERIC
