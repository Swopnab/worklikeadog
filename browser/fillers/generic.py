"""
browser/fillers/generic.py
Generic fallback form filler for custom career pages and unclassified ATS platforms.
"""
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from playwright.async_api import Page

from browser.fillers.base import BaseFormFiller, FillResult
from browser.field_mapper import FieldConfidence

logger = logging.getLogger(__name__)


class GenericFormFiller(BaseFormFiller):
    """Fills general HTML5 semantic forms using standard label & attribute heuristics."""

    async def fill_form(
        self,
        page: Page,
        resume_pdf_path: Optional[Path] = None,
        custom_answers: Optional[Dict[str, str]] = None,
    ) -> FillResult:
        result = FillResult()
        logger.info("Starting Generic form filling")

        # 1. Attach resume if file input found
        if resume_pdf_path and Path(resume_pdf_path).exists():
            try:
                file_input = page.locator("input[type='file']").first
                if await file_input.count() > 0:
                    await file_input.set_input_files(str(resume_pdf_path))
                    result.record_filled("Resume Upload", "file", str(resume_pdf_path))
            except Exception as e:
                logger.debug("Generic resume upload note: %s", e)

        # 2. Iterate all visible interactive inputs
        inputs = page.locator("input:not([type='hidden']):not([type='file']):not([type='submit']):not([type='button']), textarea, select")
        count = await inputs.count()

        for i in range(count):
            elem = inputs.nth(i)
            try:
                if not await elem.is_visible():
                    continue

                label = await self.get_input_label(page, elem)
                name = await elem.get_attribute("name") or ""
                placeholder = await elem.get_attribute("placeholder") or ""
                field_type = await elem.get_attribute("type") or "text"
                tag_name = (await elem.evaluate("el => el.tagName")).lower()

                canonical, conf, resolved = self.mapper.classify_field(
                    label=label, name=name, placeholder=placeholder, field_type=field_type
                )

                if conf == FieldConfidence.LEVEL_3_PAUSE:
                    result.record_pause(label or name or f"Input #{i+1}", name, "Sensitive / custom field")
                elif conf == FieldConfidence.LEVEL_1_AUTO and resolved:
                    if tag_name == "select":
                        await self.select_best_option(elem, resolved)
                    else:
                        curr_val = await elem.input_value()
                        if not curr_val:
                            await elem.fill(resolved)
                    result.record_filled(label or name, name, resolved)
                else:
                    result.record_skipped(label or name, name, "Unmapped field")
            except Exception:
                continue

        return result
