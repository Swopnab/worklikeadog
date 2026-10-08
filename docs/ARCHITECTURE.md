# WorkLikeADog architecture

Two independent entry points serve different purposes:

- `site/`: a static public website and browser demo, published by GitHub Pages. The demo stores fictional/editable records in localStorage and uses a fixed vocabulary for transparent keyword overlap. It has no backend connection.
- `frontend/` + `backend/`: the full local workspace. FastAPI serves the vanilla JavaScript dashboard and API from one origin. SQLite and filesystem artifacts stay local.

## Local preparation flow

1. `backend/api/profile.py` validates and saves the candidate profile. `ai/matcher.py` reloads it before each evaluation.
2. `jobs/discovery/` imports opportunities. `ai/job_parser.py` extracts structured information through Ollama or a heuristic fallback.
3. `jobs/eligibility.py` and `jobs/scoring.py` evaluate fit. `jobs/dedupe.py` checks normalized URLs and content fingerprints.
4. `ai/resume_tailor.py` selects only verified, non-blacklisted projects and skills. Verified registry bullets are reused, rather than accepting invented model claims.
5. `resume/renderer.py` generates escaped LaTeX. `resume/validator.py` compiles, checks page count/selectable text/sections, and retries with limited content reductions. Missing or invalid PDFs block preparation.
6. `agent/orchestrator.py` advances applications through the state machine and stores artifacts. `browser/` prepares supported form fields, stopping for authentication or sensitive questions. Final submission is manual.
7. `backend/services/artifact_store.py` persists application-specific records; analytics read the SQLite history. Configured webhooks are optional and disabled by default.

## Data boundaries

Private profile and approved answers, `.env`, browser sessions, SQLite files, generated résumés, and application artifacts are Git-ignored. The tracked project registry is public source data and must be reviewed for the candidate using the app. Runtime preferences are restricted to non-sensitive model/threshold/limit fields. Safety flags are hard overrides, not user-configurable toggles.

The local API has no multi-user authentication. Run it on loopback only. The static deployment workflow uploads `site/` exclusively and never packages local data.

## Testing

`tests/conftest.py` isolates databases, artifact directories, generated résumés, and preferences in temporary directories. `tests/fixtures/` provides a fictional identity and baseline source. Mock job pages exercise form preparation without contacting employers. CI adds Chromium and TeX so both browser and PDF paths can be exercised. Optional services are explicitly reported as unavailable, never treated as successful work.

## Supported scope

The repository includes discovery, matching, résumé preparation, storage, handoff, recovery, analytics, and ATS adapters. External job boards and employer forms are not stable APIs; mock coverage does not guarantee every live site works. Real applications require human supervision and final review. There is no automatic final-submission path.
