"""backend/api/profile.py — Candidate profile endpoints."""
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException

router = APIRouter()

PROFILE_PATH = Path("profile/master_profile.json")
PROJECT_REGISTRY_PATH = Path("profile/project_registry.json")


@router.get("/")
async def get_profile():
    """Get the verified candidate profile."""
    if not PROFILE_PATH.exists():
        raise HTTPException(status_code=404, detail="master_profile.json not found")
    return json.loads(PROFILE_PATH.read_text())


@router.get("/projects")
async def get_project_registry():
    """Get the project registry with evidence levels."""
    if not PROJECT_REGISTRY_PATH.exists():
        raise HTTPException(status_code=404, detail="project_registry.json not found")
    return json.loads(PROJECT_REGISTRY_PATH.read_text())


@router.get("/safety/blacklist-check/{project_name}")
async def check_blacklist(project_name: str):
    """Check if a project name is blacklisted."""
    from agent.safety import is_blacklisted
    blacklisted = is_blacklisted(project_name)
    return {"project": project_name, "blacklisted": blacklisted}
