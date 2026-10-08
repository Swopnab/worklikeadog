"""
backend/api/agent.py
Agent control endpoints: start, stop, pause, resume, force-kill, status.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ConfigDict

from agent.controller import agent_controller
from agent.state_machine import get_current_state
from database.models import AgentStateEnum
from config.settings import settings

router = APIRouter()


class ForceKillRequest(BaseModel):
    confirmed: bool


@router.get("/status")
async def get_agent_status():
    """Get current agent state, heartbeat, and settings."""
    state = await get_current_state()
    from ai.ollama_provider import get_llm_provider
    llm = get_llm_provider()
    ollama_online = await llm.is_available()

    return {
        "state": state.state.value,
        "stop_requested": state.stop_requested,
        "pause_requested": state.pause_requested,
        "current_task_id": state.current_task_id,
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "stopped_at": state.stopped_at.isoformat() if state.stopped_at else None,
        "heartbeat_at": state.heartbeat_at.isoformat() if state.heartbeat_at else None,
        "last_checkpoint": state.last_checkpoint,
        "ollama_online": ollama_online,
        "ollama_model": settings.ollama_model,
        "dry_run": settings.dry_run,
        "auto_submit": settings.auto_submit,
        "min_match_score": settings.min_match_score,
    }


@router.post("/start")
async def start_agent():
    """Start the agent. Runs crash recovery first."""
    from ai.matcher import load_candidate_data
    profile, _ = load_candidate_data()
    if not profile.get("identity", {}).get("email"):
        raise HTTPException(409, "Save your candidate profile before starting the agent.")
    result = await agent_controller.start()
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@router.post("/stop")
async def stop_agent():
    """Request graceful stop at next safe checkpoint."""
    return await agent_controller.stop()


@router.post("/pause")
async def pause_agent():
    """Request pause at next safe checkpoint."""
    return await agent_controller.pause()


@router.post("/resume")
async def resume_agent():
    """Resume from paused state."""
    result = await agent_controller.resume()
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@router.post("/force-kill")
async def force_kill_agent(request: ForceKillRequest):
    """
    Emergency force kill. Requires explicit confirmation.
    Current application will be marked INTERRUPTED.
    """
    if not request.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Force kill requires confirmed=true. This will interrupt the current application."
        )
    return await agent_controller.force_kill()


@router.post("/take-control")
async def take_control():
    """Human user takes control of the browser session from the autonomous agent."""
    from agent.state_machine import transition_state
    state = await get_current_state()
    if state.state in (AgentStateEnum.RUNNING, AgentStateEnum.NEEDS_ATTENTION, AgentStateEnum.PAUSED):
        await transition_state(AgentStateEnum.HANDOFF, checkpoint="human_took_control", task_id=state.current_task_id)
        return {"ok": True, "state": "handoff", "message": "Human has taken control of the session."}
    return {"ok": False, "message": f"Cannot take control in state {state.state.value}"}


@router.post("/hand-back")
async def hand_back():
    """Human user hands control back to the autonomous agent and resumes execution."""
    from agent.state_machine import transition_state
    state = await get_current_state()
    if state.state in (AgentStateEnum.HANDOFF, AgentStateEnum.NEEDS_ATTENTION, AgentStateEnum.PAUSED):
        await transition_state(AgentStateEnum.RUNNING, checkpoint="human_handed_back", task_id=state.current_task_id)
        return {"ok": True, "state": "running", "message": "Control handed back to agent."}
    return {"ok": False, "message": f"Agent is currently in state {state.state.value}"}


@router.get("/settings")
async def get_agent_settings():
    """Get current agent configuration."""
    return {
        "dry_run": settings.dry_run,
        "auto_submit": settings.auto_submit,
        "min_match_score": settings.min_match_score,
        "max_applications_per_day": settings.max_applications_per_day,
        "ollama_model": settings.ollama_model,
        "ollama_base_url": settings.ollama_base_url,
        "browser_headless": settings.browser_headless,
    }


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_match_score: int = Field(ge=0, le=100)
    max_applications_per_day: int = Field(ge=1, le=100)
    ollama_model: str = Field(min_length=1, max_length=100)

@router.put("/settings")
async def update_settings(request: SettingsUpdate):
    import json
    from pathlib import Path
    values = request.model_dump()
    path = Path(settings.runtime_settings_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(values, indent=2), encoding="utf-8")
    temporary.replace(path)
    for key, value in values.items():
        setattr(settings, key, value)
    from ai.ollama_provider import get_llm_provider
    get_llm_provider().model = settings.ollama_model
    return {"ok": True, "message": "Settings saved locally."}
