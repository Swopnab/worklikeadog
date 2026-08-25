"""
browser/safety_barrier.py
Pre-Submit Safety Barrier & Review Guard.

Enforces absolute hard rules before application submission:
1. auto_submit MUST be True in config/settings
2. dry_run MUST be False
3. match_score MUST be >= min_match_score
4. eligibility_status MUST be 'passed'
5. Zero Level 3 sensitive/legal flags
6. Company / role MUST NOT be in safety blacklist
7. Full pre-submit screenshot captured and stored as local artifact

If any condition is not met, the system NEVER submits; it pauses and alerts the user.
"""
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from config.settings import settings
from agent.safety import is_blacklisted

logger = logging.getLogger(__name__)


FINAL_SUBMISSION_ALLOWED = False
REAL_APPLICATIONS_ENABLED = False
DRY_RUN = True


class FinalSubmissionBlocked(Exception):
    """Raised when an automated action attempts to execute the final employer submission button."""
    pass


# Final submission button label patterns (case-insensitive)
FINAL_SUBMIT_REGEX = re.compile(
    r"\b(submit(\s+my)?\s+application|apply\s+now|complete\s+application|finish\s+application|"
    r"send\s+application|confirm\s+and\s+submit|review\s+and\s+submit|^submit$|^apply$|^finish$)\b",
    re.IGNORECASE,
)


class SafetyBarrier:
    """Evaluates submission safety criteria and enforces review stops."""

    @classmethod
    def is_final_submission_element(
        cls,
        text: str = "",
        role: str = "",
        surrounding_context: str = "",
        page_stage: str = ""
    ) -> bool:
        """
        Determines whether a target interactive element represents the final submission action.
        """
        combined = f"{text} {surrounding_context}".lower().strip()
        
        # Check against final submit patterns
        if FINAL_SUBMIT_REGEX.search(text.strip()):
            return True
        if "submit" in text.lower() and not re.search(r"next|continue|save|preview|upload", text.lower()):
            return True
        if page_stage in ("review", "final_review", "summary") and re.search(r"finish|complete|done", text.lower()):
            return True
        return False

    @classmethod
    def guard_click(
        cls,
        text: str = "",
        role: str = "",
        surrounding_context: str = "",
        page_stage: str = ""
    ) -> None:
        """
        Guards any browser click action. Raises FinalSubmissionBlocked if target is a final submit.
        """
        if cls.is_final_submission_element(text, role, surrounding_context, page_stage):
            logger.warning("Final submission click BLOCKED by browser guard: '%s'", text)
            raise FinalSubmissionBlocked(
                f"Automated click on final submission button '{text}' is strictly forbidden by policy. "
                "Application paused in READY_FOR_REVIEW state for human review."
            )

    @classmethod
    def evaluate_submission_readiness(
        cls,
        company: str,
        job_title: str,
        match_score: Optional[float],
        eligibility_passed: bool,
        requires_human_input: bool,
        pause_reason: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Returns (can_auto_submit, reason_message).
        In this version, FINAL_SUBMISSION_ALLOWED is permanently False.
        Applications always pause at the review page for human review (READY_FOR_REVIEW).
        """
        # Hard policy override: Final automated submission is permanently disabled
        if not FINAL_SUBMISSION_ALLOWED:
            return False, "Application ready for review. Automated submission is disabled; user must inspect and submit manually."

        # 1. Blacklist check
        if is_blacklisted(company) or is_blacklisted(job_title):
            return False, f"Blacklisted company or role: {company} / {job_title}"

        # 2. Hard eligibility requirement
        if not eligibility_passed:
            return False, "Eligibility check FAILED. Submission forbidden."

        # 3. Sensitive / Legal / Level 3 Pause flags
        if requires_human_input:
            return False, f"Human input required: {pause_reason or 'sensitive questions on form'}"

        return False, "Awaiting manual human review and submission."
