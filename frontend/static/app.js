/**
 * app.js
 * ------
 * Dashboard logic for the Referral Fraud Detection Pipeline.
 *
 * Responsibilities:
 *   - Render and manage the 7-file upload grid
 *   - POST files to /api/run and animate the pipeline steps
 *   - Animate stat card count-ups
 *   - Render the fraud conditions horizontal bar chart
 *   - Render, sort, filter, and expand the 22-column report table
 *   - Toast notifications
 *   - Auto-load existing report on page load (/api/results)
 */

'use strict';

/* ============================================================
   Constants
   ============================================================ */
const FILE_SLOTS = [
  { key: 'lead_log',               label: 'Lead Log',               filename: 'lead_log.csv',               icon: '📋' },
  { key: 'user_referrals',         label: 'User Referrals',         filename: 'user_referrals.csv',         icon: '👥' },
  { key: 'user_referral_logs',     label: 'Referral Logs',          filename: 'user_referral_logs.csv',     icon: '📝' },
  { key: 'user_logs',              label: 'User Logs',              filename: 'user_logs.csv',              icon: '🗂️' },
  { key: 'user_referral_statuses', label: 'Referral Statuses',      filename: 'user_referral_statuses.csv', icon: '🏷️' },
  { key: 'referral_rewards',       label: 'Referral Rewards',       filename: 'referral_rewards.csv',       icon: '🎁' },
  { key: 'paid_transactions',      label: 'Paid Transactions',      filename: 'paid_transactions.csv',      icon: '💳' },
];

// Columns to show in the table by default (first render)
const PRIMARY_COLUMNS = [
  'referral_details_id', 'referral_id', 'referral_source_category', 'referral_at',
  'referrer_name', 'referee_name', 'referral_status',
  'num_reward_days', 'transaction_status', 'is_business_logic_valid'
];

const CONDITION_META = {
  'V1 — Fully earned reward':        { cls: 'valid-bar',   chip: 'valid-chip'   },
  'V2 — Pending/failed, no reward':  { cls: 'valid-bar',   chip: 'valid-chip'   },
  'I1 — Reward without completion':  { cls: 'invalid-bar', chip: 'invalid-chip' },
  'I2 — Reward without transaction': { cls: 'invalid-bar', chip: 'invalid-chip' },
  'I3 — Transaction without reward': { cls: 'invalid-bar', chip: 'invalid-chip' },
  'I4 — Completed without reward':   { cls: 'invalid-bar', chip: 'invalid-chip' },
  'I5 — Backdated transaction':      { cls: 'invalid-bar', chip: 'invalid-chip' },
  'I6 — Earned but never disbursed': { cls: 'bonus-bar',   chip: 'bonus-chip'   },
  'I7 — Orphaned transaction ref':   { cls: 'bonus-bar',   chip: 'bonus-chip'   },
};

/* ============================================================
   State
   ============================================================ */
let uploadedFiles = {};          // key → File object
let allRows = [];                // full report rows from API
let allColumns = [];             // column names
let sortCol = null;
let sortAsc = true;
let expandedRow = null;          // index of expanded row

/* ============================================================
   Init
   ============================================================ */
document.addEventListener('DOMContentLoaded', () => {
  renderUploadGrid();
  autoLoadExistingResults();
});

/* ============================================================
   UPLOAD GRID
   ============================================================ */
function renderUploadGrid() {
  const grid = document.getElementById('upload-grid');
  grid.innerHTML = FILE_SLOTS.map(slot => `
    <div class="upload-item" id="slot-${slot.key}"
         ondragover="onDragOver(event, '${slot.key}')"
         ondragleave="onDragLeave(event, '${slot.key}')"
         ondrop="onDrop(event, '${slot.key}')">
      <input type="file" accept=".csv" id="input-${slot.key}"
             onchange="onFileSelected('${slot.key}', this)" />
      <div class="upload-check">✓</div>
      <div class="upload-icon">${slot.icon}</div>
      <div class="upload-label">${slot.label}</div>
      <div class="upload-filename" id="fname-${slot.key}">—</div>
      <div class="upload-hint">${slot.filename}</div>
    </div>
  `).join('');
  updateUploadProgress();
}

function onFileSelected(key, input) {
  if (!input.files || !input.files[0]) return;
  const file = input.files[0];
  uploadedFiles[key] = file;
  const slot = document.getElementById(`slot-${key}`);
  const fnameEl = document.getElementById(`fname-${key}`);
  slot.classList.add('file-ready');
  fnameEl.textContent = file.name;
  updateUploadProgress();
}

function onDragOver(e, key) {
  e.preventDefault();
  document.getElementById(`slot-${key}`).classList.add('drag-over');
}

function onDragLeave(e, key) {
  document.getElementById(`slot-${key}`).classList.remove('drag-over');
}

function onDrop(e, key) {
  e.preventDefault();
  const slot = document.getElementById(`slot-${key}`);
  slot.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (!file) return;
  uploadedFiles[key] = file;
  slot.classList.add('file-ready');
  document.getElementById(`fname-${key}`).textContent = file.name;
  // also set the file input value (for form submission, best-effort)
  updateUploadProgress();
}

function updateUploadProgress() {
  const count = Object.keys(uploadedFiles).length;
  document.getElementById('upload-progress-badge').textContent = `${count} / 7 files`;
  document.getElementById('btn-run').disabled = false; // always allow (missing = reuse disk)
  if (count === 7) {
    document.getElementById('btn-run').disabled = false;
  }
}

/* ============================================================
   PIPELINE RUN
   ============================================================ */
async function runPipeline() {
  const btn = document.getElementById('btn-run');
  btn.disabled = true;
  btn.innerHTML = `<span style="animation:spin 1s linear infinite;display:inline-block">⟳</span> Running…`;

  resetProgress();
  showSection('progress-section');
  scrollTo(document.getElementById('progress-section'));

  const formData = new FormData();
  for (const slot of FILE_SLOTS) {
    if (uploadedFiles[slot.key]) {
      formData.append(slot.key, uploadedFiles[slot.key]);
    }
  }

  // Animate steps as we go (fake progress while waiting for the single API response)
  const stepNames = ['Load', 'Clean', 'Transform', 'Fraud Rules', 'Report'];
  const logMsgs = [
    '▶ Loading 7 raw CSV tables...',
    '▶ Cleaning tables (dtypes, Initcap, nulls)...',
    '▶ Transforming: joining & localizing timestamps...',
    '▶ Applying 9 fraud detection rules...',
    '▶ Building final 22-column report...',
  ];

  // Advance step animations at 600ms intervals until the response arrives
  let stepInterval = null;
  let currentStep = 0;
  function advanceStep() {
    if (currentStep < stepNames.length) {
      setStepActive(currentStep);
      appendLog(logMsgs[currentStep]);
      currentStep++;
    }
  }
  advanceStep();
  stepInterval = setInterval(advanceStep, 1800);

  try {
    const res = await fetch('/api/run', { method: 'POST', body: formData });
    clearInterval(stepInterval);

    const data = await res.json();

    if (!res.ok || data.error) {
      // mark last active step as error
      setStepActive(currentStep - 1, true);
      appendLog('✗ Error: ' + (data.error || 'Unknown error'), 'error');
      showToast('Pipeline failed: ' + (data.error || 'See log for details'), 'error');
      btn.disabled = false;
      btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg> Run Pipeline`;
      return;
    }

    // All steps done
    for (let i = 0; i < 5; i++) setStepDone(i);
    if (data.log) data.log.forEach(l => appendLog(l, l.startsWith('✓') ? 'success' : ''));

    renderResults(data);
    showToast(`Pipeline complete! ${data.stats.total} referrals processed in ${data.elapsed_seconds}s`, 'success');

  } catch (err) {
    clearInterval(stepInterval);
    appendLog('✗ Network error: ' + err.message, 'error');
    showToast('Network error — is the server running?', 'error');
  }

  btn.disabled = false;
  btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg> Run Pipeline`;
}

/* ============================================================
   AUTO-LOAD EXISTING RESULTS
   ============================================================ */
async function autoLoadExistingResults() {
  try {
    const res = await fetch('/api/results');
    if (!res.ok) return;
    const data = await res.json();
    if (data.status === 'success') {
      appendLog('ℹ Loaded existing report from disk.');
      if (data.log) data.log.forEach(l => appendLog(l));
      renderResults(data, /* silent */ true);
    }
  } catch (_) {
    // server not reachable / no results — that's fine
  }
}

/* ============================================================
   RENDER RESULTS
   ============================================================ */
function renderResults(data, silent = false) {
  // Stats
  renderStats(data.stats, data.elapsed_seconds);

  // Conditions chart
  if (data.conditions && Object.keys(data.conditions).length > 0) {
    renderConditionsChart(data.conditions);
    showSectionEl(document.getElementById('conditions-section'));
  }

  // Table
  allRows = data.rows || [];
  allColumns = data.columns || [];
  renderTable();
  showSectionEl(document.getElementById('table-section'));
  showSectionEl(document.getElementById('stats-section'));

  // Hero download button
  document.getElementById('btn-download-top').classList.remove('hidden');

  if (!silent) {
    setTimeout(() => scrollTo(document.getElementById('stats-section')), 300);
  }
}

/* ============================================================
   STATS
   ============================================================ */
function renderStats(stats, elapsed) {
  const statEl = (id, val, suffix = '') => {
    const el = document.getElementById(id);
    animateCount(el, 0, val, 800, suffix);
  };

  statEl('stat-total',   stats.total);
  statEl('stat-valid',   stats.valid);
  statEl('stat-invalid', stats.invalid);
  statEl('stat-rate',    stats.validity_rate, '%');

  ['card-total','card-valid','card-invalid','card-rate'].forEach(id => {
    const card = document.getElementById(id);
    if (card) card.classList.add('loaded');
  });

  if (elapsed != null) {
    document.getElementById('elapsed-badge').textContent = `⏱ ${elapsed}s`;
  }
}

function animateCount(el, from, to, duration, suffix = '') {
  if (!el) return;
  const start = performance.now();
  function step(now) {
    const progress = Math.min((now - start) / duration, 1);
    const ease = 1 - Math.pow(1 - progress, 3); // ease-out cubic
    const value = from + (to - from) * ease;
    const display = Number.isInteger(to) ? Math.round(value) : value.toFixed(1);
    el.textContent = display + suffix;
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

/* ============================================================
   CONDITIONS CHART
   ============================================================ */
function renderConditionsChart(conditions) {
  const wrap = document.getElementById('conditions-chart');
  const maxVal = Math.max(...Object.values(conditions), 1);

  wrap.innerHTML = Object.entries(conditions).map(([label, count], i) => {
    const meta = CONDITION_META[label] || { cls: 'valid-bar', chip: 'valid-chip' };
    const pct = (count / maxVal) * 100;
    const delay = i * 80;
    return `
      <div class="condition-row" style="animation-delay:${delay}ms">
        <div class="condition-label" title="${label}">${label}</div>
        <div class="condition-bar-wrap">
          <div class="condition-bar ${meta.cls}"
               style="width:${pct}%;animation-delay:${delay + 100}ms"></div>
        </div>
        <div class="condition-count">${count}</div>
      </div>
    `;
  }).join('');
}

/* ============================================================
   TABLE
   ============================================================ */
function renderTable() {
  const head = document.getElementById('table-head');
  const tbody = document.getElementById('table-body');

  // Decide which columns to show
  const cols = PRIMARY_COLUMNS.filter(c => allColumns.includes(c));

  // Header
  head.innerHTML = `<tr>${cols.map(c => `
    <th id="th-${c}" onclick="sortTable('${c}')"
        class="${sortCol === c ? 'sorted' : ''}">
      ${formatColName(c)}
      <span class="sort-icon">${sortCol === c ? (sortAsc ? '↑' : '↓') : '⇅'}</span>
    </th>`).join('')}<th>Details</th></tr>`;

  // Filter & sort rows
  const filtered = getFilteredRows();
  document.getElementById('row-count-badge').textContent = `${filtered.length} row${filtered.length !== 1 ? 's' : ''}`;

  // Body
  tbody.innerHTML = '';
  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="${cols.length + 1}" style="text-align:center;padding:40px;color:var(--text-muted)">No rows match the current filter.</td></tr>`;
    return;
  }

  filtered.forEach((row, idx) => {
    const isValid = row['is_business_logic_valid'] === true || row['is_business_logic_valid'] === 'True';
    const rowCls  = isValid ? 'row-valid' : 'row-invalid';
    const rowId   = `row-${idx}`;
    const detailId = `detail-${idx}`;

    const tds = cols.map(c => {
      let val = row[c];
      if (val === null || val === undefined) val = '—';
      if (c === 'is_business_logic_valid') {
        const v = val === true || val === 'True' || val === 1;
        return `<td><span class="validity-badge ${v ? 'valid' : 'invalid'}">${v ? '✓ Valid' : '✗ Invalid'}</span></td>`;
      }
      const isMono = ['referral_id','transaction_id','referrer_id','referee_id',
                      'referral_details_id','referrer_phone_number','referee_phone'].includes(c);
      const isId = ['referral_details_id'].includes(c);
      return `<td class="${isMono ? 'mono' : ''} ${isId ? 'col-id' : ''}" title="${val}">${val}</td>`;
    }).join('');

    // Main row
    const tr = document.createElement('tr');
    tr.className = rowCls;
    tr.id = rowId;
    tr.innerHTML = tds + `<td><button class="btn btn-secondary btn-icon" onclick="toggleDetail(${idx})" title="Expand row" id="expand-btn-${idx}">⋯</button></td>`;
    tbody.appendChild(tr);

    // Detail row
    const detailTr = document.createElement('tr');
    detailTr.className = 'row-detail-tr';
    detailTr.id = detailId;
    detailTr.innerHTML = `<td class="row-detail-td" colspan="${cols.length + 1}">
      ${buildDetailPanel(row)}
    </td>`;
    tbody.appendChild(detailTr);
  });
}

function buildDetailPanel(row) {
  const conditions = row['_conditions_fired'] || [];
  const condHtml = conditions.length
    ? conditions.map(c => {
        const meta = CONDITION_META[c] || { chip: 'valid-chip' };
        return `<span class="condition-chip ${meta.chip}">${c}</span>`;
      }).join('')
    : '<span style="color:var(--text-muted);font-size:12px">No conditions data available for this row.</span>';

  // Show key fields
  const keyFields = [
    'referral_id', 'referral_source', 'referral_source_category', 'referral_at',
    'referrer_name', 'referrer_homeclub', 'referee_name',
    'referral_status', 'num_reward_days',
    'transaction_id', 'transaction_status', 'transaction_at', 'transaction_type',
    'reward_granted_at', 'updated_at',
  ];
  const kvHtml = keyFields
    .filter(k => k in row && row[k] !== undefined && row[k] !== null)
    .map(k => `<span><b>${formatColName(k)}:</b> ${row[k]}</span>`)
    .join('');

  return `
    <div class="row-detail-inner">
      <div class="row-detail-block">
        <h4>Conditions Fired</h4>
        <div>${condHtml}</div>
      </div>
      <div class="row-detail-block" style="flex:2">
        <h4>Row Details</h4>
        <div class="detail-kv">${kvHtml}</div>
      </div>
    </div>`;
}

function toggleDetail(idx) {
  const detailTr = document.getElementById(`detail-${idx}`);
  if (!detailTr) return;
  const isOpen = detailTr.classList.contains('open');

  // Close previous
  if (expandedRow !== null && expandedRow !== idx) {
    const prev = document.getElementById(`detail-${expandedRow}`);
    if (prev) prev.classList.remove('open');
    const prevBtn = document.getElementById(`expand-btn-${expandedRow}`);
    if (prevBtn) prevBtn.textContent = '⋯';
  }

  if (isOpen) {
    detailTr.classList.remove('open');
    document.getElementById(`expand-btn-${idx}`).textContent = '⋯';
    expandedRow = null;
  } else {
    detailTr.classList.add('open');
    document.getElementById(`expand-btn-${idx}`).textContent = '✕';
    expandedRow = idx;
  }
}

/* Sorting */
function sortTable(col) {
  if (sortCol === col) {
    sortAsc = !sortAsc;
  } else {
    sortCol = col;
    sortAsc = true;
  }
  expandedRow = null;
  renderTable();
}

/* Filtering */
function filterTable() {
  expandedRow = null;
  renderTable();
}

function getFilteredRows() {
  const query = (document.getElementById('table-search')?.value || '').toLowerCase().trim();
  const validityFilter = document.getElementById('filter-validity')?.value || 'all';
  const statusFilter = document.getElementById('filter-status')?.value || 'all';

  let rows = [...allRows];

  // Validity filter
  if (validityFilter !== 'all') {
    rows = rows.filter(r => {
      const v = r['is_business_logic_valid'];
      const isValid = v === true || v === 'True' || v === 1;
      return validityFilter === 'valid' ? isValid : !isValid;
    });
  }

  // Status filter
  if (statusFilter !== 'all') {
    rows = rows.filter(r => r['referral_status'] === statusFilter);
  }

  // Text search
  if (query) {
    rows = rows.filter(r =>
      Object.values(r).some(v =>
        v !== null && v !== undefined && String(v).toLowerCase().includes(query)
      )
    );
  }

  // Sort
  if (sortCol) {
    rows.sort((a, b) => {
      let va = a[sortCol] ?? '';
      let vb = b[sortCol] ?? '';
      // numeric sort
      if (typeof va === 'number' && typeof vb === 'number') {
        return sortAsc ? va - vb : vb - va;
      }
      va = String(va).toLowerCase();
      vb = String(vb).toLowerCase();
      if (va < vb) return sortAsc ? -1 : 1;
      if (va > vb) return sortAsc ? 1 : -1;
      return 0;
    });
  }

  return rows;
}

/* ============================================================
   PIPELINE STEP ANIMATION
   ============================================================ */
function resetProgress() {
  document.getElementById('pipeline-log').innerHTML = '';
  for (let i = 0; i < 5; i++) {
    const el = document.getElementById(`step-${i}`);
    el.classList.remove('active', 'done');
  }
}

function setStepActive(idx, isError = false) {
  const el = document.getElementById(`step-${idx}`);
  if (!el) return;
  el.classList.add('active');
  if (isError) el.style.setProperty('--accent-blue', '#f87171');
}

function setStepDone(idx) {
  const el = document.getElementById(`step-${idx}`);
  if (!el) return;
  el.classList.remove('active');
  el.classList.add('done');
}

function appendLog(msg, cls = '') {
  const log = document.getElementById('pipeline-log');
  const line = document.createElement('div');
  line.className = `log-line ${cls}`;
  line.textContent = msg;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

/* ============================================================
   DOWNLOAD
   ============================================================ */
function downloadReport() {
  window.location.href = '/api/download';
}

/* ============================================================
   TOAST NOTIFICATIONS
   ============================================================ */
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  const icon = type === 'success' ? '✅' : '❌';
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span class="toast-icon">${icon}</span>
    <span class="toast-message">${message}</span>
    <span class="toast-close" onclick="this.parentElement.remove()">×</span>
  `;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 5500);
}

/* ============================================================
   SECTION VISIBILITY
   ============================================================ */
function showSection(id) {
  const el = document.getElementById(id);
  if (el) showSectionEl(el);
}

function showSectionEl(el) {
  el.classList.remove('hidden');
}

function scrollTo(el) {
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* ============================================================
   UTILITIES
   ============================================================ */
function formatColName(col) {
  return col
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}

// Add spin keyframe dynamically
const style = document.createElement('style');
style.textContent = `@keyframes spin { to { transform: rotate(360deg); } }`;
document.head.appendChild(style);
