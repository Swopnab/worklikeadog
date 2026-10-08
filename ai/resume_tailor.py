"""
ai/resume_tailor.py
AI-driven resume tailoring with strict truthfulness validation.

AI outputs structured JSON only (never raw LaTeX).
Python deterministically validates all claims against verified profile data.
"""
import re
import json
import logging
from typing import Dict, Any, List, Optional
from ai.ollama_provider import get_llm_provider
from agent.safety import is_blacklisted, assert_not_blacklisted, can_auto_place_on_resume

logger = logging.getLogger(__name__)


class ResumeTailor:
    """
    Tailors resume structure and bullet emphasis based on target job description.
    """

    def __init__(self, master_profile: Dict[str, Any], project_registry: Dict[str, Any]):
        self.profile = master_profile
        self.project_registry = project_registry
        self.llm = get_llm_provider()

        # Build lookup table of verified projects and their verified bullets
        self.verified_projects = {}
        for p in self.project_registry.get("projects", []):
            pid = p.get("id", "")
            if pid and not is_blacklisted(pid) and can_auto_place_on_resume(p.get("status", "")):
                self.verified_projects[pid] = p

        # Build lookup table of verified skills
        self.verified_skills_by_cat = {}
        skills_dict = self.profile.get("skills", {})
        for cat, cat_skills in skills_dict.items():
            if isinstance(cat_skills, dict):
                v_list = []
                for s_name, details in cat_skills.items():
                    if isinstance(details, dict) and details.get("status", "").lower() == "verified":
                        v_list.append(s_name)
                    elif isinstance(details, str) and details.lower() == "verified":
                        v_list.append(s_name)
                self.verified_skills_by_cat[cat] = v_list

    async def tailor(self, job_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a validated, tailored resume plan.
        Tries LLM first; falls back to deterministic tailoring if offline.
        """
        target_skills = [
            s.lower() for s in (
                job_analysis.get("required_skills", []) +
                job_analysis.get("preferred_skills", []) +
                job_analysis.get("technologies", [])
            )
        ]

        # 1. Try LLM Tailoring
        llm_tailored_data = None
        try:
            if await self.llm.is_available():
                result = await self.llm.tailor_resume(
                    job_analysis=job_analysis,
                    candidate_profile=self.profile,
                    project_registry=self.project_registry,
                )
                if result.success and result.content:
                    clean_json = re.sub(r"^```json\s*", "", result.content.strip(), flags=re.MULTILINE)
                    clean_json = re.sub(r"```$", "", clean_json.strip(), flags=re.MULTILINE)
                    try:
                        llm_tailored_data = json.loads(clean_json)
                    except json.JSONDecodeError:
                        logger.warning("LLM resume tailor output was not valid JSON.")
        except Exception as e:
            logger.warning("LLM tailoring failed: %s", e)

        # 2. Build or Validate Plan
        if llm_tailored_data:
            plan = self._validate_and_sanitize_llm_plan(llm_tailored_data, target_skills)
        else:
            plan = self._deterministic_tailor(job_analysis, target_skills)

        return plan

    def _validate_and_sanitize_llm_plan(self, raw_plan: Dict[str, Any], target_skills: List[str]) -> Dict[str, Any]:
        """
        Sanitizes LLM output:
        - Drops any blacklisted project immediately
        - Drops any project not in verified registry
        - Ensures exactly 3 top projects are selected
        - Restricts skills strictly to verified candidate skills
        - Enforces verified project bullets
        """
        # 1. Sanitize project selection
        raw_selected_pids = raw_plan.get("selected_project_ids", [])
        valid_selected_pids = []

        for pid in raw_selected_pids:
            clean_pid = str(pid).strip().lower()
            if is_blacklisted(clean_pid):
                continue
            if clean_pid in self.verified_projects and clean_pid not in valid_selected_pids:
                valid_selected_pids.append(clean_pid)

        # Ensure we have at least 3 strong verified projects
        default_order = ["swopmobile", "cybersteer", "aaura-v1", "personal-job-tracker"]
        for d_pid in default_order:
            if len(valid_selected_pids) >= 3:
                break
            if d_pid in self.verified_projects and d_pid not in valid_selected_pids:
                valid_selected_pids.append(d_pid)

        valid_selected_pids = valid_selected_pids[:3]

        # 2. Assemble projects with verified bullets
        selected_projects = []
        for pid in valid_selected_pids:
            assert_not_blacklisted(pid)
            proj_def = self.verified_projects[pid]
            # Use original verified bullets
            orig_bullets = [b["text"] for b in proj_def.get("bullets", []) if b.get("verified") is True]
            selected_projects.append({
                "id": pid,
                "display_name": proj_def.get("display_name"),
                "subtitle": proj_def.get("subtitle"),
                "years": proj_def.get("years"),
                "tech_stack": proj_def.get("tech_stack", []),
                "bullets": orig_bullets,
            })

        # 3. Order skills placing matching verified skills first
        tailored_skills = self._order_skills_by_relevance(target_skills)

        # 4. Certifications
        certs = [c.get("name") for c in self.profile.get("certifications", []) if c.get("verified")]

        return {
            "selected_projects": selected_projects,
            "skills": tailored_skills,
            "certifications": certs,
            "tailoring_summary": raw_plan.get("reasoning") or "Tailored verified skills and project emphasis for target job.",
        }

    def _deterministic_tailor(self, job_analysis: Dict[str, Any], target_skills: List[str]) -> Dict[str, Any]:
        """
        Deterministic tailoring algorithm:
        - Scores projects based on keyword overlap and engineering complexity
        - Ranks and selects top 3 verified projects (Blacklist is strictly enforced)
        - Reorders skills putting matching verified skills first in each category
        """
        # Score each verified project
        scored_projects = []
        for pid, p in self.verified_projects.items():
            assert_not_blacklisted(pid)
            tier = p.get("quality_tier", 2)
            tech = [t.lower() for t in p.get("tech_stack", [])]
            keywords = [k.lower() for k in p.get("keywords", [])]

            score = 60.0 if tier == 1 else 35.0
            for t in tech:
                if t in target_skills:
                    score += 10.0
            for k in keywords:
                if k in target_skills:
                    score += 5.0

            scored_projects.append((score, pid, p))

        # Sort descending by score
        scored_projects.sort(key=lambda x: x[0], reverse=True)
        top_3 = scored_projects[:3]

        selected_projects = []
        for _, pid, proj_def in top_3:
            orig_bullets = [b["text"] for b in proj_def.get("bullets", []) if b.get("verified") is True]
            selected_projects.append({
                "id": pid,
                "display_name": proj_def.get("display_name"),
                "subtitle": proj_def.get("subtitle"),
                "years": proj_def.get("years"),
                "tech_stack": proj_def.get("tech_stack", []),
                "bullets": orig_bullets,
            })

        tailored_skills = self._order_skills_by_relevance(target_skills)
        certs = [c.get("name") for c in self.profile.get("certifications", []) if c.get("verified")]

        return {
            "selected_projects": selected_projects,
            "skills": tailored_skills,
            "certifications": certs,
            "tailoring_summary": "Deterministically ranked projects and prioritized matching verified skills.",
        }

    def _order_skills_by_relevance(self, target_skills: List[str]) -> Dict[str, List[str]]:
        """
        Sorts verified skills inside each category so that matching skills appear first.
        """
        ordered = {}
        for cat, skills in self.verified_skills_by_cat.items():
            matching = []
            others = []
            for s in skills:
                if s.lower() in target_skills:
                    matching.append(s)
                else:
                    others.append(s)
            ordered[cat] = matching + others
        return ordered
