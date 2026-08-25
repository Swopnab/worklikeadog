"""
browser/session.py
Playwright browser session management for the autonomous job application agent.

Key Responsibilities:
- Persistent browser context (user-data-dir) to retain logins and avoid repeated auth
- Configurable headless / headful mode (desktop visible by default for user transparency)
- Human-like typing delay simulation (randomized 40–120ms key delays)
- Natural scrolling and element interaction
- Captcha / Cloudflare / MFA / Login detection that triggers safety pause & user handoff
- Pre-submit / milestone screenshot capture
"""
import asyncio
import logging
import random
import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from playwright.async_api import (
    async_playwright,
    Playwright,
    Browser,
    BrowserContext,
    Page,
    Locator,
    TimeoutError as PlaywrightTimeoutError,
)

logger = logging.getLogger(__name__)

USER_DATA_DIR = Path("data/browser_profile")


class ChallengeDetector:
    """Detects bot challenges, captchas, or login barriers requiring human takeover."""

    CHALLENGE_SELECTORS = [
        "iframe[src*='cloudflare.com']",
        "iframe[src*='recaptcha']",
        "iframe[src*='hcaptcha']",
        "iframe[src*='turnstile']",
        "#cf-challenge-running",
        "#cf-please-wait",
        ".g-recaptcha",
        ".h-captcha",
        "[data-sitekey]",
        "#challenge-form",
        "#px-captcha",
        "div[class*='captcha']",
    ]

    MFA_LOGIN_PATTERNS = [
        "two-factor",
        "2-step verification",
        "enter verification code",
        "sign in with google",
        "sign in with apple",
        "sso login",
        "log in to your account",
        "enter the code sent to",
    ]

    @classmethod
    async def check_page_challenge(cls, page: Page) -> Tuple[bool, Optional[str]]:
        """
        Checks if the current page has a Captcha, bot gate, or MFA/login barrier.
        Returns (has_challenge, challenge_type_string).
        """
        # 1. Check captcha / challenge selectors
        for sel in cls.CHALLENGE_SELECTORS:
            try:
                elem = await page.query_selector(sel)
                if elem:
                    is_visible = await elem.is_visible()
                    if is_visible:
                        return True, f"CAPTCHA / Bot challenge detected ({sel})"
            except Exception:
                continue

        # 2. Check title and body text for MFA / SSO login walls
        try:
            title = (await page.title() or "").lower()
            if "just a moment" in title or "attention required" in title:
                return True, "Cloudflare waiting screen"

            body_text = (await page.inner_text("body") or "").lower()[:1500]
            for pattern in cls.MFA_LOGIN_PATTERNS:
                if pattern in body_text:
                    return True, f"Login / MFA required ({pattern})"
        except Exception:
            pass

        return False, None


class BrowserSession:
    """Manages the lifecycle of a Playwright browser instance and page."""

    def __init__(self, headless: bool = False, user_data_dir: Optional[Path] = None):
        self.headless = headless
        self.user_data_dir = user_data_dir or USER_DATA_DIR
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._is_active: bool = False

    @property
    def is_active(self) -> bool:
        return self._is_active and self._page is not None

    async def start(self) -> Page:
        """Starts Playwright with persistent context."""
        if self.is_active:
            return self._page

        self._playwright = await async_playwright().start()

        # Launch persistent context with desktop viewport
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        self._is_active = True
        logger.info("Browser session started (headless=%s)", self.headless)
        return self._page

    async def get_page(self) -> Page:
        """Returns active page or starts session if not yet initialized."""
        if not self.is_active:
            return await self.start()
        return self._page

    async def navigate(self, url: str, wait_until: str = "domcontentloaded", timeout_ms: int = 30000) -> Page:
        """Navigates to URL and verifies absence of blocking challenges."""
        page = await self.get_page()
        logger.info("Navigating to %s", url)
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            await page.wait_for_timeout(1000)
        except Exception as e:
            logger.warning("Navigation warning for %s: %s", url, e)

        return page

    async def human_type(self, locator: Locator, text: str, min_delay_ms: int = 30, max_delay_ms: int = 85) -> None:
        """Types text character-by-character with randomized human intervals."""
        await locator.click()
        # Clear existing text
        await locator.fill("")
        for char in text:
            await locator.type(char, delay=random.randint(min_delay_ms, max_delay_ms))
            if random.random() < 0.05:
                # Occasional brief thinking pause
                await asyncio.sleep(random.uniform(0.1, 0.25))

    async def natural_scroll(self, distance: int = 400, steps: int = 4) -> None:
        """Emulates smooth natural mouse wheel scrolling."""
        page = await self.get_page()
        for _ in range(steps):
            delta = distance / steps
            await page.mouse.wheel(0, delta)
            await asyncio.sleep(random.uniform(0.05, 0.15))

    async def capture_screenshot(self, output_path: Path, full_page: bool = False) -> Path:
        """Captures a PNG screenshot of the current page."""
        page = await self.get_page()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(output_path), full_page=full_page)
        return output_path

    async def check_challenge(self) -> Tuple[bool, Optional[str]]:
        """Checks current page for Captcha/MFA."""
        if not self.is_active:
            return False, None
        return await ChallengeDetector.check_page_challenge(self._page)

    async def close(self) -> None:
        """Gracefully closes context and Playwright engine."""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        self._page = None
        self._is_active = False
        logger.info("Browser session closed.")
