'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
$('#explorer-toggle').onclick = () => {
  const collapsed = document.body.classList.toggle('explorer-collapsed');
  const button = $('#explorer-toggle');
  const label = `${collapsed ? 'Expand' : 'Collapse'} investigation explorer`;
  button.textContent = collapsed ? '›' : '‹';
  button.setAttribute('aria-expanded', String(!collapsed));
  button.setAttribute('aria-label', label);
  button.title = label;
};
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = value => value == null ? '—' : `${(value * 100).toFixed(1).replace(/\.0$/, '')}%`;
const delta = value => value == null ? 'Unknown' : `${value > 0 ? '+' : ''}${value.toFixed(1).replace(/\.0$/, '')} pp`;
const storageKey = 'chive.viewer.shortlist.v1';
let saved = [];
let storageAvailable = true;
try { saved = JSON.parse(localStorage.getItem(storageKey) || '[]'); if (!Array.isArray(saved)) saved = []; } catch { storageAvailable = false; }
const state = {datasets: [], dataset: '', items: [], current: null, experiment: null, tab: 'responses', headerCollapsed: true, readingOptionsOpen: false, conversationOpen: true, compare: true, raw: false, filter: 'all', responseSearch: '', positions: {baseline: 0, edited: 0}, shortlistOnly: false, request: 0, size: 16};
try { state.headerCollapsed = localStorage.getItem('chive.viewer.headerCollapsed') !== 'false'; } catch {}
// Preload a moving window of pages, including every rendered response.
const investigationsPerPage = 10;
state.page = 0;
state.loadingId = null;
let visibleInvestigations = [];
let preloadTargets = new Map();
let preloadQueue = [];
let preloadWorkers = 0;
let preloadTimer;
const preloadFailures = new Set();
const investigationCache = new Map();
const pendingInvestigations = new Map();
const investigationKey = (dataset, id) => JSON.stringify([dataset, id]);
function trimInvestigationCache() {
  for (const key of investigationCache.keys()) {
    if (!preloadTargets.has(key) && key !== investigationKey(state.dataset, state.current?.id) && key !== investigationKey(state.dataset, state.loadingId)) investigationCache.delete(key);
  }
}
function rememberInvestigation(key, item) {
  investigationCache.set(key, item);
  trimInvestigationCache();
}
function fetchInvestigation(dataset, id, key) {
  if (!pendingInvestigations.has(key)) {
    const pending = api('investigation', {dataset, id})
      .then(item => { rememberInvestigation(key, item); return item; })
      .finally(() => pendingInvestigations.delete(key));
    pendingInvestigations.set(key, pending);
  }
  return pendingInvestigations.get(key);
}
function updatePreloadStatus() {
  const ready = visibleInvestigations.filter(item => investigationCache.has(investigationKey(state.dataset, item.id))).length;
  const failed = visibleInvestigations.some(item => preloadFailures.has(investigationKey(state.dataset, item.id)));
  $('#preload-status').textContent = state.loadingId ? `Opening ${state.loadingId}…` : ready === visibleInvestigations.length ? '' : failed ? 'Some items will load when opened' : `Preparing responses · ${ready}/${visibleInvestigations.length}`;
  document.querySelectorAll('.investigation-card').forEach(button => button.classList.toggle('loading', button.dataset.id === state.loadingId));
}
function pumpPreloads() {
  while (preloadWorkers < 2 && preloadQueue.length) {
    const target = preloadQueue.shift();
    if (investigationCache.has(target.key) || pendingInvestigations.has(target.key) || preloadFailures.has(target.key)) continue;
    preloadWorkers++;
    fetchInvestigation(target.dataset, target.id, target.key)
      .catch(() => { if (preloadTargets.has(target.key)) preloadFailures.add(target.key); })
      .finally(() => { preloadWorkers--; updatePreloadStatus(); pumpPreloads(); });
  }
}
function planPreloads(items) {
  const targets = new Map();
  const add = item => {
    if (!item) return;
    const key = investigationKey(state.dataset, item.id);
    targets.set(key, {key, dataset: state.dataset, id: item.id});
  };
  // Current page first, then entry points two pages in either direction,
  // then the rest of the adjacent pages. Never fetch the whole dataset.
  visibleInvestigations.forEach(add);
  for (const offset of [1, -1, 2, -2]) add(items[(state.page + offset) * investigationsPerPage]);
  for (const offset of [1, -1]) {
    const start = (state.page + offset) * investigationsPerPage;
    if (start >= 0) items.slice(start, start + investigationsPerPage).forEach(add);
  }
  preloadTargets = targets;
  preloadQueue = [...targets.values()];
  trimInvestigationCache();
  updatePreloadStatus();
  clearTimeout(preloadTimer);
  preloadTimer = setTimeout(pumpPreloads, 100);
}
let noticeTimer;
function notice(message) { $('#notice').textContent = message; $('#notice').hidden = false; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => $('#notice').hidden = true, 5000); }
async function api(path, params = {}) {
  const response = await fetch(`/api/${path}?${new URLSearchParams(params)}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
function isSaved(id) { return saved.some(s => s.dataset === state.dataset && s.id === id); }
function setLocation() {
  const params = new URLSearchParams({dataset: state.dataset});
  if (state.current) params.set('id', state.current.id);
  if (state.current) params.set('experiment', state.experiment ? state.experiment.number : 'original');
  history.replaceState(null, '', `#${params}`);
}
function renderList() {
  const query = $('#search').value.toLowerCase().trim();
  let items = state.items.filter(item => (!state.shortlistOnly || isSaved(item.id)) && `${item.id} ${item.question} ${item.behavior} ${item.categories.join(' ')}`.toLowerCase().includes(query));
  $('#investigation-count').textContent = `${items.length} / ${state.items.length}`;
  $('#saved-count').textContent = saved.filter(s => s.dataset === state.dataset).length;
  $('#shortlist-filter').setAttribute('aria-pressed', state.shortlistOnly);
  const pages = Math.ceil(items.length / investigationsPerPage);
  state.page = Math.min(state.page, Math.max(0, pages - 1));
  visibleInvestigations = items.slice(state.page * investigationsPerPage, (state.page + 1) * investigationsPerPage);
  $('.investigation-pagination').hidden = !items.length;
  $('#page-label').textContent = `Page ${state.page + 1} of ${pages}`;
  $('#previous-page').disabled = state.page === 0;
  $('#next-page').disabled = state.page >= pages - 1;
  $('#investigation-list').innerHTML = items.length ? visibleInvestigations.map(item => `<button class="investigation-card ${state.current?.id === item.id ? 'active' : ''}" data-id="${escapeHTML(item.id)}" aria-current="${state.current?.id === item.id ? 'true' : 'false'}"><span class="card-top"><span>${escapeHTML(item.id)}</span><span>${isSaved(item.id) ? '★' : ''}</span></span><span class="card-question">${escapeHTML(item.question)}</span><span class="card-bottom"><span>${item.experiment_count} edits</span><span>${item.claim_count} eval claims</span><span>up to ${item.max_effect == null ? '—' : Math.round(item.max_effect) + ' pp'}</span></span></button>`).join('') : '<p class="empty">No investigations match. Try a different search or turn off the shortlist filter.</p>';
  $('#investigation-list').querySelectorAll('[data-id]').forEach(button => button.addEventListener('click', () => loadInvestigation(button.dataset.id)));
  planPreloads(items);
}
async function loadDataset(id, promptId, experimentNumber) {
  const request = ++state.request;
  state.dataset = id; state.current = null; state.items = []; state.experiment = null; state.page = 0; state.loadingId = null; preloadFailures.clear();
  $('#dataset').value = id; $('#search').value = ''; renderList();
  $('#workspace').innerHTML = '<p class="empty" role="status">Loading investigations…</p>';
  try {
    const items = await api('investigations', {dataset: id});
    if (request !== state.request) return;
    state.items = items;
    state.page = Math.floor(Math.max(0, items.findIndex(item => item.id === promptId)) / investigationsPerPage);
    renderList();
    if (items.length) await loadInvestigation(items.some(i => i.id === promptId) ? promptId : items[0].id, experimentNumber, false);
    else $('#workspace').innerHTML = '<p class="empty">This dataset contains no investigations.</p>';
  } catch (error) { if (request === state.request) showError(error); }
}
function showError(error) { $('#workspace').innerHTML = `<div class="welcome error"><h2>Couldn’t load the data</h2><p>${escapeHTML(error.message)}</p><button id="retry">Try again</button></div>`; $('#retry').onclick = () => location.reload(); }
async function loadInvestigation(id, experimentNumber, reveal = true) {
  const request = ++state.request;
  const dataset = state.dataset;
  const key = investigationKey(dataset, id);
  const cached = investigationCache.get(key);
  state.loadingId = cached ? null : id;
  preloadFailures.delete(key);
  updatePreloadStatus();
  $('#workspace').setAttribute('aria-busy', String(!cached));
  if (!cached && !state.current) $('#workspace').innerHTML = '<p class="empty" role="status">Loading responses…</p>';
  if (reveal) document.body.classList.add('detail-open');
  try {
    const item = cached || await fetchInvestigation(dataset, id, key);
    if (request !== state.request) return;
    rememberInvestigation(key, item);
    if (state.current?.id !== item.id) state.conversationOpen = true;
    state.current = item;
    state.loadingId = null;
    state.experiment = experimentNumber == null || experimentNumber === 'original'
      ? null
      : (item.experiments.find(e => String(e.number) === String(experimentNumber)) || null);
    if (!state.experiment) state.tab = 'responses';
    state.positions = {baseline: 0, edited: 0}; state.responseSearch = ''; state.filter = 'all';
    setLocation(); renderList(); renderWorkspace(); $('#workspace').scrollTop = 0;
  } catch (error) {
    if (request === state.request) {
      state.loadingId = null;
      preloadFailures.add(key);
      if (state.current) notice(`Couldn’t open ${id}: ${error.message}. Click it to retry.`);
      else showError(error);
    }
  } finally {
    if (request === state.request) { $('#workspace').setAttribute('aria-busy', 'false'); updatePreloadStatus(); }
  }
}
function renderWorkspace() {
  const item = state.current;
  $('#workspace').innerHTML = `<section class="investigation-heading ${state.headerCollapsed ? 'header-collapsed' : ''}"><button class="mobile-back">← Investigations</button><div class="heading-top"><div class="metadata"><span class="id">${escapeHTML(item.id)}</span>${item.verification == null ? '' : `<span>Verification ${item.verification}/10</span>`}<span>${item.claim_count} eval claims</span></div><span class="heading-preview" title="${escapeHTML(item.question)}" ${state.headerCollapsed ? '' : 'hidden'}>${escapeHTML(item.question)}</span><div class="heading-actions"><button id="header-toggle" aria-controls="investigation-header-details" aria-expanded="${!state.headerCollapsed}">${state.headerCollapsed ? 'Show details ▾' : 'Hide details ▴'}</button><button id="save" class="save-button" aria-pressed="${isSaved(item.id)}">${isSaved(item.id) ? '★ Shortlisted' : '☆ Shortlist'}</button></div></div><div id="investigation-header-details" ${state.headerCollapsed ? 'hidden' : ''}><h2>${escapeHTML(item.question)}</h2><div class="classifier"><strong>Behavior being measured</strong>${escapeHTML(item.classifier || 'No grading question recorded.')}</div><details class="heading-details"><summary>Behavior summary & categories</summary><p>${escapeHTML(item.behavior)}</p><div class="tags">${item.categories.map(c => `<span class="tag">${escapeHTML(c.replaceAll('_',' '))}</span>`).join('')}</div></details></div></section><div class="evidence-layout"><aside class="experiment-sidebar" aria-label="Counterfactuals"><div class="section-label">COUNTERFACTUALS <span>${item.experiments.length}</span></div><div class="experiment-list"></div></aside><section class="reader-workspace" aria-label="Counterfactual reader"></section></div>`;
  $('.mobile-back').onclick = () => document.body.classList.remove('detail-open');
  $('#header-toggle').onclick = () => {
    state.headerCollapsed = !state.headerCollapsed;
    $('.investigation-heading').classList.toggle('header-collapsed', state.headerCollapsed);
    $('#investigation-header-details').hidden = state.headerCollapsed;
    $('.heading-preview').hidden = !state.headerCollapsed;
    $('#header-toggle').setAttribute('aria-expanded', String(!state.headerCollapsed));
    $('#header-toggle').textContent = state.headerCollapsed ? 'Show details ▾' : 'Hide details ▴';
    try { localStorage.setItem('chive.viewer.headerCollapsed', String(state.headerCollapsed)); } catch {}
  };
  $('#save').onclick = () => {
    if (isSaved(item.id)) saved = saved.filter(s => !(s.dataset === state.dataset && s.id === item.id));
    else saved.push({dataset: state.dataset, id: item.id, question: item.question, saved_at: new Date().toISOString()});
    try { localStorage.setItem(storageKey, JSON.stringify(saved)); } catch { storageAvailable = false; }
    if (!storageAvailable) notice('Browser storage is unavailable. Shortlist changes will only last until this page closes.');
    $('#save').textContent = isSaved(item.id) ? '★ Shortlisted' : '☆ Shortlist'; $('#save').setAttribute('aria-pressed', isSaved(item.id)); renderList();
  };
  renderExperiments(); renderReader();
}
function renderExperiments() {
  const baseline = state.current.baseline;
  const originalCard = `<button class="experiment-card ${!state.experiment ? 'active' : ''}" data-number="original" aria-current="${!state.experiment ? 'true' : 'false'}"><span class="exp-top">ORIGINAL</span><span class="exp-summary">Unedited prompt & responses</span><span class="exp-bottom"><span>${pct(baseline.rate)} behavior rate</span><span>${baseline.responses.length} responses</span></span></button>`;
  $('.experiment-list').innerHTML = originalCard + state.current.experiments.map(e => `<button class="experiment-card ${state.experiment?.number === e.number ? 'active' : ''}" data-number="${e.number}" aria-current="${state.experiment?.number === e.number ? 'true' : 'false'}"><span class="exp-top"><span>EDIT ${String(e.number).padStart(2,'0')}</span>${e.claims.length ? '<span class="badge">Eval</span>' : ''}</span><span class="exp-summary">${escapeHTML(e.summary)}</span><span class="exp-bottom"><span>${pct(state.current.baseline.rate)} → ${pct(e.rate)}</span><span class="delta">${delta(e.delta)}</span></span></button>`).join('');
  $('.experiment-list').querySelectorAll('[data-number]').forEach(button => button.onclick = () => {
    state.experiment = button.dataset.number === 'original' ? null : state.current.experiments.find(e => String(e.number) === button.dataset.number);
    if (!state.experiment) state.tab = 'responses';
    state.positions.edited = 0; setLocation(); renderExperiments(); renderReader();
  });
}
function statisticsMarkup(baseline, exp) {
  return `<div class="stats"><div class="stat"><span class="stat-label">Original behavior rate</span><span class="stat-value">${pct(baseline.rate)}</span><span class="stat-detail">${baseline.yes ?? '?'}/${baseline.n} responses</span></div><div class="stat"><span class="stat-label">After prompt edit</span><span class="stat-value">${pct(exp.rate)}</span><span class="stat-detail">${exp.yes ?? '?'}/${exp.n} responses</span></div><div class="stat delta-stat"><span class="stat-label">Change in behavior</span><span class="stat-value">${delta(exp.delta)}</span><span class="stat-detail">edited − original</span></div></div>`;
}
function renderReader() {
  const exp = state.experiment, baseline = state.current.baseline;
  $('.reader-workspace').classList.toggle('original-reader', !exp);
  if (!exp) {
    $('.reader-workspace').innerHTML = `<div class="original-toolbar"><h3>Original</h3><details class="measurement-details"><summary>Behavior statistics</summary><div class="stats original-stats"><div class="stat"><span class="stat-label">Original behavior rate</span><span class="stat-value">${pct(baseline.rate)}</span><span class="stat-detail">${baseline.yes ?? '?'}/${baseline.n} responses</span></div></div></details></div>${baseline.warnings.map(w => `<p class="warning">${escapeHTML(w)}</p>`).join('')}<div id="evidence-panel" role="region" aria-label="Original responses"></div>`;
    renderResponseView();
    return;
  }
  $('.reader-workspace').innerHTML = `<p class="experiment-description">${escapeHTML(exp.summary)}</p>${[...baseline.warnings,...exp.warnings].map(w => `<p class="warning">${escapeHTML(w)}</p>`).join('')}<div class="tabs" role="tablist" aria-label="Evidence views"><button role="tab" id="tab-responses" data-tab="responses" aria-controls="evidence-panel" aria-selected="${state.tab === 'responses'}">Responses</button><button role="tab" id="tab-prompts" data-tab="prompts" aria-controls="evidence-panel" aria-selected="${state.tab === 'prompts'}">Prompt edit</button><button role="tab" id="tab-claims" data-tab="claims" aria-controls="evidence-panel" aria-selected="${state.tab === 'claims'}">Eval claims (${exp.claims.length})</button><button role="tab" id="tab-statistics" data-tab="statistics" aria-controls="evidence-panel" aria-selected="${state.tab === 'statistics'}">Statistics</button></div><div id="evidence-panel" role="tabpanel" aria-labelledby="tab-${state.tab}"></div><details class="explanation"><summary>Investigator’s explanation · generated interpretation</summary><div class="prose">${state.current.explanation_html || '<p>No explanation recorded.</p>'}</div>${state.current.commentary ? `<p>${escapeHTML(state.current.commentary)}</p>` : ''}</details>`;
  $('.tabs').querySelectorAll('[data-tab]').forEach(button => button.onclick = () => { state.tab = button.dataset.tab; renderReader(); $(`#tab-${state.tab}`).focus(); });
  if (state.tab === 'responses') renderResponseView();
  else if (state.tab === 'prompts') renderPromptView();
  else if (state.tab === 'statistics') $('#evidence-panel').innerHTML = statisticsMarkup(baseline, exp);
  else renderClaims();
}
function renderResponseView() {
  const originalOnly = !state.experiment;
  $('#evidence-panel').innerHTML = `<div class="reader-controls">${originalOnly ? '' : `<label><input id="compare" type="checkbox" ${state.compare ? 'checked' : ''}> Compare original</label>`}<details id="reading-options" class="reading-options" ${state.readingOptionsOpen ? 'open' : ''}><summary>Reading options</summary><div class="response-toolbar"><select id="verdict-filter" aria-label="Filter by grader verdict"><option value="all">All verdicts</option><option value="yes">Behavior present</option><option value="no">Behavior absent</option><option value="unknown">Not graded</option></select><input id="response-search" type="search" placeholder="Find text in responses…" aria-label="Find text in responses" value="${escapeHTML(state.responseSearch)}"><button class="size-button" id="smaller" aria-label="Decrease text size">A−</button><button class="size-button" id="larger" aria-label="Increase text size">A+</button><button id="raw" aria-pressed="${state.raw}">Raw text</button></div><p class="reading-note">Grader labels use the question above.${originalOnly ? '' : ' Original and edited responses are independent samples, not matched pairs.'}</p></details></div><div class="response-columns ${originalOnly || !state.compare ? 'single' : ''}">${originalOnly || state.compare ? '<section id="baseline-pane" class="response-pane" aria-label="Original responses"></section>' : ''}${originalOnly ? '' : '<section id="edited-pane" class="response-pane" aria-label="Edited responses"></section>'}</div>`;
  if (originalOnly) {
    const toolbar = $('.original-toolbar');
    toolbar.append($('#reading-options'));
    $('#baseline-pane').append(toolbar);
    $('.reader-controls').remove();
  }
  $('#reading-options').ontoggle = e => { state.readingOptionsOpen = e.target.open; };
  $('#verdict-filter').value = state.filter;
  if (!originalOnly) $('#compare').onchange = e => { state.compare = e.target.checked; renderResponseView(); };
  $('#verdict-filter').onchange = e => { state.filter = e.target.value; state.positions = {baseline:0,edited:0}; renderPanes(); };
  $('#response-search').oninput = e => { state.responseSearch = e.target.value; state.positions = {baseline:0,edited:0}; renderPanes(); };
  $('#raw').onclick = () => { state.raw = !state.raw; $('#raw').setAttribute('aria-pressed', state.raw); renderPanes(); };
  $('#smaller').onclick = () => { state.size = Math.max(12,state.size-1); resizeText(); };
  $('#larger').onclick = () => { state.size = Math.min(24,state.size+1); resizeText(); };
  renderPanes(); resizeText();
}
function resizeText() {
  // A stylesheet rule keeps font controls compatible with the strict CSP.
  let sheet = document.styleSheets[0];
  if (state.fontRule != null) sheet.deleteRule(state.fontRule);
  state.fontRule = sheet.cssRules.length;
  sheet.insertRule(`:root { --reader-size: ${state.size}px; }`, state.fontRule);
  $('#smaller').disabled = state.size <= 12; $('#larger').disabled = state.size >= 24;
}
function renderPanes() {
  if (!state.experiment || state.compare) renderPane('baseline', state.current.baseline);
  if (state.experiment) renderPane('edited', state.experiment);
  const active = [];
  if (state.filter !== 'all' || state.responseSearch) active.push('filtered');
  if (state.raw) active.push('raw text');
  $('#reading-options summary').textContent = 'Reading options' + (active.length ? ` · ${active.join(', ')}` : '');
}
function renderPane(name, condition) {
  const pane = $(`#${name}-pane`);
  const originalOnly = !state.experiment;
  // Keep the Original controls mounted while paging/filtering responses.
  let content = pane;
  if (originalOnly) {
    content = $('.response-body', pane);
    if (!content) {
      content = document.createElement('div');
      content.className = 'response-body';
      pane.append(content);
    }
  }
  const historyOpen = state.conversationOpen;
  const scrollTop = $('.response-content', pane)?.scrollTop ?? 0;
  const history = `<details class="conversation-history" ${historyOpen ? 'open' : ''}><summary>Prompt & conversation · ${condition.messages.length} message${condition.messages.length === 1 ? '' : 's'}</summary>${condition.messages.map(message => `<section class="conversation-turn"><div class="conversation-role">${escapeHTML(message.role)}</div><div class="conversation-text">${escapeHTML(message.content)}</div></section>`).join('')}</details>`;
  const query = state.responseSearch.toLowerCase();
  const responses = condition.responses.filter(r => (state.filter === 'all' || (state.filter === 'yes' && r.verdict === true) || (state.filter === 'no' && r.verdict === false) || (state.filter === 'unknown' && r.verdict == null)) && r.text.toLowerCase().includes(query));
  state.positions[name] = Math.min(state.positions[name], Math.max(0,responses.length - 1));
  const position = state.positions[name], response = responses[position];
  content.innerHTML = `${originalOnly ? '' : `<div class="pane-title ${name === 'edited' ? 'edited' : ''}"><span>${name === 'baseline' ? 'Original prompt' : 'Edited prompt'}</span><span class="muted">${responses.length} / ${condition.responses.length} shown</span></div>`}${response ? `<div class="pager"><button data-step="-1" aria-label="Previous ${name} response" ${position === 0 ? 'disabled' : ''}>←</button><select aria-label="Select ${name} response">${responses.map((r,i) => `<option value="${i}" ${i === position ? 'selected' : ''}>Response ${r.index+1}</option>`).join('')}</select><button data-step="1" aria-label="Next ${name} response" ${position === responses.length-1 ? 'disabled' : ''}>→</button><span class="verdict ${response.verdict === false ? 'no' : response.verdict == null ? 'unknown' : ''}">${response.verdict === true ? 'Behavior present' : response.verdict === false ? 'Behavior absent' : 'Not graded'}</span></div><article class="response-content" tabindex="0" aria-label="${name} conversation and response ${response.index+1}">${history}<div class="conversation-role sampled-role">Assistant · sampled response</div><div class="${state.raw ? 'raw' : 'prose'}">${state.raw ? escapeHTML(response.text) : response.html}</div></article><div class="pane-footer"><span>Sample ${response.index+1} · ${response.text.length.toLocaleString()} characters</span><button data-copy>Copy response</button></div>` : '<p class="empty">No responses match these filters.</p>'}`;
  if (originalOnly) {
    let count = $('.original-count', pane);
    if (!count) {
      count = document.createElement('span');
      count.className = 'original-count muted';
      $('.original-toolbar h3', pane).after(count);
    }
    count.textContent = `${responses.length} / ${condition.responses.length} shown`;
  }
  if (!response) return;
  const conversation = $('.conversation-history', pane);
  conversation.ontoggle = () => {
    if (!conversation.isConnected || conversation.open === state.conversationOpen) return;
    state.conversationOpen = conversation.open;
    document.querySelectorAll('.conversation-history').forEach(details => {
      details.open = state.conversationOpen;
    });
  };
  $('.response-content', pane).scrollTop = scrollTop;
  pane.querySelectorAll('[data-step]').forEach(button => button.onclick = () => { state.positions[name] += Number(button.dataset.step); renderPane(name, condition); });
  $('.pager select',pane).onchange = e => { state.positions[name] = Number(e.target.value); renderPane(name, condition); };
  $('[data-copy]',pane).onclick = async () => { try { await navigator.clipboard.writeText(response.text); notice('Response copied.'); } catch { notice('Clipboard unavailable. Select the response text to copy it.'); } };
  pane.querySelectorAll('a').forEach(a => { a.target = '_blank'; a.rel = 'noopener noreferrer'; });
}
function renderPromptView() {
  $('#evidence-panel').innerHTML = '<div class="prompt-controls"><select id="prompt-mode" aria-label="Prompt view"><option value="diff">Show changes</option><option value="edited">Full edited conversation</option><option value="original">Full original conversation</option></select><div class="diff-legend"><span>− Removed</span><span>+ Added</span></div></div><div id="prompt-content"></div>';
  const render = () => {
    const mode = $('#prompt-mode').value;
    $('.diff-legend').hidden = mode !== 'diff';
    if (mode === 'diff') $('#prompt-content').innerHTML = `<div class="prompt-diff">${state.experiment.diff.map(part => part.type === 'same' ? escapeHTML(part.text) : `<${part.type === 'added' ? 'ins' : 'del'} class="${part.text.trim() ? '' : 'diff-whitespace'}">${escapeHTML(part.text)}</${part.type === 'added' ? 'ins' : 'del'}>`).join('')}</div>`;
    else {
      const messages = (mode === 'original' ? state.current.baseline : state.experiment).messages;
      $('#prompt-content').innerHTML = `<div class="messages">${messages.map((message,index) => `<details class="message" ${index === messages.length-1 ? 'open' : ''}><summary>${index+1} · ${escapeHTML(message.role.toUpperCase())} · ${String(message.content).length.toLocaleString()} characters</summary><div class="message-body">${escapeHTML(message.content)}</div></details>`).join('')}</div>`;
    }
  };
  $('#prompt-mode').onchange = render; render();
}
function renderClaims() {
  $('#evidence-panel').innerHTML = state.experiment.claims.length ? state.experiment.claims.map(c => `<article class="claim"><h3>${escapeHTML(c.claim_id)} <span class="badge">Label: ${c.is_true ? 'True' : 'False'}</span></h3><pre>${escapeHTML(c.statement)}</pre><div class="claim-footer">Source counts: ${escapeHTML(c.baseline_rate)} → ${escapeHTML(c.counterfactual_rate)} · linked experiment${c.experiment_numbers.length === 1 ? '' : 's'} ${c.experiment_numbers.join(', ')} · ${escapeHTML(c.gen_version)}</div></article>`).join('') : '<p class="empty">This experiment is part of the investigation but has no claim in the canonical evaluation set. Its responses are still available to help you understand the behavior.</p>';
}
function changePage(offset) {
  state.page += offset;
  preloadFailures.clear();
  renderList();
  $('#investigation-list').scrollTop = 0;
}
$('#previous-page').onclick = () => changePage(-1);
$('#next-page').onclick = () => changePage(1);
$('#search').oninput = () => { state.page = 0; preloadFailures.clear(); renderList(); };
$('#shortlist-filter').onclick = () => { state.shortlistOnly = !state.shortlistOnly; state.page = 0; preloadFailures.clear(); renderList(); };
$('#dataset').onchange = e => loadDataset(e.target.value);
(async () => {
  try {
    state.datasets = await api('datasets');
    if (!state.datasets.length) {
      $('#investigation-list').innerHTML = '<p class="empty">No datasets imported yet.</p>';
      $('#workspace').innerHTML = '<div class="welcome"><span class="eyebrow">GET STARTED</span><h2>Bring in an investigation.</h2><p>Import the public CHIVE data from the terminal, then reload this page.</p><pre class="raw">uv run -m chive_optimization.download\n  --data-dir /path/to/local/cache</pre><p>Use the same cache directory when starting this viewer.</p></div>';
      document.body.classList.add('detail-open'); $('#dataset').disabled = true; return;
    }
    $('#dataset').innerHTML = state.datasets.map(d => `<option value="${escapeHTML(d.id)}">${escapeHTML(d.label)}</option>`).join('');
    const params = new URLSearchParams(location.hash.slice(1));
    const dataset = state.datasets.some(d => d.id === params.get('dataset')) ? params.get('dataset') : state.datasets[0].id;
    if (params.has('id')) document.body.classList.add('detail-open');
    await loadDataset(dataset, params.get('id'), params.get('experiment'));
  } catch (error) { showError(error); document.body.classList.add('detail-open'); }
})();
