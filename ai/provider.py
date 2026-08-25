"""
ai/provider.py
Abstract LLM provider interface.
All business logic uses this interface — never Ollama directly.
Future providers: OpenAIProvider, GeminiProvider, AnthropicProvider.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class LLMResult:
    """Result from an LLM call."""
    content: str
    model: str
    success: bool
    error: Optional[str] = None
    raw_response: Optional[dict] = None


class LLMProvider(ABC):
    """
    Abstract base class for all LLM providers.
    Every provider must implement these methods.
    Business logic MUST use this interface, never a concrete provider directly.
    """

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the LLM service is reachable and ready."""
        ...

    @abstractmethod
    async def generate(self, system_prompt: str, user_message: str, **kwargs) -> LLMResult:
        """
        Generate a completion.
        
        Args:
            system_prompt: System instructions (trusted — contains our rules)
            user_message: The user message (may contain untrusted job description data)
        """
        ...

    @abstractmethod
    async def analyze_job(self, job_description: str) -> LLMResult:
        """
        Extract structured information from a job description.
        Returns JSON with: required_skills, preferred_skills, responsibilities,
        role_type, technologies, experience_requirements, location_type.
        """
        ...

    @abstractmethod
    async def tailor_resume(
        self,
        job_analysis: dict,
        candidate_profile: dict,
        project_registry: dict,
    ) -> LLMResult:
        """
        Generate tailored resume JSON.
        Output MUST be structured JSON, never raw LaTeX.
        Output MUST NOT fabricate any information.
        Output MUST only include verified skills and projects.
        """
        ...

    @abstractmethod
    async def generate_answer(
        self,
        question: str,
        context: dict,
        confidence_level: int,
    ) -> LLMResult:
        """
        Generate an answer for an application question.
        confidence_level: 1=auto, 2=ai+validation, 3=ALWAYS PAUSE (should not be called)
        """
        ...
