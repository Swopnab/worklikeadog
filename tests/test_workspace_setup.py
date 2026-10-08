"""First-run setup, artifact access, and truthful document readiness regressions."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pypdf

from backend.main import app
from backend.api import profile as profile_api, resume as resume_api
from config.settings import settings
import ai.matcher as matcher
import resume.validator as validator
from ai.resume_tailor import ResumeTailor


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        yield client


@pytest.fixture
def candidate():
    return json.loads(Path('tests/fixtures/profile.json').read_text())


@pytest.mark.asyncio
async def test_clean_checkout_profile_setup_and_roundtrip(client, tmp_path, monkeypatch, candidate):
    private_path = tmp_path / 'profile.json'
    monkeypatch.setattr(profile_api, 'PROFILE_PATH', private_path)
    monkeypatch.setattr(matcher, 'PROFILE_PATH', private_path)
    blank = await client.get('/api/profile/')
    assert blank.status_code == 200
    assert blank.json()['_configured'] is False
    assert blank.json()['identity']['email'] == ''
    missing = await client.post('/api/jobs/analyze', json={'job_description':'Python software engineering internship'})
    assert missing.status_code == 409
    assert 'profile' in missing.json()['detail'].lower()
    start = await client.post('/api/agent/start')
    assert start.status_code == 409
    saved = await client.put('/api/profile/', json=candidate)
    assert saved.status_code == 200
    assert json.loads(private_path.read_text())['identity']['email'] == 'candidate@example.com'
    loaded = await client.get('/api/profile/')
    assert loaded.json()['_configured'] is True
    assert loaded.json()['identity']['name'] == 'Example Candidate'


@pytest.mark.asyncio
async def test_profile_rejects_unsafe_links_and_invalid_email(client, candidate):
    unsafe = copy.deepcopy(candidate)
    unsafe['links']['github'] = 'javascript:alert(1)'
    assert (await client.put('/api/profile/', json=unsafe)).status_code == 422
    unsafe = copy.deepcopy(candidate)
    unsafe['identity']['email'] = 'not-an-email'
    assert (await client.put('/api/profile/', json=unsafe)).status_code == 422


@pytest.mark.asyncio
async def test_preferences_persist_without_unlocking_submission(client, tmp_path, monkeypatch):
    path = tmp_path / 'preferences.json'
    monkeypatch.setattr(settings, 'runtime_settings_path', str(path))
    monkeypatch.setattr(settings, 'min_match_score', settings.min_match_score)
    monkeypatch.setattr(settings, 'max_applications_per_day', settings.max_applications_per_day)
    monkeypatch.setattr(settings, 'ollama_model', settings.ollama_model)
    from ai.ollama_provider import get_llm_provider
    monkeypatch.setattr(get_llm_provider(), 'model', get_llm_provider().model)
    values = {'min_match_score':72,'max_applications_per_day':12,'ollama_model':'llama3.2'}
    assert (await client.put('/api/agent/settings', json=values)).status_code == 200
    assert json.loads(path.read_text()) == values
    result = (await client.get('/api/agent/settings')).json()
    assert result['min_match_score'] == 72
    assert result['dry_run'] is True and result['auto_submit'] is False
    assert (await client.put('/api/agent/settings', json={**values,'auto_submit':True})).status_code == 422
    assert (await client.put('/api/agent/settings', json={**values,'min_match_score':101})).status_code == 422


@pytest.mark.asyncio
async def test_master_creation_does_not_overwrite_a_reviewed_baseline(client, tmp_path, monkeypatch):
    baseline = tmp_path / 'master.tex'
    monkeypatch.setattr(resume_api, 'MASTER_TEX_PATH', baseline)
    response = await client.post('/api/resume/master')
    assert response.status_code == 200
    source = baseline.read_text()
    assert 'Example Candidate' in source
    assert (await client.post('/api/resume/master')).status_code == 409
    assert baseline.read_text() == source
    monkeypatch.setattr(resume_api, 'is_latex_compiler_available', lambda:(False,'none',None))
    status = await client.get('/api/resume/master')
    assert status.status_code == 200
    assert status.json()['latex_compiler_available'] is False


@pytest.mark.asyncio
async def test_download_does_not_expose_secrets_or_outside_files(client, tmp_path, monkeypatch):
    generated = tmp_path / 'generated'
    generated.mkdir()
    monkeypatch.setattr(resume_api, 'GENERATED_DIR', generated)
    allowed = generated / 'resume.tex'
    allowed.write_text('Reviewed source')
    secret = generated / '.env'
    secret.write_text('PRIVATE_TEST_VALUE')
    outside = tmp_path / 'outside.tex'
    outside.write_text('Outside allowed roots')
    assert (await client.get('/api/resume/download', params={'path':str(allowed)})).text == 'Reviewed source'
    assert (await client.get('/api/resume/download', params={'path':str(secret)})).status_code == 403
    assert (await client.get('/api/resume/download', params={'path':str(outside)})).status_code == 403
    assert (await client.get('/api/not-a-real-endpoint')).status_code == 404
    assert (await client.get('/%2e%2e/.env')).status_code == 404


def test_missing_compiler_does_not_claim_one_page(tmp_path, monkeypatch, candidate):
    monkeypatch.setattr(validator, 'is_latex_compiler_available', lambda:(False,'none',None))
    _, registry = matcher.load_candidate_data()
    plan = ResumeTailor(candidate, registry)._deterministic_tailor({}, [])
    result = validator.ResumeCompilerValidator.generate_and_enforce_one_page(candidate, plan, tmp_path)
    assert Path(result['latex_path']).exists()
    assert result['pdf_path'] is None
    assert result['page_count'] is None
    assert result['is_one_page'] is False
    assert result['is_compiled'] is False


def test_blank_pdf_cannot_be_marked_ready(tmp_path, monkeypatch, candidate):
    pdf = tmp_path / 'blank.pdf'
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612,height=792)
    with pdf.open('wb') as handle:
        writer.write(handle)
    monkeypatch.setattr(validator,'is_latex_compiler_available',lambda:(True,'pdflatex','/test/compiler'))
    monkeypatch.setattr(validator.ResumeCompilerValidator,'compile_latex',classmethod(lambda cls,*args,**kwargs:{'success':True,'is_compiled':True,'pdf_path':str(pdf)}))
    _,registry = matcher.load_candidate_data()
    plan = ResumeTailor(candidate,registry)._deterministic_tailor({},[])
    result = validator.ResumeCompilerValidator.generate_and_enforce_one_page(candidate,plan,tmp_path)
    assert result['pdf_valid'] is False
    assert result['pdf_path'] is None
    assert result['compile_error']


def test_failed_compile_cannot_reuse_stale_pdf(tmp_path, monkeypatch):
    source = tmp_path / 'resume.tex'
    source.write_text('broken source')
    stale = tmp_path / 'resume.pdf'
    stale.write_bytes(b'stale previously compiled file')
    monkeypatch.setattr(validator,'is_latex_compiler_available',lambda:(True,'pdflatex','/test/compiler'))
    monkeypatch.setattr(validator.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stdout='failed',stderr='bad source'))
    result = validator.ResumeCompilerValidator.compile_latex(source,tmp_path)
    assert result['success'] is False
    assert result['pdf_path'] is None
    assert not stale.exists()


def test_unverified_projects_and_bullets_never_enter_resume(candidate):
    registry = {'projects':[
        {'id':'exposure-only','status':'exposure','bullets':[{'text':'Unverified experience','verified':True}]},
        {'id':'verified-project','status':'verified','bullets':[{'text':'Real evidence','verified':True},{'text':'Invented claim','verified':False}]},
        {'id':'rock-paper-scissor','status':'verified','bullets':[{'text':'Blacklisted','verified':True}]},
    ]}
    plan = ResumeTailor(candidate,registry)._deterministic_tailor({},[])
    assert [p['id'] for p in plan['selected_projects']] == ['verified-project']
    assert plan['selected_projects'][0]['bullets'] == ['Real evidence']


def test_renderer_does_not_invent_missing_candidate_facts():
    from resume.renderer import LaTeXResumeRenderer
    source = LaTeXResumeRenderer.render({'identity':{'name':'Example Candidate','email':'candidate@example.com'}}, {'selected_projects':[], 'skills':{}, 'certifications':[]})
    assert 'Swopnab Bikram Karki' not in source
    assert 'University of Texas' not in source
    assert 'Fall 2027' not in source
    assert r'\section{Certifications}' not in source


@pytest.mark.asyncio
async def test_recompile_rejects_pdf_without_selectable_text(tmp_path, monkeypatch):
    from database.connection import AsyncSessionLocal
    from database.models import Application, ApplicationStatus
    from backend.api.applications import recompile_tailored_resume, get_artifact_dir
    async with AsyncSessionLocal() as session:
        application = Application(company='Example PDF Check', job_title='Software Intern', job_url='https://example.com/pdf-check', status=ApplicationStatus.RESUME_COMPILE_ERROR)
        session.add(application)
        await session.commit()
        directory = get_artifact_dir(application.id, application.company, application.job_title)
        directory.mkdir(parents=True,exist_ok=True)
        (directory/'resume.tex').write_text('Test source')
        pdf = directory/'resume.pdf'
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=612,height=792)
        with pdf.open('wb') as handle:
            writer.write(handle)
        monkeypatch.setattr(validator.ResumeCompilerValidator,'compile_latex',classmethod(lambda cls,*args,**kwargs:{'success':True,'pdf_path':str(pdf)}))
        response = await recompile_tailored_resume(application.id,session)
        assert response['success'] is False
        assert application.status == ApplicationStatus.RESUME_COMPILE_ERROR
        assert application.resume_path is None
        assert application.resume_compiler_error


def test_installed_compiler_produces_valid_one_page_resume(tmp_path, candidate):
    if not validator.is_latex_compiler_available()[0]:
        pytest.skip('TeX is optional locally; CI installs it for this integration check.')
    _,registry = matcher.load_candidate_data()
    plan = ResumeTailor(candidate,registry)._deterministic_tailor({},[])
    result = validator.ResumeCompilerValidator.generate_and_enforce_one_page(candidate,plan,tmp_path)
    assert result.get('pdf_valid') is True, result
    assert result['is_one_page'] is True
    assert result['selectable_text'] is True
    assert validator.ResumeCompilerValidator.validate_pdf(Path(result['pdf_path']))['valid'] is True


def test_archive_pdf_already_in_application_directory():
    from backend.services.artifact_store import ArtifactStore, get_artifact_dir, compute_sha256
    directory = get_artifact_dir(987654,'Example Archive Check','Software Intern')
    pdf = directory/'resume.pdf'
    pdf.write_bytes(b'fictional artifact content for the copy regression')
    digest = compute_sha256(pdf)
    result = ArtifactStore.save_resume(987654,'Example Archive Check','Software Intern',latex_source='Final reduced source',pdf_source_path=pdf)
    assert result['resume_hash'] == digest
    assert Path(result['pdf_path']).read_bytes() == b'fictional artifact content for the copy regression'
    assert Path(result['tex_path']).read_text() == 'Final reduced source'
