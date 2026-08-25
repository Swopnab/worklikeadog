"""
browser/fillers/greenhouse.py
Greenhouse ATS Application Form Filler (boards.greenhouse.io & embedded forms).
"""
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from playwright.async_api import Page, Locator

from browser.fillers.base import BaseFormFiller, FillResult
from browser.field_mapper import FieldConfidence

logger = logging.getLogger(__name__)


class GreenhouseFiller(BaseFormFiller):
    """Fills Greenhouse board and embedded application forms."""

    async def fill_form(
        self,
        page: Page,
        resume_pdf_path: Optional[Path] = None,
        custom_answers: Optional[Dict[str, str]] = None,
    ) -> FillResult:
        result = FillResult()
        logger.info("Starting Greenhouse form filling")

        # Check if form is inside an iframe
        form_page = page
        iframe_locator = page.locator("iframe#grnh_iframe, iframe[src*='greenhouse.io']")
        if await iframe_locator.count() > 0:
            frame = page.frame(name="grnh_iframe")
            if frame:
                form_page = frame  # type: ignore

        # Standard Greenhouse field selectors
        gh_standard_fields = {
            "first_name": ["#first_name", "input[name='job_application[first_name]']"],
            "last_name": ["#last_name", "input[name='job_application[last_name]']"],
            "email": ["#email", "input[name='job_application[email]']"],
            "phone": ["#phone", "input[name='job_application[phone]']"],
            "linkedin_url": [
                "input[name*='linkedin']",
                "input[id*='linkedin']",
                "input[autocomplete*='linkedin']",
            ],
            "github_url": [
                "input[name*='github']",
                "input[id*='github']",
            ],
            "website": [
                "input[name*='website']",
                "input[id*='website']",
                "input[name*='portfolio']",
            ],
        }

        # 1. Fill standard fields
        for field_key, selectors in gh_standard_fields.items():
            for selector in selectors:
                try:
                    loc = form_page.locator(selector).first
                    if await loc.count() > 0 and await loc.is_visible():
                        label = await self.get_input_label(page, loc) or field_key
                        canonical_key, confidence, val = self.mapper.classify_field(label, name=field_key)
                        if val and confidence == FieldConfidence.LEVEL_1_AUTO:
                            await loc.fill(val)
                            result.record_filled(label, field_key, val)
                            break
                except Exception as e:
                    logger.debug("Could not fill standard Greenhouse field %s: %s", field_key, e)

        # 2. Attach resume PDF if present
        if resume_pdf_path and Path(resume_pdf_path).exists():
            try:
                resume_input = form_page.locator(
                    "input[type='file'][name*='resume'], input[type='file'][id*='resume'], input[data-qa='resume-upload']"
                ).first
                if await resume_input.count() > 0:
                    await resume_input.set_input_files(str(resume_pdf_path))
                    result.record_filled("Resume Upload", "resume_file", str(resume_pdf_path))
            except Exception as e:
                logger.warning("Failed attaching resume to Greenhouse form: %s", e)

        # 3. Process custom questions & selects
        custom_inputs = form_page.locator(".field input:not([type='hidden']):not([type='file']), .field select, .field textarea")
        count = await custom_inputs.count()

        for i in range(count):
            input_elem = custom_inputs.nth(i)
            try:
                if not await input_elem.is_visible():
                    continue

                curr_val = await input_elem.input_value() if await input_elem.evaluate("el => el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'") else ""
                if curr_val:
                    continue  # Already filled

                label = await self.get_input_label(page, input_elem)
                name = await input_elem.get_attribute("name") or ""
                tag_name = (await input_elem.evaluate("el => el.tagName")).lower()

                canonical, conf, resolved = self.mapper.classify_field(label, name=name)

                if conf == FieldConfidence.LEVEL_3_PAUSE:
                    result.record_pause(label, name, "Sensitive / legal / custom question")
                elif conf == FieldConfidence.LEVEL_1_AUTO and resolved:
                    if tag_name == "select":
                        await self.select_best_option(input_elem, resolved)
                    else:
                        await input_elem.fill(resolved)
                    result.record_filled(label, name, resolved)
                else:
                    result.record_skipped(label, name, "Optional / unmapped custom field")
            except Exception:
                continue

        return result
