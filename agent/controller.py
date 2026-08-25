"""
agent/controller.py
Top-level agent orchestrator. Manages the main run loop.
All long-running business logic lives in Python here, NOT in n8n.

Phase 1: Stub with start/stop/pause/resume control.
Phase 5: Full implementation with job processing loop.
"""
import asyncio
import logging
from datetime import datetime, timezone

from agent.state_machine import (
    transition_state, should_stop, should_pause,
    request_stop, request_pause, update_heartbeat,
    get_current_state,
)
from agent.recovery import recover_on_startup
from database.models import AgentStateEnum

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30  # seconds


class AgentController:
    """
    The main agent controller. One instance per application process.
    Controls the lifecycle: start → running → pause/stop → stopped.
    """

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

    async def start(self) -> dict:
        """
        Start the agent.
        1. Set state STARTING
        2. Run crash recovery
        3. Set state RUNNING
        4. Launch main loop
        """
        state = await get_current_state()
        if state.state not in (AgentStateEnum.STOPPED, AgentStateEnum.ERROR):
            return {"ok": False, "message": f"Agent is already {state.state.value}. Stop it first."}

        await transition_state(AgentStateEnum.STARTING, checkpoint="startup")
        recovery_report = await recover_on_startup()

        await transition_state(AgentStateEnum.RUNNING, checkpoint="running")

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Start main loop (Phase 5: will actually process jobs)
        self._task = asyncio.create_task(self._main_loop())

        return {"ok": True, "message": "Agent started.", "recovery": recovery_report}

    async def stop(self) -> dict:
        """Request graceful stop. Agent finishes current safe operation then stops."""
        await request_stop()
        return {"ok": True, "message": "Stop requested. Agent will stop at the next safe checkpoint."}

    async def pause(self) -> dict:
        """Request pause at next safe checkpoint."""
        await request_pause()
        return {"ok": True, "message": "Pause requested."}

    async def resume(self) -> dict:
        """Resume from paused state."""
        state = await get_current_state()
        if state.state != AgentStateEnum.PAUSED:
            return {"ok": False, "message": f"Agent is not paused (current: {state.state.value})."}
        await transition_state(AgentStateEnum.RUNNING, checkpoint="resumed")
        return {"ok": True, "message": "Agent resumed."}

    async def force_kill(self) -> dict:
        """Emergency stop. Marks current task as INTERRUPTED."""
        from agent.state_machine import request_force_kill
        await request_force_kill()
        if self._task:
            self._task.cancel()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        try:
            await transition_state(AgentStateEnum.STOPPED, checkpoint="force_killed")
        except Exception:
            pass
        return {"ok": True, "message": "Force kill executed. Current application marked INTERRUPTED."}

    async def _heartbeat_loop(self):
        """Updates heartbeat every 30 seconds while agent is running."""
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                state = await get_current_state()
                if state.state in (AgentStateEnum.STOPPED, AgentStateEnum.ERROR):
                    break
                await update_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat error: %s", e)

    async def _main_loop(self):
        """
        Main agent processing loop.
        Launches the autonomous JobOrchestrator to process queued applications.
        """
        logger.info("Agent main loop started.")
        from agent.orchestrator import JobOrchestrator
        try:
            orchestrator = JobOrchestrator()
            await orchestrator.run_loop()
        except asyncio.CancelledError:
            logger.warning("Agent loop cancelled (force kill).")
        except Exception as e:
            logger.error("Agent loop error: %s", e, exc_info=True)
            try:
                await transition_state(AgentStateEnum.ERROR, error_message=str(e))
            except Exception:
                pass


# Global controller instance
agent_controller = AgentController()
