"""
jobs/ranking.py
Job queue prioritization and ranking engine.
Assigns priority weights (1=highest, 10=lowest) to pending jobs in the queue.
"""
from typing import List, Dict, Any


def calculate_job_priority(
    job_title: str,
    company: str,
    target_roles: List[str],
    source: str = "manual"
) -> int:
    """
    Calculates priority (1-10, where 1 is highest priority).
    """
    title_lower = (job_title or "").lower()
    comp_lower = (company or "").lower()
    
    # Highest priority for explicit internship/entry-level SWE roles
    if "intern" in title_lower or "co-op" in title_lower:
        if "software" in title_lower or "swe" in title_lower or "backend" in title_lower or "ai" in title_lower:
            return 1
        return 2

    # High priority for new grad / entry level
    if "entry level" in title_lower or "junior" in title_lower or "new grad" in title_lower or "associate" in title_lower:
        return 3

    # Check target roles list
    for tr in target_roles:
        if tr.lower() in title_lower:
            return 2

    # Manual user imports get high baseline priority
    if source == "manual":
        return 4

    return 6
