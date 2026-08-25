"""
browser/fillers/base.py
Abstract base form filler for all ATS and career page application forms.
"""
import abc
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from playwright.async_api import Page, Locator

from browser.field_mapper import FieldMapper, FieldConfidence

logger = logging.getLogger(__name__)


class FillResult:
    """Result summary of a form-filling attempt."""

    def __init__(self):
        self.filled_fields: List[Dict[str, Any]] = []
        self.skipped_fields: List[Dict[str, Any]] = []
        self.paused_fields: List[Dict[str, Any]] = []
        self.requires_human_input: bool = False
        self.pause_reason: Optional[str] = None
        self.success: bool = True

    def record_filled(self, label: str, field_name: str, value: str):
        self.filled_fields.append({"label": label, "name": field_name, "value": value})

    def record_pause(self, label: str, field_name: str, reason: str):
        self.paused_fields.append({"label": label, "name": field_name, "reason": reason})
        self.requires_human_input = True
        if not self.pause_reason:
            self.pause_reason = f"Requires human input: {label} ({reason})"

    def record_skipped(self, label: str, field_name: str, reason: str):
        self.skipped_fields.append({"label": label, "name": field_name, "reason": reason})


class BaseFormFiller(abc.ABC):
    """Abstract interface and helper primitives for ATS form filling."""

    def __init__(self, mapper: Optional[FieldMapper] = None):
        self.mapper = mapper or FieldMapper()

    @abc.abstractmethod
    async def fill_form(
        self,
        page: Page,
        resume_pdf_path: Optional[Path] = None,
        custom_answers: Optional[Dict[str, str]] = None,
    ) -> FillResult:
        """Fills the application form on the given page."""
        pass

    async def get_input_label(self, page: Page, input_locator: Locator) -> str:
        """Determines the human label text associated with an input element."""
        # 1. Check aria-label
        aria_label = await input_locator.get_attribute("aria-label")
        if aria_label:
            return aria_label.strip()

        # 2. Check <label for="id">
        elem_id = await input_locator.get_attribute("id")
        if elem_id:
            try:
                label_elem = page.locator(f"label[for='{elem_id}']")
                if await label_elem.count() > 0:
                    text = await label_elem.first.inner_text()
                    if text.strip():
                        return text.strip()
            except Exception:
                pass

        # 3. Check parent container's label or preceding label sibling
        try:
            parent_label = input_locator.locator("xpath=./ancestor::*[self::div or self::li or self::section][1]//label")
            if await parent_label.count() > 0:
                text = await parent_label.first.inner_text()
                if text.strip():
                    return text.strip()
        except Exception:
            pass

        # 4. Check placeholder
        placeholder = await input_locator.get_attribute("placeholder")
        if placeholder:
            return placeholder.strip()

        # 5. Check name attribute
        name = await input_locator.get_attribute("name")
        if name:
            return name.replace("_", " ").replace("-", " ").strip()

        return ""

    async def select_best_option(self, select_locator: Locator, target_value: str) -> bool:
        """Matches and selects the best option in a standard HTML <select>."""
        options = select_locator.locator("option")
        count = await options.count()
        target_lower = target_value.lower().strip()

        # 1. Exact match
        for i in range(count):
            opt = options.nth(i)
            text = (await opt.inner_text()).lower().strip()
            val = (await opt.get_attribute("value") or "").lower().strip()

            if target_lower in text or target_lower == val:
                val_attr = await opt.get_attribute("value")
                if val_attr is not None:
                    await select_locator.select_option(val_attr)
                    return True

        return False

    async def next_page(self, page: Page) -> bool:
        """
        Clicks intermediate multi-page navigation buttons (Next, Continue, Proceed).
        Guards against clicking final submission buttons.
        """
        from browser.safety_barrier import SafetyBarrier
        nav_buttons = page.locator("button:has-text('Next'), button:has-text('Continue'), input[value*='Next'], input[value*='Continue']")
        count = await nav_buttons.count()
        for i in range(count):
            btn = nav_buttons.nth(i)
            if await btn.is_visible():
                btn_text = (await btn.inner_text() or await btn.get_attribute("value") or "").strip()
                SafetyBarrier.guard_click(text=btn_text, role="button")
                await btn.click()
                await page.wait_for_timeout(1500)
                return True
        return False

    async def final_submit(self, page: Page) -> None:
        """
        Strictly forbidden action. Always raises FinalSubmissionBlocked.
        """
        from browser.safety_barrier import SafetyBarrier
        SafetyBarrier.guard_click(text="Submit Application", role="button", page_stage="final_review")
