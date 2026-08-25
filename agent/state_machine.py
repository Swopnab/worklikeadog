"""
agent/state_machine.py
Persistent agent FSM backed by SQLite.
State transitions are atomic — never leave the DB in a half-written state.
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AgentState,
    AgentStateEnum,
    ActivityLog,
    ActivityEventType,
    Application,
    ApplicationStatus,
)
from database.connection import db_session


# ============================================================
# Application Status Guard (Defense-in-Depth)
# ============================================================
FORBIDDEN_APP_TRANSITIONS: list[tuple[ApplicationStatus, ApplicationStatus]] = [
    (ApplicationStatus.APPLYING, ApplicationStatus.SUBMITTED),
    (ApplicationStatus.FORM_FILLED, ApplicationStatus.SUBMITTED),
    (ApplicationStatus.NEEDS_ATTENTION, ApplicationStatus.SUBMITTED),
    (ApplicationStatus.HANDOFF, ApplicationStatus.SUBMITTED),
]


class ApplicationStatusError(Exception):
    """Raised when an illegal or unconfirmed application status transition is attempted."""
    pass


def validate_application_transition(
    current: ApplicationStatus,
    target: ApplicationStatus,
    is_user_confirmed: bool = False
) -> None:
    """
    Guarantees that an application can never transition to SUBMITTED automatically.
    """
    if (current, target) in FORBIDDEN_APP_TRANSITIONS:
        raise ApplicationStatusError(
            f"FORBIDDEN direct transition: {current.value} → {target.value}. "
            "Applications must pause at READY_FOR_REVIEW for human inspection."
        )

    if target == ApplicationStatus.SUBMITTED and not is_user_confirmed:
        raise ApplicationStatusError(
            f"Transition {current.value} → SUBMITTED rejected: "
            "Submissions require explicit human applicant confirmation via the user confirmation endpoint."
        )


# ============================================================
# Valid state transitions
# ============================================================
VALID_TRANSITIONS: dict[AgentStateEnum, list[AgentStateEnum]] = {
    AgentStateEnum.STOPPED:          [AgentStateEnum.STARTING],
    AgentStateEnum.STARTING:         [AgentStateEnum.RUNNING, AgentStateEnum.ERROR, AgentStateEnum.STOPPED],
    AgentStateEnum.RUNNING:          [AgentStateEnum.PAUSE_REQUESTED, AgentStateEnum.STOP_REQUESTED, AgentStateEnum.NEEDS_ATTENTION, AgentStateEnum.HANDOFF, AgentStateEnum.ERROR, AgentStateEnum.STOPPING],
    AgentStateEnum.PAUSE_REQUESTED:  [AgentStateEnum.PAUSED, AgentStateEnum.STOP_REQUESTED, AgentStateEnum.ERROR],
    AgentStateEnum.PAUSED:           [AgentStateEnum.RUNNING, AgentStateEnum.STOP_REQUESTED, AgentStateEnum.STOPPED],
    AgentStateEnum.NEEDS_ATTENTION:  [AgentStateEnum.HANDOFF, AgentStateEnum.RUNNING, AgentStateEnum.STOP_REQUESTED, AgentStateEnum.STOPPED],
    AgentStateEnum.HANDOFF:          [AgentStateEnum.RUNNING, AgentStateEnum.NEEDS_ATTENTION, AgentStateEnum.STOP_REQUESTED, AgentStateEnum.STOPPED],
    AgentStateEnum.STOP_REQUESTED:   [AgentStateEnum.STOPPING, AgentStateEnum.STOPPED, AgentStateEnum.ERROR],
    AgentStateEnum.STOPPING:         [AgentStateEnum.STOPPED, AgentStateEnum.ERROR],
    AgentStateEnum.ERROR:            [AgentStateEnum.STOPPED, AgentStateEnum.STARTING],
}


class StateMachineError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


async def _get_or_create_state(session: AsyncSession) -> AgentState:
    """Get the singleton agent state row, creating it if it doesn't exist."""
    result = await session.execute(select(AgentState).where(AgentState.id == 1))
    state = result.scalar_one_or_none()
    if state is None:
        state = AgentState(id=1, state=AgentStateEnum.STOPPED)
        session.add(state)
        await session.flush()
    return state


async def get_current_state() -> AgentState:
    """Read the current agent state from the database."""
    async with db_session() as session:
        return await _get_or_create_state(session)


async def transition_state(
    new_state: AgentStateEnum,
    checkpoint: Optional[str] = None,
    error_message: Optional[str] = None,
    task_id: Optional[int] = None,
) -> AgentState:
    """
    Atomically transition agent to a new state.
    Validates the transition is allowed.
    Logs the transition to the activity log.
    """
    async with db_session() as session:
        state = await _get_or_create_state(session)
        current = state.state

        # Validate transition (allow self-updates for checkpoints/task_id)
        allowed = VALID_TRANSITIONS.get(current, [])
        if new_state != current and new_state not in allowed:
            raise StateMachineError(
                f"Invalid state transition: {current} → {new_state}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        # Apply transition
        state.state = new_state
        if checkpoint:
            state.last_checkpoint = checkpoint
        if error_message is not None:
            state.error_message = error_message
        if task_id is not None:
            state.current_task_id = task_id

        now = datetime.now(timezone.utc)
        state.heartbeat_at = now

        if new_state == AgentStateEnum.RUNNING and current == AgentStateEnum.STARTING:
            state.started_at = now
            state.stopped_at = None
        elif new_state == AgentStateEnum.STOPPED:
            state.stopped_at = now
            state.stop_requested = False
            state.pause_requested = False
            state.force_kill_requested = False
            state.current_task_id = None

        # Safely determine application_id for activity log
        app_id_for_log = None
        if task_id:
            exists = (await session.execute(select(Application.id).where(Application.id == task_id))).scalar_one_or_none()
            if exists:
                app_id_for_log = task_id

        # Log the transition
        log_entry = ActivityLog(
            application_id=app_id_for_log,
            event_type=ActivityEventType.AGENT_STARTED.value if new_state == AgentStateEnum.RUNNING else ActivityEventType.AGENT_STOPPED.value if new_state == AgentStateEnum.STOPPED else "STATE_TRANSITION",
            description=f"Agent state: {current.value} → {new_state.value}",
            details=checkpoint or error_message,
        )
        session.add(log_entry)
        await session.flush()

        return state


async def request_stop() -> None:
    """Signal the agent to stop gracefully at the next safe checkpoint."""
    async with db_session() as session:
        state = await _get_or_create_state(session)
        state.stop_requested = True
        await session.flush()


async def request_pause() -> None:
    """Signal the agent to pause at the next safe checkpoint."""
    async with db_session() as session:
        state = await _get_or_create_state(session)
        state.pause_requested = True
        await session.flush()


async def request_force_kill() -> None:
    """Signal an emergency force kill. Agent should stop immediately."""
    async with db_session() as session:
        state = await _get_or_create_state(session)
        state.force_kill_requested = True
        state.stop_requested = True
        await session.flush()


async def update_heartbeat() -> None:
    """Update the agent heartbeat timestamp. Call every ~30 seconds while running."""
    async with db_session() as session:
        state = await _get_or_create_state(session)
        state.heartbeat_at = datetime.now(timezone.utc)
        await session.flush()


async def should_stop() -> bool:
    """Check if a stop has been requested. Call at safe checkpoints."""
    async with db_session() as session:
        state = await _get_or_create_state(session)
        return state.stop_requested or state.force_kill_requested


async def should_pause() -> bool:
    """Check if a pause has been requested. Call at safe checkpoints."""
    async with db_session() as session:
        state = await _get_or_create_state(session)
        return state.pause_requested
