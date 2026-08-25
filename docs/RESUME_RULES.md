# Resume Rules

## Hard Requirements

1. **One page only.** Never exceed one page. This is a hard requirement, not a soft preference.
2. **Use existing resume as baseline.** Never reconstruct formatting from scratch.
3. **Never fabricate.** Any claim that cannot be verified from the master profile or GitHub is excluded.
4. **Truthfulness priority.** ATS keyword matching never overrides truthfulness.

## Project Selection Rules

Priority order:
1. Technical depth
2. Relevance to target job
3. Engineering complexity
4. Recency
5. Uniqueness
6. Verified implementation quality
7. Keyword overlap

**3 excellent projects beats 5 weak projects.**

### Permanently Blacklisted
- `Rock-Paper-Scissor` — NEVER under any circumstance

### Tier 1 (Always eligible)
- SwopMobile — JWT Authentication, RBAC & AI Workspace
- CyberSteer — Hand-Controlled Racing Game
- AAURA-V1 — Advanced AI-Utilized Responsive Assistant

### Tier 2 (Include when relevant)
- Personal Job Tracker

### Conditional (EXPOSURE level — evaluate per job)
- Zabum-AI, my-react-blog, Music-Player, Website

## Skill Evidence Levels

| Level | Meaning | Auto-place on Resume? |
|---|---|---|
| `verified` | Actually implemented and defensible | ✅ Yes |
| `exposure` | Touched/experimented with | ❌ No |
| `unverified` | Do not use | ❌ Never |

## XYZ Method

Use XYZ-style bullets only when real measurable information exists.

Verified real numbers from resume:
- 3 RBAC roles (SwopMobile)
- 15-minute access token lifetime (SwopMobile)
- 21 MediaPipe landmarks (CyberSteer)
- Speed progression 50–100 mph (CyberSteer)

**Never invent** "Improved performance by 40%" without actual measurement.

## One-Page Enforcement Algorithm

If generated resume exceeds one page:
1. Shorten lowest-priority bullet
2. Remove redundant wording
3. Reduce lower-priority certifications
4. Remove least relevant project
5. Compile again
6. Repeat until exactly 1 page

Never remove strong relevant content before weaker content.

## LaTeX Generation Flow

```
AI (Ollama) → structured JSON output
↓
Python validates JSON against master_profile.json
↓
Safety check: blacklist, evidence levels, fabrication detection
↓
Deterministic Python generates LaTeX (never Ollama writes raw LaTeX)
↓
latex_escape.py escapes all special characters
↓
pdflatex/latexmk compiles locally
↓
Validator: page count, selectable text, section presence
↓
Both resume.tex and resume.pdf saved
```

AI outputs **JSON only**. Python generates LaTeX. This prevents LLM hallucination from corrupting the document.
