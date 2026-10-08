#!/usr/bin/env python3
"""Bootstrap the local workspace: python3 setup.py [--skip-browser]."""
import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-browser', action='store_true', help='Skip the optional Chromium download')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Python 3.11 or newer is required.')
    os.chdir(ROOT)
    environment = ROOT / '.venv'
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    print('WorkLikeADog — setting up your local workspace', flush=True)
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', 'requirements.txt'], check=True)
    if not args.skip_browser:
        subprocess.run([str(python), '-m', 'playwright', 'install', 'chromium'], check=True)
    for directory in ['database', 'resume/generated', 'applications', 'logs', 'data']:
        (ROOT / directory).mkdir(parents=True, exist_ok=True)
    if not (ROOT / '.env').exists():
        shutil.copyfile(ROOT / '.env.example', ROOT / '.env')
    subprocess.run([str(python), '-c', 'import asyncio; from database.connection import init_db; asyncio.run(init_db())'], check=True)
    subprocess.run([str(python), '-c', 'from agent.safety import is_blacklisted; assert is_blacklisted("Rock-Paper-Scissor")'], check=True)
    print('\nSetup complete. Start the local workspace:')
    print(f'  {python.relative_to(ROOT)} -m uvicorn backend.main:app --host 127.0.0.1 --port 8000')
    print('  Open http://127.0.0.1:8000 and save your candidate profile.')
    print('\nOptional: run Ollama with your configured model for local AI analysis.')
    print('PDF generation requires a TeX distribution (pdflatex or xelatex).')
    print('Application submission remains manual. Review every generated document.')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(f'\nSetup stopped because a required step failed (exit {error.returncode}).', file=sys.stderr)
        sys.exit(error.returncode)
