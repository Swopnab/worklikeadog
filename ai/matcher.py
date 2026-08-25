"""
ai/matcher.py
High-level matching coordinator.
Orchestrates:
1. Job description parsing (LLM or heuristic)
2. Hard eligibility gate evaluation
3. Deterministic 100-point job match scoring
4. Verified project recommendations
5. Decision recommendation (Apply vs Skip)
"""
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from ai.job_parser import JobParser
from jobs.eligibility import EligibilityChecker, EligibilityResult
from jobs.scoring import JobMatchEngine, ScoreBreakdown
from config.settings import settings

logger = logging.getLogger(__name__)

PROFILE_PATH = Path("profile/master_profile.json")
PROJECTS_PATH = Path("profile/project_registry.json")


def load_candidate_data() -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Loads master profile and project registry from disk."""
    profile = {}
    projects = {}
    if PROFILE_PATH.exists():
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    if PROJECTS_PATH.exists():
        projects = json.loads(PROJECTS_PATH.read_text(encoding="utf-8"))
    return profile, projects


class MatchCoordinator:
    """
    Main evaluation pipeline for jobs.
    """

    def __init__(self):
        self.profile, self.project_registry = load_candidate_data()
        self.parser = JobParser()
        self.eligibility_checker = EligibilityChecker(self.profile)
        self.scoring_engine = JobMatchEngine(self.profile, self.project_registry)

    async def evaluate_job(
        self,
        job_description: str,
        job_title: str = "",
        company: str = "",
        job_url: str = "",
        location: str = "",
    ) -> Dict[str, Any]:
        """
        Runs the full evaluation workflow for a job description.
        Returns complete analysis, eligibility status, match score breakdown,
        matched/missing skills, recommended projects, and apply decision.
        """
        # Reload profile in case user edited it
        self.profile, self.project_registry = load_candidate_data()
        self.eligibility_checker = EligibilityChecker(self.profile)
        self.scoring_engine = JobMatchEngine(self.profile, self.project_registry)

        # 1. Parse Job Description
        parsed = await self.parser.parse(
            job_description=job_description,
            job_title=job_title,
            company=company,
        )
        if location and not parsed.get("location"):
            parsed["location"] = location

        # 2. Hard Eligibility Check
        eligibility: EligibilityResult = self.eligibility_checker.evaluate(parsed)

        # 3. Deterministic Match Score (0 - 100)
        score_breakdown: ScoreBreakdown = self.scoring_engine.score(parsed)

        # 4. Decision Logic
        min_score = settings.min_match_score
        decision = "apply"
        decision_reason = "Job meets eligibility criteria and match score threshold."

        if not eligibility.passed:
            decision = "skip"
            decision_reason = f"Ineligible: {eligibility.primary_reason}"
        elif score_breakdown.total_score < min_score:
            decision = "skip"
            decision_reason = f"Match score {score_breakdown.total_score}% is below minimum threshold ({min_score}%)."

        return {
            "company": parsed.get("company") or company or "Unknown Company",
            "job_title": parsed.get("job_title") or job_title or "Software Engineer",
            "location": parsed.get("location") or location or "United States",
            "job_url": job_url,
            "eligibility": {
                "passed": eligibility.passed,
                "reason": eligibility.primary_reason,
                "failed_checks": eligibility.failed_checks,
                "warnings": eligibility.warnings,
            },
            "match_score": score_breakdown.total_score,
            "score_breakdown": {
                "required_skills": score_breakdown.required_skills_score,
                "preferred_skills": score_breakdown.preferred_skills_score,
                "role_similarity": score_breakdown.role_similarity_score,
                "project_relevance": score_breakdown.project_relevance_score,
                "location": score_breakdown.location_score,
                "experience": score_breakdown.experience_score,
                "total": score_breakdown.total_score,
            },
            "skills": {
                "matched_required": score_breakdown.matched_required_skills,
                "missing_required": score_breakdown.missing_required_skills,
                "matched_preferred": score_breakdown.matched_preferred_skills,
                "missing_preferred": score_breakdown.missing_preferred_skills,
            },
            "selected_projects": score_breakdown.selected_project_ids,
            "project_rankings": score_breakdown.project_rankings,
            "decision": decision,
            "decision_reason": decision_reason,
            "parsed_requirements": parsed,
        }
