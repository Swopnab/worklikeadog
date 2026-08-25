#!/usr/bin/env python3
"""
setup.py — Development bootstrap script
Run: python3 setup.py
"""
import subprocess
import sys
import shutil
from pathlib import Path

def run(cmd, **kwargs):
    print(f"  $ {cmd}")
    return subprocess.run(cmd, shell=True, **kwargs)

def check(name, cmd):
    result = run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  ✓ {name}: {result.stdout.strip()[:60]}")
        return True
    else:
        print(f"  ✗ {name}: NOT FOUND")
        return False

print("\n🚀 JobAgent — Development Setup")
print("=" * 50)

print("\n📦 Checking core dependencies...")
python_ok  = check("Python", "python3 --version")
pip_ok     = check("pip", "pip --version")
ollama_ok  = check("Ollama CLI", "ollama --version")
latex_ok   = check("pdflatex", "pdflatex --version")
node_ok    = check("Node.js", "node --version")

print("\n📦 Installing Python packages...")
run("pip install -q fastapi 'uvicorn[standard]' alembic aiosqlite python-dotenv structlog aiofiles beautifulsoup4 lxml xxhash python-dateutil sqlalchemy pydantic pydantic-settings httpx requests")

print("\n📁 Creating required directories...")
for directory in [
    "database", "resume/generated", "applications", "logs",
    "profile", "config", "frontend/css", "frontend/js",
    "agent", "ai", "backend/api", "jobs/discovery",
    "browser/sites", "tests/mock_job_sites",
]:
    Path(directory).mkdir(parents=True, exist_ok=True)
    print(f"  ✓ {directory}/")

print("\n⚙️  Setting up environment...")
if not Path(".env").exists():
    shutil.copy(".env.example", ".env")
    print("  ✓ Created .env from .env.example")
    print("  → Edit .env to configure your settings")
else:
    print("  ✓ .env already exists")

print("\n🗄️  Initializing database...")
try:
    result = run("python3 -c \"import asyncio; from database.connection import init_db; asyncio.run(init_db()); print('DB OK')\"", capture_output=True, text=True)
    if "DB OK" in result.stdout:
        print("  ✓ SQLite database initialized with WAL mode")
    else:
        print("  ✗ Database init failed:", result.stderr[:200])
except Exception as e:
    print(f"  ✗ Error: {e}")

print("\n🔒 Running safety checks...")
result = run("python3 -c \"from agent.safety import is_blacklisted; assert is_blacklisted('Rock-Paper-Scissor'); print('Blacklist OK')\"", capture_output=True, text=True)
if "Blacklist OK" in result.stdout:
    print("  ✓ Rock-Paper-Scissor blacklist: ACTIVE")

print("\n📋 Status Summary:")
print(f"  Python:    {'✓' if python_ok else '✗ Required'}")
print(f"  Ollama:    {'✓' if ollama_ok else '⚠ Install from https://ollama.ai — run: ollama pull llama3.2'}")
print(f"  LaTeX:     {'✓' if latex_ok else '⚠ Install: brew install --cask basictex (required for Phase 3)'}")
print(f"  Node.js:   {'✓' if node_ok else '⚠ Optional (not required for current phase)'}")

print("\n🎯 Next Steps:")
print("  1. Start the backend:  uvicorn backend.main:app --reload")
print("  2. Open in browser:    http://localhost:8000")
if not ollama_ok:
    print("  3. Install Ollama:     https://ollama.ai")
    print("     Then run:           ollama serve && ollama pull llama3.2")
if not latex_ok:
    print("  4. Install LaTeX:      brew install --cask basictex")
    print("     (Required for Phase 3 resume generation)")

print("\n✅ Setup complete!\n")
