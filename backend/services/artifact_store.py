"""
backend/services/artifact_store.py
Local filesystem artifact archiving for every application.

Directory structure:
  applications/
    <company_slug>/
      <job_slug>_<app_id>/
        job.json              — structured job metadata
        job-description.txt   — raw job description text
        analysis.json         — match score + eligibility + project recommendations
        resume.tex            — tailored LaTeX source
        resume.pdf            — compiled PDF (if compiler available)
        answers.json          — generated application answers
        activity.log          — chronological event log
        screenshot.png        — submission confirmation (if captured)

All writes are atomic: write to .tmp then rename.
"""
import hashlib
import json
import re
import shutil
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, List

logger = logging.getLogger(__name__)

from config.settings import settings

ARTIFACTS_ROOT = Path(settings.applications_dir)


def _slug(text: str, max_len: int = 40) -> str:
    """Convert text to a safe, lowercase filesystem slug."""
    text = re.sub(r"[^\w\s-]", "", (text or "unknown").lower())
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:max_len].strip("_")


def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically by writing to .tmp then renaming."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    shutil.move(str(tmp), str(path))


def compute_sha256(file_path: Path) -> Optional[str]:
    """Computes SHA-256 hash of a file."""
    if not file_path.exists():
        return None
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def get_artifact_dir(app_id: int, company: str, job_title: str) -> Path:
    """Returns (and creates) the artifact directory for an application."""
    company_slug = _slug(company)
    job_slug = _slug(job_title)
    dir_path = ARTIFACTS_ROOT / company_slug / f"{job_slug}_{app_id}"
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "screenshots").mkdir(exist_ok=True)
    return dir_path


class ArtifactStore:
    """Manages local artifact files and immutable evidence for each application."""

    @classmethod
    def save_job_metadata(
        cls,
        app_id: int,
        company: str,
        job_title: str,
        job_url: str,
        location: str,
        source: str,
        status: str,
        country: str = "United States",
        employment_type: str = "internship",
        external_job_id: Optional[str] = None,
        posted_at: Optional[str] = None,
    ) -> Path:
        """Saves structured job metadata to job.json."""
        dir_path = get_artifact_dir(app_id, company, job_title)
        data = {
            "app_id": app_id,
            "company": company,
            "job_title": job_title,
            "location": location,
            "country": country,
            "employment_type": employment_type,
            "source": source,
            "source_url": job_url,
            "canonical_url": job_url,
            "external_job_id": external_job_id or "",
            "posted_at": posted_at or "",
            "discovered_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
        }
        out = dir_path / "job.json"
        _atomic_write(out, json.dumps(data, indent=2))
        return out

    @classmethod
    def save_job_description(
        cls,
        app_id: int,
        company: str,
        job_title: str,
        job_description: str,
    ) -> Dict[str, Any]:
        """Saves raw job description text to job-description.txt and returns path and SHA-256 hash."""
        dir_path = get_artifact_dir(app_id, company, job_title)
        out = dir_path / "job-description.txt"
        _atomic_write(out, job_description or "")
        desc_hash = compute_sha256(out)
        return {"path": str(out), "hash": desc_hash}

    @classmethod
    def save_analysis(
        cls,
        app_id: int,
        company: str,
        job_title: str,
        analysis_data: Dict[str, Any],
    ) -> Path:
        """Saves full job evaluation JSON (match score, eligibility, project rankings)."""
        dir_path = get_artifact_dir(app_id, company, job_title)
        out = dir_path / "analysis.json"
        _atomic_write(out, json.dumps(analysis_data, indent=2))
        return out

    @classmethod
    def save_resume(
        cls,
        app_id: int,
        company: str,
        job_title: str,
        latex_source: Optional[str] = None,
        pdf_source_path: Optional[Path] = None,
    ) -> Dict[str, Optional[str]]:
        """Saves tailored resume LaTeX source, copies compiled PDF, and computes PDF SHA-256 hash."""
        dir_path = get_artifact_dir(app_id, company, job_title)
        tex_path = None
        pdf_path = None
        pdf_hash = None

        if latex_source:
            out = dir_path / "resume.tex"
            _atomic_write(out, latex_source)
            tex_path = str(out)

        if pdf_source_path and Path(pdf_source_path).exists():
            dest = dir_path / "resume.pdf"
            if Path(pdf_source_path).resolve() != dest.resolve():
                shutil.copy2(str(pdf_source_path), str(dest))
            pdf_path = str(dest)
            pdf_hash = compute_sha256(dest)

        return {"tex_path": tex_path, "pdf_path": pdf_path, "resume_hash": pdf_hash}

    @classmethod
    def save_answers(
        cls,
        app_id: int,
        company: str,
        job_title: str,
        answers: List[Dict[str, Any]],
    ) -> Path:
        """Saves structured application answers list to answers.json."""
        dir_path = get_artifact_dir(app_id, company, job_title)
        out = dir_path / "answers.json"
        _atomic_write(out, json.dumps(answers, indent=2))
        return out

    @classmethod
    def save_application_state(
        cls,
        app_id: int,
        company: str,
        job_title: str,
        status: str,
        resume_path: Optional[str] = None,
        resume_hash: Optional[str] = None,
        answers_path: Optional[str] = None,
        last_checkpoint: Optional[str] = None,
        submission_confirmation: Optional[str] = None,
        pause_reason: Optional[str] = None,
        ready_for_review_at: Optional[str] = None,
        submitted_at: Optional[str] = None,
    ) -> Path:
        """Saves application state snapshot to application.json."""
        dir_path = get_artifact_dir(app_id, company, job_title)
        data = {
            "application_id": app_id,
            "status": status,
            "resume_path": resume_path,
            "resume_hash": resume_hash,
            "answers_path": answers_path,
            "last_checkpoint": last_checkpoint,
            "submission_confirmation": submission_confirmation,
            "pause_reason": pause_reason,
            "ready_for_review_at": ready_for_review_at,
            "submitted_at": submitted_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        out = dir_path / "application.json"
        _atomic_write(out, json.dumps(data, indent=2))
        return out

    @classmethod
    def append_activity_log(
        cls,
        app_id: int,
        company: str,
        job_title: str,
        events: List[Dict[str, Any]],
    ) -> Path:
        """Appends activity events to the chronological text activity log."""
        dir_path = get_artifact_dir(app_id, company, job_title)
        out = dir_path / "activity.log"
        lines = []
        for ev in events:
            ts = ev.get("created_at") or datetime.now(timezone.utc).strftime("%H:%M:%S")
            etype = ev.get("event_type", "EVENT")
            desc = ev.get("description", "")
            lines.append(f"{ts} | {etype} | {desc}")

        existing = out.read_text(encoding="utf-8") if out.exists() else ""
        updated = existing.rstrip("\n") + "\n" + "\n".join(lines) + "\n"
        _atomic_write(out, updated.lstrip("\n"))
        return out

    @classmethod
    def verify_application_artifacts(cls, app_id: int, company: str, job_title: str) -> Dict[str, Any]:
        """
        Validates that all required physical artifact files exist for the application.
        Required: job.json, job-description.txt, analysis.json, resume.tex, resume.pdf, answers.json, activity.log
        """
        dir_path = get_artifact_dir(app_id, company, job_title)
        required = [
            "job.json", "job-description.txt", "analysis.json",
            "resume.tex", "resume.pdf", "answers.json", "activity.log"
        ]
        missing = [f for f in required if not (dir_path / f).exists()]
        pdf_path = dir_path / "resume.pdf"
        resume_hash = compute_sha256(pdf_path) if pdf_path.exists() else None

        return {
            "valid": len(missing) == 0,
            "missing": missing,
            "dir": str(dir_path),
            "resume_hash": resume_hash,
        }

    @classmethod
    def list_artifacts(cls, app_id: int, company: str, job_title: str) -> Dict[str, Any]:
        """Returns dict of artifact names, their sizes/existence, and SHA-256 hashes."""
        dir_path = get_artifact_dir(app_id, company, job_title)
        artifact_names = [
            "job.json", "job-description.txt", "analysis.json",
            "resume.tex", "resume.pdf", "answers.json", "application.json", "activity.log"
        ]
        result = {
            "dir": str(dir_path),
            "artifacts": {}
        }
        for name in artifact_names:
            p = dir_path / name
            result["artifacts"][name] = {
                "exists": p.exists(),
                "size_bytes": p.stat().st_size if p.exists() else 0,
                "path": str(p) if p.exists() else None,
                "hash": compute_sha256(p) if p.exists() and name.endswith((".pdf", ".txt", ".tex")) else None,
            }

        # Check screenshots
        ss_dir = dir_path / "screenshots"
        if ss_dir.exists():
            for ss in ss_dir.glob("*.png"):
                result["artifacts"][f"screenshots/{ss.name}"] = {
                    "exists": True,
                    "size_bytes": ss.stat().st_size,
                    "path": str(ss),
                }

        return result

    @classmethod
    def read_artifact_text(cls, path: str) -> Optional[str]:
        """Safely reads a text artifact given its absolute path."""
        p = Path(path)
        try:
            p.resolve().relative_to(ARTIFACTS_ROOT.resolve())
        except ValueError:
            logger.warning("Artifact path escape attempt: %s", path)
            return None
        if not p.exists():
            return None
        try:
            return p.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("Error reading artifact %s: %s", path, e)
            return None
