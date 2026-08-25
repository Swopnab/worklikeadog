"""
browser/fillers/workday.py
Workday ATS Application Form Filler (myworkdayjobs.com).

Handles:
- Multi-step wizard navigation (My Information -> My Experience -> Questions -> Review)
- Workday authentication barrier detection (Sign in / Create Account modal)
- Workday data-automation-id input selectors
- Pre-submit safety checkpoint pause
"""
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from playwright.async_api import Page, Locator

from browser.fillers.base import BaseFormFiller, FillResult
from browser.field_mapper import FieldConfidence

logger = logging.getLogger(__name__)


class WorkdayFiller(BaseFormFiller):
    """Fills Workday multi-step enterprise application wizards."""

    async def fill_form(
        self,
        page: Page,
        resume_pdf_path: Optional[Path] = None,
        custom_answers: Optional[Dict[str, str]] = None,
    ) -> FillResult:
        result = FillResult()
        logger.info("Starting Workday multi-stage application filling")

        # 1. Check for Workday Sign-in / Create Account modal
        signin_modal = page.locator("div[data-automation-id='signInModal'], button[data-automation-id='signInSubmitButton'], input[data-automation-id='email'][type='password']")
        if await signin_modal.count() > 0 and await signin_modal.first.is_visible():
            logger.warning("Workday login / account barrier detected")
            result.record_pause("Workday Authentication", "login_modal", "Workday requires manual sign-in / account authentication.")
            return result

        # 2. Check for Resume file upload dropzone / input
        if resume_pdf_path and Path(resume_pdf_path).exists():
            try:
                file_input = page.locator("input[type='file'], div[data-automation-id='file-upload-drop-zone'] input").first
                if await file_input.count() > 0:
                    await file_input.set_input_files(str(resume_pdf_path))
                    result.record_filled("Resume Upload", "resume_file", str(resume_pdf_path))
                    await page.wait_for_timeout(1500)
            except Exception as e:
                logger.warning("Workday resume upload notice: %s", e)

        # 3. Fill current page fields using Workday automation IDs & standard selectors
        await self._fill_workday_fields(page, result)

        # 4. Check for validation errors on current step
        error_locs = page.locator("div[data-automation-id='errorMessage'], span[data-automation-id='validationError'], div[role='alert']")
        if await error_locs.count() > 0:
            for i in range(await error_locs.count()):
                err = error_locs.nth(i)
                if await err.is_visible():
                    err_text = (await err.inner_text()).strip()
                    if err_text:
                        logger.warning("Workday form validation alert: %s", err_text)
                        result.record_pause("Workday Validation Error", "validation_alert", err_text)
                        return result

        # 5. Workday multi-step: look for 'Save and Continue' or 'Next'
        next_button = page.locator("button[data-automation-id='bottom-navigation-next-button'], button:has-text('Save and Continue'), button:has-text('Next')").first
        if await next_button.count() > 0 and await next_button.is_visible():
            logger.info("Workday next step button detected. Pausing at safe boundary for human review.")
            result.record_pause("Multi-Step Wizard Boundary", "next_step", "Workday multi-stage application ready for review.")

        return result

    async def _fill_workday_fields(self, page: Page, result: FillResult) -> None:
        """Fills visible inputs on the active Workday stage."""
        inputs = page.locator("input:not([type='hidden']):not([type='file']), select, textarea")
        count = await inputs.count()

        for i in range(count):
            loc = inputs.nth(i)
            try:
                if not await loc.is_visible():
                    continue

                auto_id = await loc.get_attribute("data-automation-id") or ""
                name = await loc.get_attribute("name") or auto_id
                placeholder = await loc.get_attribute("placeholder") or ""
                label = await self.get_input_label(page, loc) or auto_id
                field_type = await loc.get_attribute("type") or "text"

                canonical, conf, resolved = self.mapper.classify_field(
                    label=f"{auto_id} {label}", name=name, placeholder=placeholder, field_type=field_type
                )

                if conf == FieldConfidence.LEVEL_3_PAUSE:
                    result.record_pause(label or auto_id, name, "Sensitive / voluntary disclosure question")
                elif conf == FieldConfidence.LEVEL_1_AUTO and resolved:
                    curr_val = await loc.input_value() if field_type != "select" else ""
                    if not curr_val:
                        await loc.fill(resolved)
                        result.record_filled(label or auto_id, name, resolved)
                else:
                    result.record_skipped(label or auto_id, name, "Unmapped / Optional")
            except Exception:
                continue
