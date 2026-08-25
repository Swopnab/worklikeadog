"""
ai/ollama_provider.py
Ollama implementation of the LLM provider interface.
Uses httpx for async HTTP calls to the local Ollama API.
"""
import json
import logging
from typing import Any, Optional

import httpx

from ai.provider import LLMProvider, LLMResult
from agent.safety import wrap_untrusted_for_llm
from config.settings import settings

logger = logging.getLogger(__name__)


# ============================================================
# System prompts (trusted — injected as system instructions)
# ============================================================

JOB_ANALYSIS_SYSTEM_PROMPT = """You are a structured data extractor for job descriptions.
Your job is to extract factual requirements from the job description provided.
You MUST output valid JSON only. No prose, no markdown, just JSON.
Never invent requirements not present in the job description.

Output format:
{
  "required_skills": [],
  "preferred_skills": [],
  "technologies": [],
  "role_type": "",
  "experience_level": "",
  "experience_years_required": null,
  "responsibilities": [],
  "degree_required": null,
  "location": "",
  "location_type": "",
  "sponsorship_mentioned": false,
  "clearance_required": false,
  "visa_restrictions": false
}"""

RESUME_TAILOR_SYSTEM_PROMPT = """You are a resume tailoring assistant with strict honesty rules.

ABSOLUTE RULES:
1. NEVER fabricate technologies, metrics, or project features not in the candidate profile.
2. NEVER invent XYZ metrics (e.g., "improved performance by 40%") unless they are verified facts.
3. NEVER change graduation date, degree, or school name.
4. NEVER include blacklisted projects.
5. Prefer 3 strong projects over 5 weak ones.
6. Only use skills with "verified" status.
7. Output MUST be valid JSON only — never raw LaTeX.

Output format:
{
  "skill_order": [],
  "selected_project_ids": [],
  "project_bullets": {},
  "certifications_to_include": [],
  "reasoning": ""
}"""


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    def __init__(self):
        self.base_url = settings.ollama_base_url
        self.model = settings.ollama_model
        self.timeout = settings.ollama_timeout

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout)

    async def is_available(self) -> bool:
        """Check if Ollama is running and has the configured model."""
        try:
            async with self._make_client() as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code != 200:
                    return False
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                return any(self.model in m for m in models)
        except Exception as e:
            logger.warning("Ollama availability check failed: %s", e)
            return False

    async def generate(self, system_prompt: str, user_message: str, **kwargs) -> LLMResult:
        """Call Ollama chat completion API."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.1),
                "num_predict": kwargs.get("max_tokens", 4096),
            },
        }
        try:
            async with self._make_client() as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("message", {}).get("content", "")
                return LLMResult(
                    content=content,
                    model=self.model,
                    success=True,
                    raw_response=data,
                )
        except httpx.ConnectError:
            logger.error("Cannot connect to Ollama at %s. Is it running?", self.base_url)
            return LLMResult(content="", model=self.model, success=False, error="AI_OFFLINE: Cannot connect to Ollama.")
        except Exception as e:
            logger.error("Ollama generate error: %s", e)
            return LLMResult(content="", model=self.model, success=False, error=str(e))

    async def analyze_job(self, job_description: str) -> LLMResult:
        """Extract structured requirements from a job description."""
        # SAFETY: wrap job description as untrusted data
        wrapped_jd = wrap_untrusted_for_llm(job_description)
        return await self.generate(
            system_prompt=JOB_ANALYSIS_SYSTEM_PROMPT,
            user_message=f"Extract structured data from this job description:\n\n{wrapped_jd}",
            temperature=0.0,  # deterministic extraction
        )

    async def tailor_resume(
        self,
        job_analysis: dict,
        candidate_profile: dict,
        project_registry: dict,
    ) -> LLMResult:
        """Generate tailored resume JSON from verified candidate data."""
        # Blacklist enforced at Python level before calling LLM
        user_message = (
            f"Job Analysis:\n{json.dumps(job_analysis, indent=2)}\n\n"
            f"Candidate Profile (VERIFIED DATA ONLY):\n{json.dumps(candidate_profile, indent=2)}\n\n"
            f"Available Projects:\n{json.dumps(project_registry, indent=2)}\n\n"
            "Generate tailored resume JSON following the output format. "
            "NEVER include blacklisted projects. NEVER fabricate anything."
        )
        return await self.generate(
            system_prompt=RESUME_TAILOR_SYSTEM_PROMPT,
            user_message=user_message,
            temperature=0.1,
        )

    async def generate_answer(
        self,
        question: str,
        context: dict,
        confidence_level: int,
    ) -> LLMResult:
        """Generate application question answer. Level 3 should never be called here."""
        if confidence_level == 3:
            raise ValueError("SAFETY: Level 3 questions must ALWAYS pause. Never call generate_answer for them.")

        system = (
            "You are an honest job application assistant. "
            "Only use information from the provided candidate context. "
            "NEVER fabricate experience, skills, or accomplishments. "
            "If the answer is unknown, say so clearly."
        )
        user = (
            f"Question: {question}\n\n"
            f"Candidate context (verified only):\n{json.dumps(context, indent=2)}\n\n"
            "Provide a concise, honest answer."
        )
        return await self.generate(system_prompt=system, user_message=user, temperature=0.2)


# Singleton provider instance
_provider: Optional[OllamaProvider] = None


def get_llm_provider() -> OllamaProvider:
    global _provider
    if _provider is None:
        _provider = OllamaProvider()
    return _provider
