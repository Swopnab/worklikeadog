"""
jobs/discovery/base.py
Abstract base class for all job discovery sources (Career pages, Greenhouse RSS, Lever, Manual, etc.).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any


@dataclass
class DiscoveredJob:
    url: str = ""
    job_url: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    location: Optional[str] = None
    country: Optional[str] = "United States"
    employment_type: Optional[str] = "internship"
    source: str = "discovery"
    job_description: Optional[str] = None
    external_job_id: Optional[str] = None
    raw_html: Optional[str] = None
    discovered_at: Optional[Any] = None

    def __post_init__(self):
        if not self.url and self.job_url:
            self.url = self.job_url
        elif not self.job_url and self.url:
            self.job_url = self.url


class DiscoverySource(ABC):
    """
    Abstract interface for discovering jobs.
    """

    @abstractmethod
    async def discover(self) -> List[DiscoveredJob]:
        """Discover new jobs."""
        ...
