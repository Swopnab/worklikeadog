"""Candidate profile setup. Private files remain local and git-ignored."""
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from config.settings import settings

router = APIRouter()
PROFILE_PATH = Path(settings.profile_path)
PROJECT_REGISTRY_PATH = Path('profile/project_registry.json')

class Identity(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    first_name: str = ''
    last_name: str = ''
    email: str = Field(min_length=3, max_length=254)
    phone: str = ''
    location: str = ''
    city: str = ''
    state: str = ''
    country: str = ''

    @field_validator('email')
    @classmethod
    def email_valid(cls, value):
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Enter a valid email address')
        return value

class ProfileUpdate(BaseModel):
    identity: Identity
    education: list[dict[str, Any]] = Field(default_factory=list, max_length=10)
    links: dict[str, str] = Field(default_factory=dict)
    skills: dict[str, dict[str, Any]] = Field(default_factory=dict)
    certifications: list[dict[str, Any]] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)

    @field_validator('links')
    @classmethod
    def web_links(cls, value):
        for key, url in value.items():
            if not url:
                continue
            parsed = urlparse(url)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
                raise ValueError(f'{key} must be an HTTP or HTTPS URL')
        return value

    @field_validator('skills')
    @classmethod
    def skill_evidence(cls, value):
        for category in value.values():
            for detail in category.values():
                if not isinstance(detail, (str, dict)):
                    raise ValueError('Skill evidence must be a status or an object with a status')
                status = detail if isinstance(detail, str) else detail.get('status', '')
                if status not in {'verified', 'exposure', 'unverified'}:
                    raise ValueError('Skills must use verified, exposure, or unverified evidence levels')
        return value

@router.get('/')
async def get_profile():
    if PROFILE_PATH.exists():
        profile = json.loads(PROFILE_PATH.read_text(encoding='utf-8'))
        return {**profile, '_configured': bool(profile.get('identity', {}).get('email'))}
    template = json.loads(Path('profile/master_profile.example.json').read_text(encoding='utf-8'))
    return {**template, '_configured': False}

@router.put('/')
async def save_profile(request: ProfileUpdate):
    profile = request.model_dump()
    profile['_meta'] = {'version': '1.0', 'configured': True, 'source': 'user_entered'}
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PROFILE_PATH.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(profile, indent=2) + '\n', encoding='utf-8')
    temporary.replace(PROFILE_PATH)
    return {'ok': True, 'message': 'Your candidate profile was saved locally.'}

@router.get('/projects')
async def get_project_registry():
    if not PROJECT_REGISTRY_PATH.exists():
        raise HTTPException(404, 'Project registry not found')
    return json.loads(PROJECT_REGISTRY_PATH.read_text(encoding='utf-8'))

@router.get('/safety/blacklist-check/{project_name}')
async def check_blacklist(project_name: str):
    from agent.safety import is_blacklisted
    return {'project': project_name, 'blacklisted': is_blacklisted(project_name)}
