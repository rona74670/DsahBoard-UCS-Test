// infinidat.js — Frontend for Infinidat iBox dashboard pages
'use strict';

const IBOX = window.IBOX_CONFIG || { apiPrefix: '/api/ibox/tc03', label: 'TC iBox-03' };

// ── helpers ──────────────────────────────────────────────────────────
function fmt(val, unit = 'TB', decimals = 2) {
  if (val === undefined || val === null || val === '') return '–';
  return `${Number(val).toFixed(decimals)} ${unit}`;
}
function fmtPct(val) { return (val === null || val === undefined) ? '–' : `${Math.round(val)}%`; }

function apiFetch(path) {
  return fetch(IBOX.apiPrefix + path).then(r => {
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  });
}

function setKpi(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function showStatus(msg, type = 'ok') {
  const bar = document.getElementById('status-bar');
  if (!bar) return;
  bar.textContent = msg;
  bar.className = `status-bar status-${type}`;
  bar.style.display = 'block';
}

function ts(ms) {
  if (!ms) return '–';
  return new Date(ms).toLocaleString('he-IL');
}

// ── Donut chart ───────────────────────────────────────────────────────
function drawDonut(svgId, pct, color) {
  const svg  = document.getElementById(svgId);
  if (!svg) return;
  const r    = 60, cx = 80, cy = 80, sw = 16;
  const circ = 2 * Math.PI * r;
  const used = Math.min(Math.max(pct, 0), 100);
  const dash = (used / 100) * circ;
  svg.innerHTML = `
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#21262d" stroke-width="${sw}"/>
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="${sw}"
      stroke-dasharray="${dash.toFixed(1)} ${circ.toFixed(1)}"
      stroke-linecap="round"
      transform="rotate(-90 ${cx} ${cy})"
      style="transition:stroke-dasharray 0.6s ease"/>
  `;
}

// ── Pool usage bars ───────────────────────────────────────────────────
function renderPoolBars(pools) {
  const wrap = document.getElementById('pool-bars');
  if (!wrap) return;
  if (!pools || !pools.length) { wrap.innerHTML = '<div style="color:var(--muted)">No pools</div>'; return; }

  const colors = ['#58a6ff','#3fb950','#f0883e','#bc8cff','#e3b341','#79c0ff'];
  wrap.innerHTML = pools.map((p, i) => {
    const col = colors[i % colors.length];
    const pct = p.phys_pct || 0;
    const barCol = pct > 85 ? '#f85149' : pct > 70 ? '#e3b341' : col;
    return `
      <div>
        <div style="display:flex;justify-content:space-between;font-size:0.78rem;margin-bottom:0.2rem;">
          <span style="color:var(--text);font-weight:600">${escHtml(p.name)}</span>
          <span style="color:var(--muted)">${fmt(p.phys_used_tb)} / ${fmt(p.phys_total_tb)} &nbsp; <b style="color:${barCol}">${pct}%</b></span>
        </div>
        <div class="pool-bar-wrap">
          <div class="pool-bar" style="width:${pct}%;background:${barCol}"></div>
        </div>
      </div>
    `;
  }).join('');
}

// ── Pools table ────────────────────────────────────────────────────────
function renderPoolsTable(pools) {
  const tbody = document.querySelector('#pools-table tbody');
  if (!tbody) return;
  if (!pools || !pools.length) { tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--muted)">No pools</td></tr>'; return; }
  tbody.innerHTML = pools.map(p => {
    const pctCol = p.phys_pct > 85 ? 'var(--critical)' : p.phys_pct > 70 ? 'var(--major)' : 'var(--ok)';
    return `<tr>
      <td><b>${escHtml(p.name)}</b></td>
      <td>${fmt(p.phys_total_tb)}</td>
      <td>${fmt(p.phys_used_tb)}</td>
      <td>${fmt(p.phys_free_tb)}</td>
      <td style="color:${pctCol};font-weight:700">${fmtPct(p.phys_pct)}</td>
      <td>${fmt(p.virt_total_tb)}</td>
      <td>${fmt(p.virt_used_tb)}</td>
      <td>${fmt(p.virt_free_tb)}</td>
      <td style="color:var(--accent);font-weight:600">${p.data_reduction ?? '–'}:1</td>
      <td>${fmt(p.savings_tb)}</td>
    </tr>`;
  }).join('');
}

// ── Volumes table ──────────────────────────────────────────────────────
function renderVolumesTable(data) {
  const tbody = document.querySelector('#volumes-table tbody');
  if (!tbody) return;
  const rows = data.by_pool || [];
  if (!rows.length) { tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--muted)">No data</td></tr>'; return; }
  tbody.innerHTML = rows.map(r => `<tr>
    <td>${escHtml(r.pool_name)}</td>
    <td>${r.count}</td>
    <td>${fmt(r.total_size_tb)}</td>
    <td>${fmt(r.total_used_tb)}</td>
  </tr>`).join('');
}

// ── Snapshots ──────────────────────────────────────────────────────────
let _snapCandidates = [];   // full list for client-side filtering
let _allSnaps       = [];   // all snapshots for the collapsible table
let _allSnapsSortField = 'date';
let _allSnapsSortAsc   = false;
let _diskUsageAvail    = true;   // false on firmware v7.x

function ageLabel(days) {
  if (days < 1)   return '< 1 day';
  if (days < 7)   return `${days} days`;
  if (days < 30)  return `${days} days`;
  if (days < 365) return `${Math.floor(days/30)}mo ${days%30}d`;
  return `${Math.floor(days/365)}y ${Math.floor((days%365)/30)}mo`;
}

function ageClass(days) {
  if (days >= 90) return 'age-very-old';
  if (days >= 30) return 'age-old';
  if (days <  7)  return 'age-fresh';
  return '';
}

function filterCandidates() {
  const minAge  = parseInt(document.getElementById('min-age-filter')?.value || '0', 10);
  const poolSel = document.getElementById('pool-filter')?.value || '';
  const filtered = _snapCandidates.filter(s =>
    s.age_days >= minAge && (!poolSel || s.pool_name === poolSel)
  );
  renderCandidatesBody(filtered);
}

function renderCandidatesBody(rows) {
  const tbody = document.getElementById('snap-candidates-body');
  if (!tbody) return;

  // Update "Physical Used" header based on firmware
  const thDisk = document.querySelector('#snap-candidates-table thead th:nth-child(4)');
  if (thDisk) {
    thDisk.innerHTML = _diskUsageAvail
      ? 'Physical Used (TB)'
      : '<span style="color:#e3b341" title="Firmware v7.x — נפח מוחזק, לא דלתא ייחודית">Referenced (TB) ⓘ</span>';
  }

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted)">No snapshots match filter</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(s => {
    const ac  = ageClass(s.age_days);
    const ageStyle = ac === 'age-very-old'
      ? 'color:#f85149;font-weight:700'
      : ac === 'age-old'
        ? 'color:#e3b341;font-weight:600'
        : ac === 'age-fresh'
          ? 'color:#3fb950'
          : '';
    const sizeVal   = _diskUsageAvail ? s.disk_usage_tb : (s.used_tb || 0);
    const diskStyle = sizeVal > 1
      ? (_diskUsageAvail ? 'color:#58a6ff;font-weight:600' : 'color:#e3b341;font-weight:600')
      : '';
    const childBadge = s.has_children
      ? '<span class="pill pill-warn" style="font-size:0.65rem">Has children</span>'
      : '';
    return `<tr>
      <td class="snap-name" title="${escHtml(s.name)}">${escHtml(s.name)}</td>
      <td>${escHtml(s.pool_name)}</td>
      <td style="${ageStyle}">${ageLabel(s.age_days)}</td>
      <td style="${diskStyle}">${fmt(sizeVal)}</td>
      <td>${fmt(s.parent_size_tb)}</td>
      <td style="white-space:nowrap;font-size:0.75rem">${ts(s.created_at)}</td>
      <td style="font-size:0.75rem;color:var(--muted)">${escHtml(s.policy || '–')}</td>
      <td>${childBadge}</td>
    </tr>`;
  }).join('');
}

function renderSnapshots(data) {
  setKpi('snap-total-count', data.total_count?.toLocaleString() ?? '–');
  if (data.disk_usage_avail === false) {
    setKpi('snap-total-disk', 'N/A');
    const diskEl = document.getElementById('snap-total-disk');
    if (diskEl) diskEl.style.color = 'var(--muted)';
    const noteEl = diskEl?.closest('.kpi-card')?.querySelector('div[style]');
    const unavailNote = document.createElement('div');
    unavailNote.style.cssText = 'font-size:0.65rem;color:#e3b341;margin-top:0.2rem';
    unavailNote.textContent = 'לא זמין ב-firmware v7.x';
    if (diskEl?.closest('.kpi-card')) diskEl.closest('.kpi-card').appendChild(unavailNote);
  } else {
    setKpi('snap-total-disk', fmt(data.total_disk_tb));
  }

  // By pool table
  const tbody1 = document.querySelector('#snaps-pool-table tbody');
  if (tbody1) {
    const rows = data.by_pool || [];
    const showDisk = data.disk_usage_avail !== false;
    // Update header if disk usage not available
    const thead1 = document.querySelector('#snaps-pool-table thead tr');
    if (thead1 && !showDisk) {
      thead1.innerHTML = '<th>Pool</th><th>Count</th><th style="color:#e3b341">Physical Space</th>';
    }
    tbody1.innerHTML = rows.length
      ? rows.map(r => `<tr>
          <td>${escHtml(r.pool_name)}</td>
          <td>${r.count.toLocaleString()}</td>
          <td style="color:${showDisk ? 'inherit' : 'var(--muted)'}">
            ${showDisk ? fmt(r.total_disk_tb) : '<span title="לא זמין ב-firmware v7.x" style=\'color:#e3b341\'>N/A</span>'}
          </td>
        </tr>`).join('')
      : '<tr><td colspan="3" style="text-align:center;color:var(--muted)">No snapshots</td></tr>';
  }

  // Deletion candidates
  _snapCandidates  = data.old_candidates || [];
  _diskUsageAvail  = data.disk_usage_avail !== false;  // true on v8+, false on v7.x

  // All snapshots
  _allSnaps = data.all_snapshots || [];
  const countEl = document.getElementById('all-snaps-count');
  if (countEl) countEl.textContent = _allSnaps.length.toLocaleString();

  // Populate pool filter dropdown
  const sel = document.getElementById('pool-filter');
  if (sel && _snapCandidates.length) {
    const pools = [...new Set(_snapCandidates.map(s => s.pool_name))].sort();
    pools.forEach(p => {
      const opt = document.createElement('option');
      opt.value = opt.textContent = p;
      sel.appendChild(opt);
    });
  }

  filterCandidates();
}

// ── All Snapshots table (collapsible) ───────────────────────────────────
function renderAllSnaps() {
  const tbody = document.getElementById('all-snaps-body');
  if (!tbody) return;
  if (!_allSnaps.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted)">אין נתונים</td></tr>';
    return;
  }

  // Update column header based on firmware capability
  const thead = document.querySelector('#all-snaps-table thead tr');
  if (thead) {
    const sizeLabel = _diskUsageAvail
      ? 'Physical (TB)'
      : '<span style="color:#e3b341" title="Firmware v7.x — מוחזק, לא דלתא ייחודית">Referenced (TB) ⓘ</span>';
    thead.innerHTML = `<th>Name</th><th>Pool</th><th>${sizeLabel}</th><th>Age (days)</th><th>Created</th><th>Status</th>`;
  }

  const sorted = [..._allSnaps].sort((a, b) => {
    const aSize = _diskUsageAvail ? a.disk_usage_tb : a.used_tb;
    const bSize = _diskUsageAvail ? b.disk_usage_tb : b.used_tb;
    let diff;
    if (_allSnapsSortField === 'size') diff = aSize - bSize;
    else                               diff = a.created_at - b.created_at;
    return _allSnapsSortAsc ? diff : -diff;
  });

  tbody.innerHTML = sorted.map(s => {
    const sizeVal = _diskUsageAvail ? s.disk_usage_tb : s.used_tb;
    const sizeStr = sizeVal > 0 ? sizeVal.toFixed(3) : '0.000';
    const sizeCol = !_diskUsageAvail ? 'color:#e3b341' : '';
    const locked  = s.write_protected;
    const lockIcon = locked
      ? '<span title="נעול" style="color:#e3b341">&#x1F512; נעול</span>'
      : '<span title="פתוח" style="color:#3fb950">&#x1F513; פתוח</span>';
    const created = s.created_at ? new Date(s.created_at).toLocaleDateString('he-IL') : '–';
    const ageCls  = ageClass(s.age_days);
    return `<tr class="${ageCls}">
      <td class="snap-name" title="${escHtml(s.name)}" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(s.name)}</td>
      <td style="font-size:0.78rem">${escHtml(s.pool_name)}</td>
      <td style="font-weight:600;${sizeCol}">${sizeStr}</td>
      <td style="font-size:0.78rem">${ageLabel(s.age_days)}</td>
      <td style="font-size:0.78rem;white-space:nowrap">${created}</td>
      <td>${lockIcon}</td>
    </tr>`;
  }).join('');

  // Update sort button indicators
  ['size', 'date'].forEach(f => {
    const btn = document.getElementById(`sort-${f}-btn`);
    if (!btn) return;
    const active = _allSnapsSortField === f;
    btn.style.background     = active ? '#264d73' : '';
    btn.style.borderColor    = active ? '#58a6ff' : '';
    btn.style.color          = active ? '#58a6ff' : '';
    const arrow = _allSnapsSortAsc ? '&#x2191;' : '&#x2193;';
    btn.innerHTML = active
      ? `${arrow} ${f === 'size' ? 'Size' : 'Date'}`
      : `&#x2195; ${f === 'size' ? 'Size' : 'Date'}`;
  });
}

function toggleAllSnaps() {
  const panel  = document.getElementById('all-snaps-panel');
  const arrow  = document.getElementById('all-snaps-arrow');
  if (!panel) return;
  const open = panel.style.display !== 'none';
  panel.style.display = open ? 'none' : 'block';
  if (arrow) arrow.innerHTML = open ? '&#9654;' : '&#9660;';
  if (!open && _allSnaps.length && !document.getElementById('all-snaps-body')?.children.length) {
    renderAllSnaps();
  }
  if (!open) renderAllSnaps(); // always re-render on open (data may have just loaded)
}

function sortAllSnaps(field) {
  if (_allSnapsSortField === field) {
    _allSnapsSortAsc = !_allSnapsSortAsc;  // flip direction
  } else {
    _allSnapsSortField = field;
    _allSnapsSortAsc   = false;            // default: newest / largest first
  }
  renderAllSnaps();
}

// ── Health ─────────────────────────────────────────────────────────────
function renderHealth(h) {
  const summary = document.getElementById('health-summary');
  if (summary) {
    const bbuPct = h.bbu_charge || 0;
    const bbuCol = bbuPct >= 90 ? 'ok' : bbuPct >= 50 ? 'warn' : 'error';
    const rebuildMsg = (h.rebuild_1 || h.rebuild_2) ? '<span class="pill pill-warn">Rebuild in progress</span>' : '';
    summary.innerHTML = `
      <span class="pill ${h.failed_drives > 0 ? 'pill-error' : 'pill-ok'}">
        Drives: ${h.active_drives} active · ${h.failed_drives} failed · ${h.missing_drives} missing
      </span>
      <span class="pill pill-${bbuCol}">BBU ${bbuPct}%</span>
      <span class="pill ${h.encryption ? 'pill-ok' : 'pill-warn'}">${h.encryption ? '&#x1F512; Encrypted' : 'Not encrypted'}</span>
      ${rebuildMsg}
    `;
  }

  const tbody = document.querySelector('#nodes-table tbody');
  if (!tbody) return;
  const nodes = h.nodes || [];
  if (!nodes.length) { tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--muted)">No node data</td></tr>'; return; }
  tbody.innerHTML = nodes.map(n => {
    const stateCol = n.state === 'ACTIVE' ? 'var(--ok)' : 'var(--critical)';
    const bbuCol   = n.bbu === 'protected' ? 'var(--ok)' : 'var(--major)';
    return `<tr>
      <td><b>${escHtml(n.name)}</b></td>
      <td style="color:${stateCol};font-weight:600">${n.state}</td>
      <td>${escHtml(n.model)}</td>
      <td style="color:${bbuCol}">${n.bbu || '–'}</td>
    </tr>`;
  }).join('');
}

// ── Replicas ────────────────────────────────────────────────────────────
function renderReplicas(reps) {
  const tbody = document.querySelector('#replicas-table tbody');
  if (!tbody) return;
  if (!reps || !reps.length) { tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted)">No replication configured</td></tr>'; return; }
  tbody.innerHTML = reps.map(r => {
    const ls   = r.link_state || '–';
    const lsCol = ls === 'ACTIVE' ? 'var(--ok)' : ls === 'SUSPENDED' ? 'var(--major)' : 'var(--critical)';
    const prog  = r.sync_progress != null ? `${r.sync_progress}%` : '–';
    return `<tr>
      <td>${r.id}</td>
      <td style="color:${lsCol};font-weight:600">${ls}</td>
      <td>${escHtml(r.sync_type || '–')}</td>
      <td>${prog}</td>
      <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(r.local_entity || '–')}</td>
      <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(r.remote_entity || '–')}</td>
    </tr>`;
  }).join('');
}

// ── Events ──────────────────────────────────────────────────────────────
function renderEvents(evts) {
  const tbody = document.querySelector('#events-table tbody');
  if (!tbody) return;
  if (!evts || !evts.length) {
    tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--ok)">&#x2713; No recent warnings or errors</td></tr>';
    return;
  }
  tbody.innerHTML = evts.map(e => {
    const cls = e.level === 'ERROR' || e.level === 'CRITICAL' ? 'pill-error' : 'pill-warn';
    return `<tr>
      <td style="white-space:nowrap">${ts(e.timestamp)}</td>
      <td><span class="pill ${cls}">${e.level}</span></td>
      <td style="font-size:0.8rem;max-width:500px">${escHtml(e.description)}</td>
    </tr>`;
  }).join('');
}

// ── Card toggle ─────────────────────────────────────────────────────────
function toggleCard(toggle) {
  const body = toggle.nextElementSibling;
  if (!body) return;
  const isOpen = body.style.display !== 'none';
  body.style.display = isOpen ? 'none' : '';
  const icon = toggle.querySelector('.card-toggle-icon');
  if (icon) icon.textContent = isOpen ? '▶' : '▼';
}

// ── Excel export ────────────────────────────────────────────────────────
function exportExcel(tableId, filename) {
  const tbl = document.getElementById(tableId);
  if (!tbl || typeof XLSX === 'undefined') return;
  const headers = [...tbl.querySelectorAll('thead th')].map(th => th.textContent.trim());
  const rows    = [...tbl.querySelectorAll('tbody tr')].map(tr =>
    [...tr.querySelectorAll('td')].map(td => td.textContent.trim())
  );
  const ws = XLSX.utils.aoa_to_sheet([headers, ...rows]);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Sheet1');
  XLSX.writeFile(wb, `${filename}.xlsx`);
}

// ── Top Volumes + Unprotected ───────────────────────────────────────────
function renderTopVolumes(data) {
  const tbody1 = document.querySelector('#top-vols-table tbody');
  if (tbody1) {
    const rows = data.top10 || [];
    tbody1.innerHTML = rows.length
      ? rows.map(v => `<tr>
          <td class="snap-name" title="${escHtml(v.name)}">${escHtml(v.name)}</td>
          <td>${escHtml(v.pool_name)}</td>
          <td style="font-weight:600">${fmt(v.size_tb)}</td>
          <td>${fmt(v.used_tb)}</td>
          <td style="font-size:0.75rem;color:var(--muted)">${escHtml(v.provtype)}</td>
          <td>${v.mapped ? '<span class="pill pill-ok">Yes</span>' : '<span class="pill" style="background:#1a1a1a;color:var(--muted);border:1px solid var(--border)">No</span>'}</td>
          <td style="font-size:0.75rem">${escHtml(v.policy)}</td>
        </tr>`).join('')
      : '<tr><td colspan="7" style="text-align:center;color:var(--muted)">No data</td></tr>';
  }

  const badge = document.getElementById('unprotected-badge');
  if (badge) badge.textContent = `${data.unprotected_count} / ${data.total_count}`;

  const tbody2 = document.querySelector('#unprotected-table tbody');
  if (tbody2) {
    const rows = data.unprotected || [];
    tbody2.innerHTML = rows.length
      ? rows.map(v => `<tr>
          <td class="snap-name" title="${escHtml(v.name)}">${escHtml(v.name)}</td>
          <td>${escHtml(v.pool_name)}</td>
          <td>${fmt(v.size_tb)}</td>
          <td>${fmt(v.used_tb)}</td>
          <td>${v.mapped ? '<span class="pill pill-ok">Yes</span>' : '<span class="pill" style="background:#1a1a1a;color:var(--muted);border:1px solid var(--border)">No</span>'}</td>
        </tr>`).join('')
      : '<tr><td colspan="5" style="text-align:center;color:var(--ok)">✓ All volumes have snapshot policies</td></tr>';
  }
}

// ── Consistency Groups ──────────────────────────────────────────────────
function renderCGs(cgs) {
  const tbody = document.querySelector('#cgs-table tbody');
  if (!tbody) return;
  if (!cgs || !cgs.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--muted)">No consistency groups</td></tr>';
    return;
  }
  tbody.innerHTML = cgs.map(cg => `<tr>
    <td><b>${escHtml(cg.name)}</b></td>
    <td style="font-size:0.75rem;color:var(--muted)">${escHtml(cg.type || '–')}</td>
    <td>${cg.is_replicated ? '<span class="pill pill-ok">Yes</span>' : '–'}</td>
    <td>${cg.has_children ? '<span class="pill pill-info">Yes</span>' : '–'}</td>
  </tr>`).join('');
}

// ── Hosts ───────────────────────────────────────────────────────────────
function renderHosts(data) {
  const kpis = document.getElementById('hosts-kpis');
  if (kpis) {
    kpis.innerHTML = `
      <div class="kpi-card" style="padding:0.5rem 1rem;flex:0 0 auto">
        <div class="kpi-label">Total Hosts</div><div class="kpi-value">${data.total ?? '–'}</div>
      </div>
      <div class="kpi-card" style="padding:0.5rem 1rem;flex:0 0 auto">
        <div class="kpi-label">With LUNs</div><div class="kpi-value" style="color:var(--ok)">${data.mapped ?? '–'}</div>
      </div>
      <div class="kpi-card" style="padding:0.5rem 1rem;flex:0 0 auto">
        <div class="kpi-label">No LUNs</div><div class="kpi-value" style="color:var(--muted)">${data.unmapped ?? '–'}</div>
      </div>`;
  }
  const tbody = document.querySelector('#hosts-type-table tbody');
  if (!tbody) return;
  const rows = data.by_type || [];
  tbody.innerHTML = rows.length
    ? rows.map(r => `<tr>
        <td><b>${escHtml(r.type)}</b></td>
        <td>${r.count}</td>
      </tr>`).join('')
    : '<tr><td colspan="2" style="text-align:center;color:var(--muted)">No hosts</td></tr>';
}

// ── Enhanced Replicas ───────────────────────────────────────────────────
function renderReplicas(reps) {
  const tbody = document.querySelector('#replicas-table tbody');
  if (!tbody) return;
  if (!reps || !reps.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted)">No replication configured</td></tr>';
    return;
  }
  tbody.innerHTML = reps.map(r => {
    const state = r.state || '–';
    const stateCol = state === 'ACTIVE' ? 'var(--ok)' : state === 'SUSPENDED' ? 'var(--major)' : 'var(--critical)';
    const jobState = r.job_state || '–';
    const jobCol = jobState === 'DONE' ? 'var(--ok)' : jobState === 'RUNNING' ? 'var(--accent)' : 'var(--muted)';
    const ago = r.last_sync_ago_min != null
      ? (r.last_sync_ago_min < 60 ? `${r.last_sync_ago_min}m ago` : `${(r.last_sync_ago_min/60).toFixed(1)}h ago`)
      : '–';
    const dur = r.job_duration_s != null ? `${r.job_duration_s}s` : '–';
    return `<tr>
      <td>${r.id}</td>
      <td style="color:${stateCol};font-weight:600">${state}</td>
      <td style="font-size:0.75rem">${escHtml(r.role || '–')}</td>
      <td style="font-size:0.75rem">${escHtml(r.entity_type || '–')}</td>
      <td style="font-size:0.75rem;white-space:nowrap">${ago}</td>
      <td style="font-size:0.75rem">${dur}</td>
      <td style="color:${jobCol};font-size:0.75rem">${jobState}</td>
    </tr>`;
  }).join('');
}

// ── Capacity Trend Chart ────────────────────────────────────────────────
function renderCapacityTrend(data) {
  const daysEl  = document.getElementById('days-until-full');
  const noteEl  = document.getElementById('days-full-note');
  const cardEl  = document.getElementById('days-full-card');
  const emptyEl = document.getElementById('trend-empty');
  const canvas  = document.getElementById('trend-canvas');

  const days = data.days_until_full;
  const history = data.history || [];

  if (daysEl) {
    if (days === null || days === undefined) {
      daysEl.textContent = '?';
      if (noteEl) noteEl.textContent = `${data.readings} קריאות — יש צורך ב-2+ כדי לחשב מגמה`;
    } else if (days === 0) {
      daysEl.textContent = 'FULL';
      daysEl.style.color = 'var(--critical)';
    } else {
      daysEl.textContent = days;
      if (cardEl) cardEl.style.borderColor = days < 30 ? 'var(--critical)' : days < 60 ? 'var(--major)' : '';
      if (noteEl) noteEl.textContent = days < 30 ? '⚠ קריטי — פחות מחודש' : days < 90 ? '⚠ יש לתכנן הרחבה' : '✓ רמה סבירה';
      if (noteEl) noteEl.style.color = days < 30 ? '#f85149' : days < 90 ? '#e3b341' : '#3fb950';
    }
  }

  if (!canvas) return;
  if (history.length < 2) {
    canvas.style.display = 'none';
    if (emptyEl) emptyEl.style.display = 'block';
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';
  canvas.style.display = 'block';

  // Simple canvas line chart
  const ctx  = canvas.getContext('2d');
  const W    = canvas.offsetWidth || 600;
  const H    = 120;
  canvas.width  = W;
  canvas.height = H;
  ctx.clearRect(0, 0, W, H);

  const pcts = history.map(r => r.phys_pct);
  const minP = Math.max(0,  Math.min(...pcts) - 5);
  const maxP = Math.min(100, Math.max(...pcts) + 5);
  const pad  = { l: 40, r: 20, t: 10, b: 20 };
  const iW   = W - pad.l - pad.r;
  const iH   = H - pad.t - pad.b;

  function xPos(i)   { return pad.l + (i / (history.length - 1)) * iW; }
  function yPos(pct) { return pad.t + (1 - (pct - minP) / (maxP - minP)) * iH; }

  // Grid lines
  ctx.strokeStyle = '#21262d'; ctx.lineWidth = 1;
  [70, 80, 90].forEach(p => {
    if (p < maxP && p > minP) {
      ctx.beginPath(); ctx.moveTo(pad.l, yPos(p)); ctx.lineTo(W - pad.r, yPos(p)); ctx.stroke();
      ctx.fillStyle = '#444'; ctx.font = '10px monospace';
      ctx.fillText(`${p}%`, 2, yPos(p) + 4);
    }
  });

  // Line
  const lineColor = pcts[pcts.length-1] > 85 ? '#f85149' : pcts[pcts.length-1] > 70 ? '#e3b341' : '#58a6ff';
  ctx.beginPath(); ctx.moveTo(xPos(0), yPos(pcts[0]));
  history.forEach((r, i) => { if (i > 0) ctx.lineTo(xPos(i), yPos(r.phys_pct)); });
  ctx.strokeStyle = lineColor; ctx.lineWidth = 2; ctx.stroke();

  // Dots
  history.forEach((r, i) => {
    ctx.beginPath(); ctx.arc(xPos(i), yPos(r.phys_pct), 3, 0, 2*Math.PI);
    ctx.fillStyle = lineColor; ctx.fill();
  });

  // Labels: first and last date
  ctx.fillStyle = '#8b949e'; ctx.font = '10px monospace';
  const d0 = new Date(history[0].recorded_at).toLocaleDateString('he-IL');
  const d1 = new Date(history[history.length-1].recorded_at).toLocaleDateString('he-IL');
  ctx.fillText(d0, pad.l, H - 4);
  ctx.textAlign = 'right';
  ctx.fillText(d1, W - pad.r, H - 4);
}

// ── Security: HTML escaping ─────────────────────────────────────────────
function escHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── Main load ───────────────────────────────────────────────────────────
async function loadAll() {
  const btn = document.getElementById('refresh-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Loading…'; }

  try {
    // 1. Summary (fast) — also records capacity to DB server-side
    const sum = await apiFetch('/summary');

    document.getElementById('sys-version').textContent = `v${sum.system?.version || '–'}`;
    document.getElementById('sys-host').textContent    = sum.system?.host || '';

    const cap = sum.capacity || {};
    setKpi('kpi-phys-total', fmt(cap.phys_total_tb));
    setKpi('kpi-phys-free',  `${fmt(cap.phys_free_tb)} (${fmtPct(100 - cap.phys_pct)})`);
    setKpi('kpi-virt-total', fmt(cap.virt_total_tb));
    setKpi('kpi-virt-free',  `${fmt(cap.virt_free_tb)} (${fmtPct(100 - cap.virt_pct)})`);
    setKpi('kpi-dr',         `${cap.data_reduction}:1`);
    setKpi('kpi-savings',    fmt(cap.savings_tb));

    const cnt = sum.counts || {};
    setKpi('kpi-volumes',   cnt.volumes ?? '–');
    setKpi('kpi-snapshots', cnt.snapshots?.toLocaleString() ?? '–');
    setKpi('kpi-pools',     cnt.pools ?? '–');
    setKpi('kpi-hosts',     cnt.hosts ?? '–');

    const h = sum.health || {};
    setKpi('kpi-drives', h.active_drives ?? '–');
    const failedEl = document.getElementById('kpi-failed');
    if (failedEl) {
      failedEl.textContent = h.failed_drives ?? '–';
      if (h.failed_drives > 0) failedEl.style.color = 'var(--critical)';
    }

    drawDonut('donut-phys', cap.phys_pct || 0, cap.phys_pct > 85 ? '#f85149' : cap.phys_pct > 70 ? '#e3b341' : '#58a6ff');
    setKpi('donut-phys-pct', fmtPct(cap.phys_pct));
    setKpi('leg-phys-used',  fmt(cap.phys_used_tb));
    setKpi('leg-phys-free',  fmt(cap.phys_free_tb));
    setKpi('leg-phys-total', fmt(cap.phys_total_tb));

    drawDonut('donut-virt', cap.virt_pct || 0, cap.virt_pct > 85 ? '#f85149' : cap.virt_pct > 70 ? '#e3b341' : '#3fb950');
    setKpi('donut-virt-pct', fmtPct(cap.virt_pct));
    setKpi('leg-virt-used',  fmt(cap.virt_used_tb));
    setKpi('leg-virt-free',  fmt(cap.virt_free_tb));
    setKpi('leg-virt-total', fmt(cap.virt_total_tb));

    renderPoolBars(sum.pools);
    renderPoolsTable(sum.pools);
    renderHealth(h);

    showStatus(`Connected – ${sum.system?.host} – ${IBOX.label}`, 'ok');

    // 2. Fast parallel calls
    Promise.all([
      apiFetch('/volumes').then(renderVolumesTable).catch(e => console.warn('volumes:', e)),
      apiFetch('/replicas').then(renderReplicas).catch(e => console.warn('replicas:', e)),
      apiFetch('/events').then(renderEvents).catch(e => console.warn('events:', e)),
      apiFetch('/top-volumes').then(renderTopVolumes).catch(e => console.warn('top-volumes:', e)),
      apiFetch('/cgs').then(renderCGs).catch(e => console.warn('cgs:', e)),
      apiFetch('/hosts').then(renderHosts).catch(e => console.warn('hosts:', e)),
      apiFetch('/capacity-trend').then(renderCapacityTrend).catch(e => console.warn('trend:', e)),
    ]);

    // 3. Snapshots last (SLOW — paginates 2500+)
    apiFetch('/snapshots').then(renderSnapshots).catch(e => console.warn('snapshots:', e));

  } catch (err) {
    showStatus(`Connection failed: ${err.message}`, 'error');
    console.error(err);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '↻ Refresh'; }
  }
}

// Auto-load on page open
document.addEventListener('DOMContentLoaded', loadAll);
