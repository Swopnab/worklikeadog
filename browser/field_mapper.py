"""
browser/field_mapper.py
Semantic classification and mapping of job application form fields.

Enforces Safety Level boundaries:
- LEVEL 1 (AUTO): Safe, verified profile facts (First/Last name, email, phone, LinkedIn, GitHub, university, degree, graduation).
- LEVEL 2 (AI + VALIDATION): Safe non-legal questions where approved answers or verified facts exist in master profile.
- LEVEL 3 (ALWAYS PAUSE): Legal attestations, citizenship, visa status, sponsorship, security clearance, demographic questions, background check consent -> NEVER guess; pauses for human input.
"""
import re
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from enum import Enum
from config.settings import settings

logger = logging.getLogger(__name__)


class FieldConfidence(str, Enum):
    LEVEL_1_AUTO = "level_1_auto"          # Auto-fillable verified data
    LEVEL_2_AI = "level_2_ai"              # AI answered, must match profile
    LEVEL_3_PAUSE = "level_3_pause"        # Sensitive / legal / unknown -> Pause


class FieldMapper:
    """Classifies form inputs and retrieves verified answers from profile."""

    def __init__(
        self,
        master_profile_path: Optional[Path] = None,
        approved_answers_path: Optional[Path] = None,
    ):
        master_profile_path = master_profile_path or Path(settings.profile_path)
        approved_answers_path = approved_answers_path or Path(settings.approved_answers_path)
        self.profile = {}
        self.answers = {}
        if master_profile_path.exists():
            try:
                self.profile = json.loads(master_profile_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error("Failed loading master profile: %s", e)

        if approved_answers_path.exists():
            try:
                self.answers = json.loads(approved_answers_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error("Failed loading approved answers: %s", e)

        self.level_1_data = self.answers.get("level_1_auto", {})
        self.f1_approved = self.answers.get("f1_work_authorization_approved", {})
        self.level_3_keywords = [
            "citizen", "citizenship", "clearance", "veteran", "disability",
            "gender", "race", "ethnicity", "hispanic", "latino", "felony",
            "conviction", "criminal", "background check", "drug test",
            "salary", "compensation", "non-compete", "nda", "signature",
            "attest", "certify", "under penalty",
        ]

    def classify_field(self, label: str, name: str = "", placeholder: str = "", field_type: str = "text") -> Tuple[Optional[str], FieldConfidence, Optional[str]]:
        """
        Analyzes field cues (label, name attribute, placeholder) and determines:
        - canonical_key (e.g. 'first_name', 'email')
        - FieldConfidence (LEVEL_1_AUTO, LEVEL_2_AI, LEVEL_3_PAUSE)
        - resolved_value (the verified value to type or select, or None)
        """
        combined = f"{label} {name} {placeholder}".lower().strip()

        # Work authorization is always a human decision; never infer a legal answer.
        if re.search(r"\b(visa|sponsorship|authorization|authorized|cpt|opt|h-?1b|green\s*card|work\s*permit)\b", combined):
            return "work_authorization", FieldConfidence.LEVEL_3_PAUSE, None

        # 2. Check for other Level 3 sensitive/legal pause triggers
        for kw in self.level_3_keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", combined):
                return "sensitive_legal", FieldConfidence.LEVEL_3_PAUSE, None

        # 3. Level 1 Verified Profile Mappings
        # First Name
        if re.search(r"\bfirst\s*name\b|fname|given\s*name", combined):
            val = self.level_1_data.get("first_name", self.profile.get("identity", {}).get("first_name", ""))
            return "first_name", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # Last Name
        if re.search(r"\blast\s*name\b|lname|family\s*name|surname", combined):
            val = self.level_1_data.get("last_name", self.profile.get("identity", {}).get("last_name", ""))
            return "last_name", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # Full Name
        if re.search(r"\bfull\s*name\b|\byour\s*name\b|^name$", combined) and not re.search(r"company|school|user", combined):
            val = self.level_1_data.get("full_name", self.profile.get("identity", {}).get("name", ""))
            return "full_name", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # Email
        if re.search(r"\be-?mail\b", combined) or field_type == "email":
            val = self.level_1_data.get("email", self.profile.get("identity", {}).get("email", ""))
            return "email", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # Phone
        if re.search(r"\bphone\b|\bmobile\b|\bcell\b|\bcontact\s*number\b", combined) or field_type == "tel":
            val = self.level_1_data.get("phone_formatted", self.profile.get("identity", {}).get("phone", ""))
            return "phone", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # LinkedIn
        if re.search(r"linkedin", combined):
            val = self.level_1_data.get("linkedin_url", self.profile.get("links", {}).get("linkedin", ""))
            return "linkedin_url", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # GitHub
        if re.search(r"github", combined):
            val = self.level_1_data.get("github_url", self.profile.get("links", {}).get("github", ""))
            return "github_url", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # Portfolio / Website
        if re.search(r"portfolio|website|personal\s*site|url", combined) and not re.search(r"linkedin|github", combined):
            val = self.level_1_data.get("portfolio_url") or self.level_1_data.get("github_url", self.profile.get("links", {}).get("github", ""))
            return "website", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # Location: City
        if re.search(r"\bcity\b", combined) and not re.search(r"university|college", combined):
            val = self.level_1_data.get("current_city", self.profile.get("identity", {}).get("city", ""))
            return "city", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # Location: State
        if re.search(r"\bstate\b|\bprovince\b", combined):
            val = self.level_1_data.get("current_state", self.profile.get("identity", {}).get("state", ""))
            return "state", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # Location: Country
        if re.search(r"\bcountry\b", combined):
            val = self.level_1_data.get("current_country", self.profile.get("identity", {}).get("country", ""))
            return "country", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # Education: University / School
        if re.search(r"university|college|school|institution", combined):
            val = self.level_1_data.get("university", (self.profile.get("education") or [{}])[0].get("institution", ""))
            return "university", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # Education: Degree
        if re.search(r"\bdegree\b", combined):
            val = self.level_1_data.get("degree", (self.profile.get("education") or [{}])[0].get("degree", ""))
            return "degree", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # Education: Major / Discipline
        if re.search(r"\bmajor\b|\bdiscipline\b|\bfield\s*of\s*study\b", combined):
            val = self.level_1_data.get("major", (self.profile.get("education") or [{}])[0].get("major", ""))
            return "major", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # Education: Graduation Year
        if re.search(r"graduation\s*year|\byear\s*of\s*graduation\b", combined):
            val = self.level_1_data.get("graduation_year", (self.profile.get("education") or [{}])[0].get("graduation_year", ""))
            return "graduation_year", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # Education: Graduation Month / Term
        if re.search(r"graduation\s*month|\bgraduation\s*date\b", combined):
            val = self.level_1_data.get("graduation_month", (self.profile.get("education") or [{}])[0].get("graduation", ""))
            return "graduation_date", FieldConfidence.LEVEL_1_AUTO if val else FieldConfidence.LEVEL_3_PAUSE, val or None

        # Resume file upload
        if re.search(r"resume|cv|curriculum\s*vitae", combined) and field_type == "file":
            return "resume_upload", FieldConfidence.LEVEL_1_AUTO, None

        # Cover Letter
        if re.search(r"cover\s*letter", combined) and field_type == "file":
            return "cover_letter_upload", FieldConfidence.LEVEL_1_AUTO, None

        # If not recognized and not explicitly legal, mark as Level 2 or Level 3 for safety
        return "custom_question", FieldConfidence.LEVEL_3_PAUSE, None
