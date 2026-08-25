"""
backend/services/analytics.py
Computes real analytics from the local SQLite database:
- Most required skills across evaluated jobs
- Most missing skills (skill gaps)
- Match score distribution
- Application funnel counts
- Company + source breakdown
- Timeline of activity over the last 30 days
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Application, ApplicationStatus, ActivityLog


async def compute_analytics(db: AsyncSession) -> Dict[str, Any]:
    """Full analytics report from all local application history."""
    result = await db.execute(select(Application))
    apps = result.scalars().all()

    if not apps:
        return _empty_analytics()

    # 1. Status funnel
    status_counts: Dict[str, int] = Counter(a.status.value for a in apps)

    # 2. Match score distribution
    scores = [a.match_score for a in apps if a.match_score is not None]
    score_avg = round(sum(scores) / len(scores), 1) if scores else 0
    score_min = round(min(scores), 1) if scores else 0
    score_max = round(max(scores), 1) if scores else 0
    score_p75 = round(sorted(scores)[int(len(scores) * 0.75)], 1) if scores else 0

    # Score buckets: 0-49, 50-64, 65-74, 75-84, 85-100
    score_buckets = {"0–49": 0, "50–64": 0, "65–74": 0, "75–84": 0, "85–100": 0}
    for s in scores:
        if s < 50:
            score_buckets["0–49"] += 1
        elif s < 65:
            score_buckets["50–64"] += 1
        elif s < 75:
            score_buckets["65–74"] += 1
        elif s < 85:
            score_buckets["75–84"] += 1
        else:
            score_buckets["85–100"] += 1

    # 3. Required / missing skill analysis (from match_details JSON)
    required_skill_counter: Counter = Counter()
    missing_skill_counter: Counter = Counter()
    technologies_counter: Counter = Counter()

    for a in apps:
        if not a.match_details:
            continue
        try:
            details = json.loads(a.match_details)
        except Exception:
            continue
        # matched_required and missing_required stored in app's resume_skills / notes
        # Try to parse from match_details which stores score breakdown, and resume_skills
        matched = json.loads(a.resume_skills) if a.resume_skills else []
        for sk in matched:
            required_skill_counter[sk] += 1

    # Also scan job descriptions for tech keywords heuristically
    tech_patterns = [
        "python", "javascript", "typescript", "react", "node.js", "django", "flask",
        "fastapi", "aws", "docker", "kubernetes", "sql", "postgresql", "mongodb",
        "redis", "rest api", "graphql", "tensorflow", "pytorch", "langchain",
        "llm", "git", "github", "linux", "java", "c++", "go", "rust", "figma"
    ]
    for a in apps:
        if not a.job_description:
            continue
        desc_lower = a.job_description.lower()
        for tech in tech_patterns:
            if tech in desc_lower:
                technologies_counter[tech] += 1

    top_required = required_skill_counter.most_common(12)
    top_technologies = technologies_counter.most_common(15)

    # 4. Company breakdown
    company_counter: Counter = Counter(a.company for a in apps if a.company)
    top_companies = company_counter.most_common(10)

    # 5. Source breakdown
    source_counter: Counter = Counter(a.source for a in apps if a.source)
    source_breakdown = dict(source_counter)

    # 6. Timeline — applications per day over last 30 days
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    timeline: Dict[str, int] = defaultdict(int)

    for a in apps:
        if not a.discovered_at:
            continue
        # Normalise: SQLite often stores naive datetimes
        dt = a.discovered_at
        if dt.tzinfo is None:
            from datetime import timezone as _tz
            dt = dt.replace(tzinfo=_tz.utc)
        if dt >= thirty_days_ago:
            day_key = dt.strftime("%Y-%m-%d")
            timeline[day_key] += 1

    # Sort timeline by date
    timeline_sorted = dict(sorted(timeline.items()))

    # 7. Eligible vs ineligible rate
    total = len(apps)
    eligible_count = sum(1 for a in apps if a.eligibility_status == "passed")
    ineligible_count = total - eligible_count
    eligibility_rate = round((eligible_count / total) * 100, 1) if total > 0 else 0

    # 8. Apply rate (applied out of eligible)
    applied_count = sum(1 for a in apps if a.status == ApplicationStatus.SUBMITTED)
    apply_rate = round((applied_count / eligible_count * 100), 1) if eligible_count > 0 else 0

    return {
        "total_applications": total,
        "status_counts": dict(status_counts),
        "scores": {
            "avg": score_avg,
            "min": score_min,
            "max": score_max,
            "p75": score_p75,
            "distribution": score_buckets,
            "all_scores": sorted(scores),
        },
        "eligibility": {
            "eligible": eligible_count,
            "ineligible": ineligible_count,
            "rate_pct": eligibility_rate,
        },
        "apply_rate_pct": apply_rate,
        "top_required_skills": [{"skill": k, "count": v} for k, v in top_required],
        "top_technologies_seen": [{"tech": k, "count": v} for k, v in top_technologies],
        "top_companies": [{"company": k, "count": v} for k, v in top_companies],
        "source_breakdown": source_breakdown,
        "timeline": timeline_sorted,
    }


def _empty_analytics() -> Dict[str, Any]:
    return {
        "total_applications": 0,
        "status_counts": {},
        "scores": {"avg": 0, "min": 0, "max": 0, "p75": 0, "distribution": {}, "all_scores": []},
        "eligibility": {"eligible": 0, "ineligible": 0, "rate_pct": 0},
        "apply_rate_pct": 0,
        "top_required_skills": [],
        "top_technologies_seen": [],
        "top_companies": [],
        "source_breakdown": {},
        "timeline": {},
    }
