"""
ai/job_parser.py
Extracts structured requirements from unstructured job descriptions.
Uses Ollama LLM provider with fallback deterministic heuristic extraction when AI is offline.
"""
import re
import json
import logging
from typing import Dict, Any, List, Optional
from ai.ollama_provider import get_llm_provider

logger = logging.getLogger(__name__)

# Common software engineering skills dictionary for heuristic fallback extraction
COMMON_TECH_PATTERNS = [
    # Languages
    "python", "javascript", "typescript", "java", "c\\+\\+", "c#", "golang", "go", "rust", "c", "sql", "html", "css",
    # Frameworks / Backend
    "react", "node\\.js", "nodejs", "django", "flask", "fastapi", "express", "hono", "spring", "vue", "angular",
    "rest", "restful", "rest api", "graphql", "grpc",
    # AI / ML
    "pytorch", "tensorflow", "scikit-learn", "keras", "opencv", "mediapipe", "llm", "llama", "rag", "langchain",
    "vector database", "huggingface", "openai",
    # Cloud & DevOps
    "aws", "s3", "iam", "ec2", "lambda", "azure", "gcp", "docker", "kubernetes", "k8s", "ci/cd", "github actions",
    "cloudflare", "cloudflare workers", "d1", "terraform", "linux", "unix", "git", "github", "postman",
    # Databases
    "sqlite", "postgresql", "postgres", "mysql", "mongodb", "redis", "dynamodb",
    # Security / Concepts
    "jwt", "rbac", "oauth", "authentication", "authorization", "data structures", "algorithms", "oop"
]


class JobParser:
    """
    Parses unstructured job description text into structured JSON schema.
    """

    def __init__(self):
        self.llm = get_llm_provider()

    async def parse(self, job_description: str, job_title: str = "", company: str = "") -> Dict[str, Any]:
        """
        Extract structured information from the job description.
        Attempts LLM extraction first; falls back to deterministic rule extraction if offline.
        """
        if not job_description or not job_description.strip():
            return self._empty_structure(job_title, company)

        # 1. Try LLM Extraction
        try:
            if await self.llm.is_available():
                result = await self.llm.analyze_job(job_description)
                if result.success and result.content:
                    # Clean markdown code blocks if LLM included ```json
                    cleaned_content = re.sub(r"^```json\s*", "", result.content.strip(), flags=re.MULTILINE)
                    cleaned_content = re.sub(r"```$", "", cleaned_content.strip(), flags=re.MULTILINE)
                    
                    try:
                        data = json.loads(cleaned_content)
                        # Ensure all expected fields exist
                        data["job_title"] = data.get("job_title") or job_title
                        data["company"] = data.get("company") or company
                        data["job_description"] = job_description
                        data["extraction_method"] = "llm"
                        return data
                    except json.JSONDecodeError:
                        logger.warning("LLM output was not valid JSON. Falling back to heuristic parser.")
        except Exception as e:
            logger.warning("LLM job parsing failed: %s. Using heuristic parser.", e)

        # 2. Heuristic Rule-Based Fallback
        return self._heuristic_parse(job_description, job_title, company)

    def _heuristic_parse(self, text: str, job_title: str = "", company: str = "") -> Dict[str, Any]:
        """
        Deterministic regex/NLP extraction of key requirements.
        """
        text_lower = text.lower()
        
        # 1. Extract Technologies / Skills
        detected_skills = []
        for pat in COMMON_TECH_PATTERNS:
            if re.search(r'\b' + pat + r'\b', text_lower):
                clean_skill = pat.replace("\\+", "+").replace("\\.", ".")
                detected_skills.append(clean_skill.title() if len(clean_skill) > 3 else clean_skill.upper())

        # Deduplicate
        seen = set()
        skills = []
        for s in detected_skills:
            if s.lower() not in seen:
                seen.add(s.lower())
                skills.append(s)

        # 2. Extract Experience level / Years
        years = None
        m_years = re.search(r"(\d+)\+?\s*(?:-\s*\d+\s*)?(?:years?|yrs?)\s+of\s+(?:professional\s+|relevant\s+|industry\s+)?experience", text_lower)
        if m_years:
            try:
                years = int(m_years.group(1))
            except ValueError:
                pass

        # 3. Detect Security Clearance & Sponsorship
        clearance = bool(re.search(r"\b(security clearance|top secret|ts/sci|active clearance)\b", text_lower))
        sponsorship = bool(re.search(r"\b(sponsorship|visa|opt|cpt|h1b|work authorization)\b", text_lower))
        
        # 4. Role Type
        role_type = "Internship" if any(w in (job_title + " " + text[:500]).lower() for w in ["intern", "co-op", "student"]) else "Full-Time"

        # Separate into required vs preferred heuristics
        req_skills = skills[:min(len(skills), 7)]
        pref_skills = skills[min(len(skills), 7):min(len(skills), 12)]

        return {
            "job_title": job_title or "Software Engineer",
            "company": company or "Unknown Company",
            "job_description": text,
            "required_skills": req_skills,
            "preferred_skills": pref_skills,
            "technologies": skills,
            "role_type": role_type,
            "experience_level": "Internship" if "intern" in role_type.lower() else ("Entry Level" if not years or years <= 2 else "Mid/Senior"),
            "experience_years_required": years,
            "degree_required": "Bachelor's degree" if "bachelor" in text_lower or "bs" in text_lower else None,
            "location": "Remote" if "remote" in text_lower else "United States",
            "location_type": "Remote" if "remote" in text_lower else "On-site / Hybrid",
            "sponsorship_mentioned": sponsorship,
            "clearance_required": clearance,
            "visa_restrictions": "no sponsorship" in text_lower or "u.s. citizen" in text_lower,
            "responsibilities": [],
            "extraction_method": "heuristic",
        }

    def _empty_structure(self, job_title: str, company: str) -> Dict[str, Any]:
        return {
            "job_title": job_title,
            "company": company,
            "job_description": "",
            "required_skills": [],
            "preferred_skills": [],
            "technologies": [],
            "role_type": "",
            "experience_level": "",
            "experience_years_required": None,
            "degree_required": None,
            "location": "",
            "location_type": "",
            "sponsorship_mentioned": False,
            "clearance_required": False,
            "visa_restrictions": False,
            "responsibilities": [],
            "extraction_method": "none",
        }
