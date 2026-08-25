"""
browser/fillers/ashby.py
Ashby ATS Application Form Filler (jobs.ashbyhq.com).
"""
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from playwright.async_api import Page

from browser.fillers.base import BaseFormFiller, FillResult
from browser.field_mapper import FieldConfidence

logger = logging.getLogger(__name__)


class AshbyFiller(BaseFormFiller):
    """Fills Ashby modern React-based application forms."""

    async def fill_form(
        self,
        page: Page,
        resume_pdf_path: Optional[Path] = None,
        custom_answers: Optional[Dict[str, str]] = None,
    ) -> FillResult:
        result = FillResult()
        logger.info("Starting Ashby form filling")

        # 1. Resume file upload
        if resume_pdf_path and Path(resume_pdf_path).exists():
            try:
                file_input = page.locator("input[type='file']").first
                if await file_input.count() > 0:
                    await file_input.set_input_files(str(resume_pdf_path))
                    result.record_filled("Resume Upload", "resume_file", str(resume_pdf_path))
                    await page.wait_for_timeout(1000)
            except Exception as e:
                logger.warning("Failed uploading resume to Ashby: %s", e)

        # 2. Iterate all visible inputs and textareas
        inputs = page.locator("input:not([type='hidden']):not([type='file']), textarea, select")
        count = await inputs.count()

        for i in range(count):
            loc = inputs.nth(i)
            try:
                if not await loc.is_visible():
                    continue

                label = await self.get_input_label(page, loc)
                name = await loc.get_attribute("name") or ""
                placeholder = await loc.get_attribute("placeholder") or ""
                field_type = await loc.get_attribute("type") or "text"

                canonical, conf, resolved = self.mapper.classify_field(
                    label=label, name=name, placeholder=placeholder, field_type=field_type
                )

                if conf == FieldConfidence.LEVEL_3_PAUSE:
                    result.record_pause(label or name or "Field", name, "Sensitive / custom question")
                elif conf == FieldConfidence.LEVEL_1_AUTO and resolved:
                    curr_val = await loc.input_value() if field_type != "select" else ""
                    if not curr_val:
                        await loc.fill(resolved)
                        result.record_filled(label or name, name, resolved)
                else:
                    result.record_skipped(label or name, name, "Optional / unmapped")
            except Exception:
                continue

        return result
