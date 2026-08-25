# JobAgent — AI-Powered Job Application Agent

A local-first, privacy-preserving autonomous job application agent for Swopnab Bikram Karki.

> **Current Phase:** 1 of 10 — Foundation complete. See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for roadmap.

---

## Quick Start

```bash
# Clone / navigate to the project
cd worklikeadog

# Bootstrap development environment
python3 setup.py

# Start the backend
uvicorn backend.main:app --reload

# Open the dashboard
open http://localhost:8000
```

---

## Requirements

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Backend runtime |
| pip | any | Package management |
| Ollama | any | Local LLM inference |
| BasicTeX | any | Resume PDF compilation (Phase 3) |
| Playwright | 1.48+ | Browser automation (Phase 6) |

### Install Ollama
```bash
# Download from https://ollama.ai, then:
ollama serve
ollama pull llama3.2
```

### Install BasicTeX (for resume compilation)
```bash
brew install --cask basictex
# Restart terminal, then:
sudo tlmgr update --self && sudo tlmgr install latexmk
```

### Install Playwright (Phase 6)
```bash
pip install playwright
playwright install chromium
```

---

## Environment Variables

Copy `.env.example` to `.env` and configure:

```env
# IMPORTANT — safe defaults:
DRY_RUN=true        # NEVER clicks Submit while developing
AUTO_SUBMIT=false   # Must be explicitly enabled

OLLAMA_MODEL=llama3.2
MIN_MATCH_SCORE=65
MAX_APPLICATIONS_PER_DAY=25
```

**Never commit `.env` to version control.**

---

## Architecture

```
worklikeadog/
├── backend/        FastAPI API server
├── agent/          FSM controller, safety rules, crash recovery
├── ai/             LLM provider abstraction (Ollama + future providers)
├── browser/        Playwright automation + ATS site adapters
├── resume/         LaTeX templates + renderer + validator
├── profile/        master_profile.json, project_registry.json
├── database/       SQLAlchemy models + WAL-mode SQLite
├── jobs/           Discovery, eligibility, scoring, deduplication
├── frontend/       Vanilla JS SPA dashboard
└── docs/           Architecture docs
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full details.

---

## Safety Rules (Non-Negotiable)

1. **Never fabricate** technologies, metrics, or experience
2. **Resume must be one page** — hard limit enforced
3. **Rock-Paper-Scissor is permanently blacklisted** — never appears anywhere
4. **DRY_RUN=true by default** — no submissions during development
5. **CAPTCHA/MFA/login → always pause** → user handoff
6. **Sensitive questions (citizenship, sponsorship, legal) → always pause**
7. **Never submit until submission is confirmed** by ATS response
8. **Never submit the same job twice** — fingerprint deduplication

See [docs/AGENT_SAFETY.md](docs/AGENT_SAFETY.md) and [docs/RESUME_RULES.md](docs/RESUME_RULES.md).

---

## Development Phases

| Phase | Status | Description |
|---|---|---|
| 1 | ✅ Complete | Foundation: DB, profile, safety, FSM stubs, full UI |
| 2 | 🔲 Next | Job parsing, eligibility engine, match scorer |
| 3 | 🔲 | Resume tailoring, LaTeX generation, PDF compilation |
| 4 | 🔲 | Application history, local artifact storage |
| 5 | 🔲 | Full agent FSM with job processing loop |
| 6 | 🔲 | Playwright + mock job sites + form detection |
| 7 | 🔲 | Greenhouse, Lever, Ashby adapters |
| 8 | 🔲 | Handoff system (login/MFA/CAPTCHA) |
| 9 | 🔲 | Workday, iCIMS, SmartRecruiters adapters |
| 10 | 🔲 | Overnight operation, notifications, n8n |

---

## Privacy & Security

- All data stored **locally only** (SQLite + filesystem)
- No cloud sync, no third-party services in the critical path
- Generated resumes and application data are **git-ignored**
- Passwords never typed or stored by the agent
- Webpage content is treated as **untrusted input** — never passed to LLM as system instructions

---

## Known Limitations (Phase 1)

- Resume PDF compilation requires BasicTeX (not yet installed)
- AI features require Ollama running with a model pulled
- Browser automation not yet implemented (Phase 6)
- ATS adapters not yet implemented (Phase 7)
- Job discovery is manual URL paste only (Phase 2+)
- Application auto-submit is always OFF during development

These are documented limitations, not bugs. See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for the roadmap.
