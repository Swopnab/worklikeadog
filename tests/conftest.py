"""Tests use fictional profiles and temporary data, never the user's workspace."""
import atexit
import os
import tempfile
from pathlib import Path

_data = tempfile.TemporaryDirectory(prefix="worklikeadog-tests-")
atexit.register(_data.cleanup)
os.environ["DATABASE_PATH"] = str(Path(_data.name) / "test.db")
os.environ["APPLICATIONS_DIR"] = str(Path(_data.name) / "applications")
os.environ["PROFILE_PATH"] = "tests/fixtures/profile.json"
os.environ["APPROVED_ANSWERS_PATH"] = "tests/fixtures/answers.json"
os.environ["MASTER_RESUME_PATH"] = "tests/fixtures/resume.tex"
os.environ["RESUME_GENERATED_DIR"] = str(Path(_data.name) / "generated")
os.environ["RUNTIME_SETTINGS_PATH"] = str(Path(_data.name) / "settings.json")
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:1"

import pytest_asyncio
from database.connection import init_db, engine
import backend.services.artifact_store as artifacts

artifacts.ARTIFACTS_ROOT = Path(_data.name) / "applications"

@pytest_asyncio.fixture(scope="session", autouse=True)
async def initialize_test_database():
    await init_db()
    yield
    await engine.dispose()
