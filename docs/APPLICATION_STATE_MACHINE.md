# Application State Machine

## States

| State | Description |
|---|---|
| `STOPPED` | Agent is not running. Safe to restart. |
| `STARTING` | Startup in progress. Running crash recovery. |
| `RUNNING` | Agent is actively processing jobs. |
| `PAUSE_REQUESTED` | User requested pause. Finishing current atomic operation. |
| `PAUSED` | Agent paused intentionally by user. Preserves browser state. |
| `NEEDS_ATTENTION` | Automatic pause — user input required (CAPTCHA, MFA, unknown question). |
| `HANDOFF` | Browser tab handed to user for manual interaction. |
| `STOP_REQUESTED` | Graceful stop requested. Finishing current safe operation. |
| `STOPPING` | In the process of shutting down gracefully. |
| `ERROR` | Unrecoverable error. Manual review needed. |

## Valid Transitions

```
STOPPED          → STARTING
STARTING         → RUNNING, ERROR, STOPPED
RUNNING          → PAUSE_REQUESTED, STOP_REQUESTED, NEEDS_ATTENTION, HANDOFF, ERROR, STOPPING
PAUSE_REQUESTED  → PAUSED, STOP_REQUESTED, ERROR
PAUSED           → RUNNING, STOP_REQUESTED, STOPPED
NEEDS_ATTENTION  → HANDOFF, RUNNING, STOP_REQUESTED, STOPPED
HANDOFF          → RUNNING, NEEDS_ATTENTION, STOP_REQUESTED, STOPPED
STOP_REQUESTED   → STOPPING, STOPPED, ERROR
STOPPING         → STOPPED, ERROR
ERROR            → STOPPED, STARTING
```

## Safe Checkpoints

The agent checks for stop/pause signals only at safe checkpoints:
- After job discovery
- After job analysis
- After eligibility check
- After resume generation
- Before opening an application
- Between application pages
- After submission
- After database updates

**Never** interrupts in the middle of a database write or form submission.

## Crash Recovery

On startup, the agent scans for:
- `status=applying` → marked `INTERRUPTED` (unknown if submitted, manual review)
- `status=interrupted` → left for user review
- `status=paused` → eligible to resume
- `status=needs_attention` → user notified
- `status=needs_review` → **never auto-retry** (possible duplicate submission risk)

## Force Kill

Separate from graceful stop. Requires explicit confirmation.
- Immediately stops browser automation
- Marks current application `INTERRUPTED`
- Does NOT mark as submitted unless confirmed
- Saves best available state

## Heartbeat

Agent updates `heartbeat_at` every 30 seconds while running.
A stale heartbeat (>5 minutes old) on startup indicates a crash.
