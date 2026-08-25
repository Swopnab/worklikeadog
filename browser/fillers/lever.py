"""
browser/fillers/lever.py
Lever ATS Application Form Filler (jobs.lever.co).
"""
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from playwright.async_api import Page, Locator

from browser.fillers.base import BaseFormFiller, FillResult
from browser.field_mapper import FieldConfidence

logger = logging.getLogger(__name__)


class LeverFiller(BaseFormFiller):
    """Fills Lever job application forms."""

    async def fill_form(
        self,
        page: Page,
        resume_pdf_path: Optional[Path] = None,
        custom_answers: Optional[Dict[str, str]] = None,
    ) -> FillResult:
        result = FillResult()
        logger.info("Starting Lever form filling")

        # Lever standard fields
        lever_fields = {
            "full_name": ["input[name='name']"],
            "email": ["input[name='email']"],
            "phone": ["input[name='phone']"],
            "linkedin_url": ["input[name='urls[LinkedIn]']", "input[name*='LinkedIn']"],
            "github_url": ["input[name='urls[GitHub]']", "input[name*='GitHub']"],
            "website": ["input[name='urls[Portfolio]']", "input[name*='Portfolio']", "input[name='urls[Other]']"],
            "university": ["input[name*='school']", "input[name*='university']"],
        }

        # 1. Fill standard fields
        for field_key, selectors in lever_fields.items():
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        label = await self.get_input_label(page, loc) or field_key
                        canonical_key, confidence, val = self.mapper.classify_field(label, name=field_key)
                        if val and confidence == FieldConfidence.LEVEL_1_AUTO:
                            await loc.fill(val)
                            result.record_filled(label, field_key, val)
                            break
                except Exception as e:
                    logger.debug("Could not fill standard Lever field %s: %s", field_key, e)

        # 2. Upload resume
        if resume_pdf_path and Path(resume_pdf_path).exists():
            try:
                file_input = page.locator("input[name='resume'], input[type='file']").first
                if await file_input.count() > 0:
                    await file_input.set_input_files(str(resume_pdf_path))
                    result.record_filled("Resume Upload", "resume_file", str(resume_pdf_path))
            except Exception as e:
                logger.warning("Failed uploading resume to Lever: %s", e)

        # 3. Custom / additional questions
        custom_inputs = page.locator(".application-additional input:not([type='hidden']), .application-additional select, .application-additional textarea")
        count = await custom_inputs.count()

        for i in range(count):
            elem = custom_inputs.nth(i)
            try:
                if not await elem.is_visible():
                    continue

                label = await self.get_input_label(page, elem)
                name = await elem.get_attribute("name") or ""
                canonical, conf, resolved = self.mapper.classify_field(label, name=name)

                if conf == FieldConfidence.LEVEL_3_PAUSE:
                    result.record_pause(label, name, "Sensitive / custom question")
                elif conf == FieldConfidence.LEVEL_1_AUTO and resolved:
                    await elem.fill(resolved)
                    result.record_filled(label, name, resolved)
                else:
                    result.record_skipped(label, name, "Optional / unmapped")
            except Exception:
                continue

        return result
