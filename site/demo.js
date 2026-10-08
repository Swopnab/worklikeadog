'use strict';
// This public sandbox performs keyword matching only. It never calls the local API.
const STORAGE_KEY = 'worklikeadog.demo.v1';
const STATUSES = {exploring:'To explore', preparing:'Preparing', review:'In review', applied:'Applied'};
const VOCABULARY = ['Python','JavaScript','TypeScript','Java','C++','SQL','HTML','CSS','React','Django','Flask','FastAPI','Node.js','Git','Docker','AWS','Azure','Kubernetes','PostgreSQL','MongoDB','REST','GraphQL','Linux','testing','machine learning','communication','teamwork'];
const DEFAULT_SKILLS = ['Python','JavaScript','TypeScript','SQL','HTML','CSS','React','Flask','Git','REST','communication','teamwork'];
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function sampleJobs() {
  return [
    {id:'sample-northstar',company:'Northstar',title:'Software Engineer Intern',location:'Remote',status:'exploring',description:'Join a small product team building web tools. We are looking for Python, JavaScript, SQL, Git, communication, and teamwork. Work with mentors on REST services and thoughtful testing.',notes:'Read more about the engineering team before applying.'},
    {id:'sample-fieldwork',company:'Fieldwork',title:'Frontend Developer',location:'Austin · Hybrid',status:'review',description:'Build accessible interfaces with React, TypeScript, HTML, and CSS. Use Git to collaborate and REST APIs to connect the product. Communication matters as much as clean code.',notes:'Review the project bullets and check the résumé layout.'},
    {id:'sample-orbit',company:'Orbit Systems',title:'Backend Engineer Intern',location:'Remote',status:'preparing',description:'Help build reliable backend services in Python and FastAPI. Work with SQL, PostgreSQL, Docker, AWS, testing, and Git.',notes:'Refresh SQL joins and prepare questions about the team.'},
    {id:'sample-canopy',company:'Canopy Labs',title:'Full Stack Intern',location:'Chicago · On-site',status:'exploring',description:'Create features using JavaScript, React, Node.js, and MongoDB. Share progress using Git. Bring strong communication and teamwork.',notes:''},
  ].map(job => ({...job,createdAt:'2026-01-15T12:00:00.000Z'}));
}
function freshState() { return {version:1,skills:[...DEFAULT_SKILLS],jobs:sampleJobs()}; }
function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (!saved || saved.version !== 1 || !Array.isArray(saved.jobs) || !Array.isArray(saved.skills)) return freshState();
    const skills = saved.skills.filter(s => typeof s === 'string' && VOCABULARY.includes(s));
    const jobs = saved.jobs.filter(j => j && typeof j.id === 'string' && typeof j.title === 'string' && typeof j.company === 'string' && typeof j.description === 'string' && Object.hasOwn(STATUSES,j.status)).slice(0,500).map(j => ({id:j.id.slice(0,100),company:j.company.slice(0,100),title:j.title.slice(0,150),location:String(j.location ?? '').slice(0,120),status:j.status,description:j.description.slice(0,15000),notes:String(j.notes ?? '').slice(0,5000),createdAt:j.createdAt || new Date().toISOString()}));
    return {version:1,skills,jobs};
  } catch { return freshState(); }
}
let state = loadState();
let view = 'list';
let currentId = null;
let lastMatch = null;
let confirmAction = null;
let toastTimer;
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>{$('toast').hidden=true;},3500); }
function save() {
  try { localStorage.setItem(STORAGE_KEY,JSON.stringify(state)); $('save-indicator').textContent='SAVED IN THIS BROWSER'; }
  catch { $('save-indicator').textContent='THIS SESSION ONLY'; toast('Browser storage is unavailable. Export your workspace to keep a copy.'); }
}
function detectSkills(text) {
  return VOCABULARY.filter(skill => {
    const escaped=skill.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
    return new RegExp('(^|[^a-z0-9])'+escaped+'(?=$|[^a-z0-9])','i').test(text);
  });
}
function analyze(description) {
  const required=detectSkills(description);
  const matched=required.filter(s=>state.skills.includes(s));
  return {required,matched,missing:required.filter(s=>!state.skills.includes(s)),score:required.length ? Math.round(matched.length/required.length*100) : null};
}
function scoreLabel(score) { return score===null ? 'No keywords' : `${score}%`; }
function companyColor(company) { return ['lavender','peach','blue','mint'][[...company].reduce((sum,c)=>sum+c.charCodeAt(0),0)%4]; }
function companyIcon(job) { return `<span class="company-icon ${companyColor(job.company)}" aria-hidden="true">${esc(job.company.slice(0,1).toUpperCase())}</span>`; }
function statusTag(status) { return `<span class="tag ${{exploring:'green',preparing:'neutral',review:'amber',applied:'purple'}[status]}">${STATUSES[status]}</span>`; }
function render() {
  const scores=state.jobs.map(j=>analyze(j.description).score);
  $('metric-total').textContent=String(state.jobs.length).padStart(2,'0');
  $('metric-fit').textContent=String(scores.filter(s=>s!==null&&s>=75).length).padStart(2,'0');
  $('metric-review').textContent=String(state.jobs.filter(j=>j.status==='review').length).padStart(2,'0');
  $('metric-applied').textContent=String(state.jobs.filter(j=>j.status==='applied').length).padStart(2,'0');
  const query=$('search').value.toLowerCase().trim(),status=$('status-filter').value;
  const jobs=state.jobs.filter(j=>(status==='all'||j.status===status)&&`${j.title} ${j.company} ${j.location}`.toLowerCase().includes(query));
  $('results-count').textContent=`Showing ${jobs.length} of ${state.jobs.length} opportunities`;
  if (!jobs.length) {
    $('jobs-container').innerHTML=`<div class="empty-state"><h2>${state.jobs.length ? 'No matches this time.' : 'Make room for possibility.'}</h2><p>${state.jobs.length ? 'Try a different search or stage.' : 'Add an opportunity to start your shortlist.'}</p><button class="button outline small" data-action="${state.jobs.length?'clear':'add'}">${state.jobs.length?'Clear filters':'Add your first opportunity'}</button></div>`;
  } else if (view==='board') {
    $('jobs-container').innerHTML=`<div class="board">${Object.entries(STATUSES).map(([key,label])=>{const stage=jobs.filter(j=>j.status===key);return `<section class="board-column"><h2>${label}<span>${stage.length}</span></h2>${stage.map(j=>`<button class="board-card" data-job="${esc(j.id)}" aria-label="Review ${esc(j.title)} at ${esc(j.company)}">${companyIcon(j)}<strong>${esc(j.title)}</strong><p>${esc(j.company)} · ${esc(j.location||'Location unspecified')}</p><span class="tag green">${scoreLabel(analyze(j.description).score)} keyword fit</span></button>`).join('')}</section>`;}).join('')}</div>`;
  } else {
    $('jobs-container').innerHTML=`<div class="jobs-table-wrap"><table class="jobs-table"><caption class="sr-only">Your demo opportunities. Keyword fit is illustrative, not a hiring prediction.</caption><thead><tr><th scope="col">OPPORTUNITY</th><th scope="col">LOCATION</th><th scope="col">KEYWORD FIT</th><th scope="col">STAGE</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead><tbody>${jobs.map(j=>{const score=analyze(j.description).score;return `<tr><td><div class="job-cell">${companyIcon(j)}<div><button class="job-title" data-job="${esc(j.id)}">${esc(j.title)}</button><p>${esc(j.company)}</p></div></div></td><td>${esc(j.location||'Unspecified')}</td><td><div class="fit-cell"><span class="fit-bar" aria-hidden="true"><span style="width:${score??0}%"></span></span>${scoreLabel(score)}</div></td><td>${statusTag(j.status)}</td><td><button class="table-action" data-job="${esc(j.id)}" aria-label="Review ${esc(j.title)} at ${esc(j.company)}">Review ↗</button></td></tr>`;}).join('')}</tbody></table></div>`;
  }
}
function navigate(page) {
  if (!['opportunities','match','profile'].includes(page)) page='opportunities';
  for (const name of ['opportunities','match','profile']) $(`page-${name}`).hidden=name!==page;
  document.querySelectorAll('[data-page]').forEach(button=>{const active=button.dataset.page===page;button.classList.toggle('active',active);if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
  history.replaceState(null,'',`#${page}`);
  document.title=`${{opportunities:'Your workspace',match:'Match lab',profile:'Sample profile'}[page]} — WorkLikeADog demo`;
  if(page==='profile') renderProfile();
  if(page==='match' && lastMatch) renderMatch();
}
function renderProfile() {
  $('sample-skills').value=state.skills.join(', ');
  const categories={Languages:['Python','JavaScript','TypeScript','Java','C++','SQL','HTML','CSS'],Frameworks:['React','Django','Flask','FastAPI','Node.js'],Tools:VOCABULARY.filter(s=>!['Python','JavaScript','TypeScript','Java','C++','SQL','HTML','CSS','React','Django','Flask','FastAPI','Node.js'].includes(s))};
  $('profile-skills').innerHTML=Object.entries(categories).map(([cat,skills])=>`<div><h3>${cat.toUpperCase()}</h3><div class="chips">${skills.filter(s=>state.skills.includes(s)).map(s=>`<span class="chip">${esc(s)}</span>`).join('')||'<span class="small-note">None selected</span>'}</div></div>`).join('');
}
function openAdd(prefill=null) {
  $('job-form').reset();
  if(prefill) for (const key of ['title','company','description']) $('job-form').elements[key].value=prefill[key]||'';
  $('job-dialog').showModal();
}
function openDetail(id) {
  const job=state.jobs.find(j=>j.id===id);if(!job)return;
  currentId=id;
  $('detail-company').textContent=job.company;
  $('detail-title').textContent=job.title;
  $('detail-location').textContent=job.location||'Location unspecified';
  $('detail-fit').textContent=`${scoreLabel(analyze(job.description).score)} keyword fit`;
  $('detail-description').textContent=job.description;
  $('detail-status').value=job.status;
  $('detail-notes').value=job.notes;
  $('detail-dialog').showModal();
}
function renderMatch() {
  const match=analyze(lastMatch.description);$('match-results').hidden=false;
  $('match-results').innerHTML=`<div class="match-score">${match.score===null?'—':match.score+'%'} <small>keyword overlap</small></div><h3>Matches in your sample profile</h3><div class="chips">${match.matched.map(s=>`<span class="chip">✓ ${esc(s)}</span>`).join('')||'<span class="small-note">No matching keywords found.</span>'}</div><h3>Skills to look at more closely</h3><div class="chips">${match.missing.map(s=>`<span class="chip missing">${esc(s)}</span>`).join('')||'<span class="small-note">No gaps among recognized keywords.</span>'}</div><p>${match.required.length ? `${match.matched.length} of ${match.required.length} recognized role skills appear in the sample profile. Review the description for requirements this preview cannot detect.` : 'This description has no recognized skill keywords. The preview cannot estimate a fit; review the description yourself.'}</p><div class="panel-actions"><button class="button outline small" id="save-match" type="button">Add to opportunities ↗</button></div>`;
  $('save-match').addEventListener('click',()=>openAdd(lastMatch));
}
function confirmDialog(title,copy,label,action) { $('confirm-title').textContent=title;$('confirm-copy').textContent=copy;$('confirm-action').textContent=label;confirmAction=action;$('confirm-dialog').showModal(); }
function download(name,content,type) { const url=URL.createObjectURL(new Blob([content],{type}));const link=document.createElement('a');link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Workspace exported.'); }
function csvCell(value) { const text=String(value??'');return '"'+( /^[=+@\-\t\r]/.test(text)?"'":'' )+text.replace(/"/g,'""')+'"'; }
document.querySelectorAll('[data-page]').forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.page)));
document.querySelectorAll('[data-close]').forEach(button=>button.addEventListener('click',()=>$(button.dataset.close).close()));
$('add-job').addEventListener('click',()=>openAdd());
$('search').addEventListener('input',render);$('status-filter').addEventListener('change',render);
for(const mode of ['list','board']) $(`${mode}-view`).addEventListener('click',()=>{view=mode;for(const m of ['list','board']){ $(`${m}-view`).classList.toggle('active',m===mode);$(`${m}-view`).setAttribute('aria-pressed',String(m===mode));}render();});
$('jobs-container').addEventListener('click',event=>{const button=event.target.closest('[data-job],[data-action]');if(!button)return;if(button.dataset.job)openDetail(button.dataset.job);else if(button.dataset.action==='add')openAdd();else{$('search').value='';$('status-filter').value='all';render();}});
$('job-form').addEventListener('submit',event=>{event.preventDefault();const data=new FormData(event.currentTarget);const title=String(data.get('title')).trim(),company=String(data.get('company')).trim(),description=String(data.get('description')).trim();if(!title||!company||!description){toast('Add a role, company, and description.');return;}if(state.jobs.length>=500){toast('Export or remove an opportunity before adding more.');return;}state.jobs.unshift({id:globalThis.crypto?.randomUUID?.()||`job-${Date.now()}-${Math.random().toString(36).slice(2)}`,title,company,description,location:String(data.get('location')).trim(),status:String(data.get('status')),notes:'',createdAt:new Date().toISOString()});save();$('job-dialog').close();$('search').value='';$('status-filter').value='all';navigate('opportunities');render();toast('A new opportunity, ready to explore.');});
$('detail-form').addEventListener('submit',event=>{event.preventDefault();const job=state.jobs.find(j=>j.id===currentId);if(!job)return;job.status=$('detail-status').value;job.notes=$('detail-notes').value;save();$('detail-dialog').close();render();toast('Your next step is saved.');});
$('delete-job').addEventListener('click',()=>confirmDialog('Remove this opportunity?','This removes the job and its notes from this browser workspace.','Remove opportunity',()=>{state.jobs=state.jobs.filter(j=>j.id!==currentId);$('detail-dialog').close();save();render();toast('Opportunity removed.');}));
$('reset-demo').addEventListener('click',()=>confirmDialog('Start fresh?','This replaces your demo jobs, notes, and sample skills with the original fictional workspace. Export first if you want to keep a copy.','Reset demo',()=>{state=freshState();lastMatch=null;$('match-results').hidden=true;$('search').value='';$('status-filter').value='all';save();render();renderProfile();toast('A fresh workspace, ready to explore.');}));
$('confirm-action').addEventListener('click',()=>{$('confirm-dialog').close();if(confirmAction)confirmAction();confirmAction=null;});
$('match-form').addEventListener('submit',event=>{event.preventDefault();lastMatch={title:$('match-title').value.trim(),company:$('match-company').value.trim(),description:$('match-description').value.trim()};if(!lastMatch.title||!lastMatch.company||!lastMatch.description){toast('Add a role, company, and description.');return;}renderMatch();});
$('use-example').addEventListener('click',()=>{const job=sampleJobs()[2];$('match-title').value=job.title;$('match-company').value=job.company;$('match-description').value=job.description;});
$('skills-form').addEventListener('submit',event=>{event.preventDefault();const entered=$('sample-skills').value.split(',').map(s=>s.trim()).filter(Boolean);const mapped=entered.map(s=>VOCABULARY.find(v=>v.toLowerCase()===s.toLowerCase()));if(mapped.some(s=>!s)){toast('Use the recognized skills listed below the field.');return;}if(!mapped.length){toast('Add at least one sample skill.');return;}state.skills=[...new Set(mapped)];save();render();renderProfile();if(lastMatch)renderMatch();toast('Sample skills updated. The keyword fits have changed.');});
$('export-json').addEventListener('click',()=>download('worklikeadog-workspace.json',JSON.stringify({...state,exportedAt:new Date().toISOString(),demo:true},null,2),'application/json'));
$('export-csv').addEventListener('click',()=>{const headers=['Company','Role','Location','Stage','Keyword fit','Description','Notes'];const rows=state.jobs.map(j=>[j.company,j.title,j.location,STATUSES[j.status],scoreLabel(analyze(j.description).score),j.description,j.notes]);download('worklikeadog-opportunities.csv',[headers,...rows].map(row=>row.map(csvCell).join(',')).join('\r\n'),'text/csv;charset=utf-8');});
render();renderProfile();navigate(location.hash.slice(1));
