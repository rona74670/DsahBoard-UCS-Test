/* =====================================================================
   UCS Dashboard – app.js
   ===================================================================== */

// Farm config injected by the HTML page
const FARM = window.FARM_CONFIG || {
  name:      'TC-FARM',
  host:      '10.10.140.100',
  apiPrefix: '/api/tc',
};

// Static column definitions
const FI_COLS    = ['id', 'model', 'oobIfIp', 'operState', 'side', 'serial'];
const RACK_COLS  = ['serverId', 'model', 'totalMemory', 'numOfCpus', 'operPower', 'operState', 'assignedToDn'];
const FAULT_COLS = ['severity', 'code', 'descr', 'dn', 'created'];

// Manual-data cache  serverId → {assignment, cabinet}
let manualCache = {};
let saveTimers  = {};

// Sort state for generic tables
const tableSortState = {};  // tableId → { col: index|null, dir: 'asc'|'desc' }

// Blade table sort state
let bladeData = [];
let bladeSort = { col: null, dir: 'asc' };

// Advanced table state (filterable + sortable)
const advTableState = {};  // tableId → { sortCol, sortDir, filter }

const SYSTEM_KEYS = [
  ['name',        'Domain Name'],
  ['address',     'Management IP'],
  ['mode',        'Mode'],
  ['state',       'State'],
  ['virtualIpv4', 'Virtual IPv4'],
  ['oobMgmtAddr', 'OOB Mgmt Address'],
  ['systemUpTime','System Uptime'],
];

// ------------------------------------------------------------------ //
//  Utility helpers                                                    //
// ------------------------------------------------------------------ //

async function apiFetch(path) {
  const res = await fetch(FARM.apiPrefix + path);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

function setStatus(msg, type = 'checking') {
  const el = document.getElementById('conn-status');
  el.textContent = msg;
  el.className = `status-box ${type}`;
}

function escapeHtml(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function escapeAttr(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/"/g,'&quot;');
}

function shortSP(dn) {
  if (!dn || dn === '–') return '–';
  const m = dn.match(/ls-(.+)$/);
  return m ? m[1] : dn.split('/').pop();
}

function buildTable(tableId, cols, rows) {
  const tbl   = document.getElementById(tableId);
  if (!tbl) return;
  const thead = tbl.querySelector('thead');
  const tbody = tbl.querySelector('tbody');
  if (!thead || !tbody) return;

  if (!tableSortState[tableId]) tableSortState[tableId] = { col: null, dir: 'asc' };
  const state = tableSortState[tableId];

  function applySort(data) {
    if (state.col === null) return [...data];
    const col = cols[state.col];
    return [...data].sort((a, b) => {
      const av = String(a[col] ?? '');
      const bv = String(b[col] ?? '');
      const cmp = av.localeCompare(bv, undefined, { numeric: true, sensitivity: 'base' });
      return state.dir === 'asc' ? cmp : -cmp;
    });
  }

  function render() {
    thead.innerHTML = `<tr>${cols.map((c, i) => {
      const active = state.col === i;
      const cls = 'sortable' + (active ? (state.dir === 'asc' ? ' sort-asc' : ' sort-desc') : '');
      return `<th class="${cls}" data-col="${i}">${c}</th>`;
    }).join('')}</tr>`;

    const sorted = applySort(rows);
    if (!sorted || sorted.length === 0) {
      tbody.innerHTML = `<tr><td colspan="${cols.length}" style="color:var(--muted);text-align:center">No data</td></tr>`;
    } else {
      tbody.innerHTML = sorted.map(row => `<tr>${cols.map((col, i) => {
        const val = row[col] ?? '–';
        let cell = escapeHtml(val);
        if (['operState','operPower','state'].includes(col)) {
          const cls = /ok|up|on|connected|operable/i.test(val) ? 'badge-ok'
                    : /error|fail|lost|fault/i.test(val)       ? 'badge-err'
                    :                                             'badge-warn';
          cell = `<span class="badge ${cls}">${escapeHtml(val)}</span>`;
        }
        if (col === 'severity') {
          const cls = {critical:'badge-err',major:'badge-warn',minor:'badge-warn',warning:'badge-warn'}[val] || '';
          cell = `<span class="badge ${cls}">${escapeHtml(val)}</span>`;
        }
        return `<td${i === 0 ? ' style="font-weight:600;color:var(--accent)"' : ''}>${cell}</td>`;
      }).join('')}</tr>`).join('');
    }

    thead.querySelectorAll('th.sortable').forEach(th => {
      th.addEventListener('click', () => {
        const ci = parseInt(th.dataset.col);
        if (state.col === ci) { state.dir = state.dir === 'asc' ? 'desc' : 'asc'; }
        else                   { state.col = ci; state.dir = 'asc'; }
        render();
      });
    });
  }

  render();
}

// ------------------------------------------------------------------ //
//  Advanced Sortable + Filterable Table                               //
// ------------------------------------------------------------------ //

// colDefs: [{key, label, width?, badgeFn?}]
// badgeFn: (val) => css-class string or ''

function operBadge(v) {
  return /operable|ok|up|^on$/i.test(v)     ? 'badge-ok'
       : /inoperable|fail|error|lost/i.test(v) ? 'badge-err'
       : v && v !== '–'                         ? 'badge-warn'
       : '';
}

function buildAdvancedTable(tableId, filterId, colDefs, rows) {
  if (!advTableState[tableId]) {
    advTableState[tableId] = { sortCol: null, sortDir: 'asc', filter: '' };
  }
  const state   = advTableState[tableId];
  const tbl     = document.getElementById(tableId);
  if (!tbl) return;
  const thead   = tbl.querySelector('thead');
  const tbody   = tbl.querySelector('tbody');
  const countEl = filterId ? document.getElementById(filterId + '-count') : null;

  // Re-bind filter input every time (fix stale closure on refresh)
  if (filterId) {
    const fi = document.getElementById(filterId);
    if (fi) {
      // Remove previous listener if any, then re-add with fresh closure
      if (fi._advListener) fi.removeEventListener('input', fi._advListener);
      fi._advListener = () => {
        state.filter = fi.value.toLowerCase().trim();
        renderAdv();
      };
      fi.addEventListener('input', fi._advListener);
      // Prevent click/keydown on filter from toggling the collapsible card
      if (!fi._stopPropBound) {
        fi._stopPropBound = true;
        fi.addEventListener('click',   e => e.stopPropagation());
        fi.addEventListener('keydown', e => e.stopPropagation());
        fi.addEventListener('focus',   e => e.stopPropagation());
        fi.addEventListener('mousedown', e => e.stopPropagation());
      }
      // Sync input value with current state (e.g. after refresh)
      fi.value = state.filter;
    }
  }

  function getRows() {
    let data = rows;
    if (state.filter) {
      data = data.filter(row =>
        colDefs.some(cd => String(row[cd.key] ?? '').toLowerCase().includes(state.filter))
      );
    }
    if (state.sortCol !== null) {
      const key = colDefs[state.sortCol].key;
      data = [...data].sort((a, b) => {
        const av = String(a[key] ?? '');
        const bv = String(b[key] ?? '');
        const cmp = av.localeCompare(bv, undefined, { numeric: true, sensitivity: 'base' });
        return state.sortDir === 'asc' ? cmp : -cmp;
      });
    }
    return data;
  }

  function renderAdv() {
    thead.innerHTML = `<tr>${colDefs.map((cd, i) => {
      const active = state.sortCol === i;
      const cls = 'sortable' + (active ? (state.sortDir === 'asc' ? ' sort-asc' : ' sort-desc') : '');
      const w = cd.width ? ` style="width:${cd.width}"` : '';
      return `<th class="${cls}" data-col="${i}"${w}>${escapeHtml(cd.label)}</th>`;
    }).join('')}</tr>`;

    const data = getRows();
    if (countEl) countEl.textContent = `${data.length} / ${rows.length} rows`;

    if (!data.length) {
      tbody.innerHTML = `<tr><td colspan="${colDefs.length}" style="text-align:center;color:var(--muted)">No results</td></tr>`;
    } else {
      tbody.innerHTML = data.map(row => {
        const isM5 = /M5/i.test(String(row.blade_model ?? '') + String(row.model ?? ''));
        return `<tr${isM5 ? ' class="row-m5"' : ''}>${colDefs.map(cd => {
        const val = String(row[cd.key] ?? '–');
        let cell = escapeHtml(val);
        if (cd.badgeFn) {
          const cls = cd.badgeFn(val);
          if (cls) cell = `<span class="badge ${cls}">${escapeHtml(val)}</span>`;
        }
        return `<td title="${escapeAttr(val)}">${cell}</td>`;
      }).join('')}</tr>`;
      }).join('');
    }

    thead.querySelectorAll('th.sortable').forEach(th => {
      th.addEventListener('click', () => {
        const ci = parseInt(th.dataset.col);
        if (state.sortCol === ci) { state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc'; }
        else { state.sortCol = ci; state.sortDir = 'asc'; }
        renderAdv();
      });
    });
  }

  renderAdv();
}

// ------------------------------------------------------------------ //
//  Column definitions for advanced tables                             //
// ------------------------------------------------------------------ //

const FIRMWARE_COLS = [
  { key: 'chassis',   label: 'Chassis',  width: '7%'  },
  { key: 'blade',     label: 'Blade',    width: '6%'  },
  { key: 'server_id', label: 'Server',   width: '8%'  },
  { key: 'model',     label: 'Model',    width: '14%' },
  { key: 'bios',      label: 'BIOS',     width: '22%' },
  { key: 'cimc',      label: 'CIMC/IMC', width: '22%' },
  { key: 'adapter',   label: 'Adapter',  width: '20%' },
];

const POWER_COLS = [
  { key: 'chassis',   label: 'Chassis',   width: '8%'  },
  { key: 'model',     label: 'Model',     width: '24%' },
  { key: 'input_w',   label: 'Input (W)', width: '14%' },
  { key: 'output_w',  label: 'Output (W)',width: '14%' },
  { key: 'ambient_c', label: 'Ambient',   width: '13%' },
  { key: 'front_c',   label: 'Front',     width: '13%' },
  { key: 'rear_c',    label: 'Rear',      width: '13%' },
];

const ADAPTER_COLS = [
  { key: 'chassis',     label: 'Chassis',     width: '6%'  },
  { key: 'blade',       label: 'Blade',       width: '5%'  },
  { key: 'server_id',   label: 'Server',      width: '7%'  },
  { key: 'blade_model', label: 'Server Model',width: '13%' },
  { key: 'adapter',     label: 'Adapter',     width: '6%'  },
  { key: 'model',       label: 'Model',       width: '30%' },
  { key: 'serial',      label: 'Serial',      width: '20%' },
  { key: 'pci_slot',    label: 'PCI Slot',    width: '8%'  },
];

const VNIC_COLS = [
  { key: 'chassis',     label: 'Chassis',   width: '7%'  },
  { key: 'blade',       label: 'Blade',     width: '6%'  },
  { key: 'server_id',   label: 'Server',    width: '8%'  },
  { key: 'blade_model', label: 'Model',     width: '12%' },
  { key: 'adapter',     label: 'Adapter',   width: '6%'  },
  { key: 'interface',   label: 'Interface', width: '12%' },
  { key: 'mac',         label: 'MAC',       width: '20%' },
  { key: 'mtu',         label: 'MTU',       width: '8%'  },
];

const VHBA_COLS = [
  { key: 'chassis',     label: 'Chassis',   width: '6%'  },
  { key: 'blade',       label: 'Blade',     width: '5%'  },
  { key: 'server_id',   label: 'Server',    width: '7%'  },
  { key: 'blade_model', label: 'Model',     width: '11%' },
  { key: 'adapter',     label: 'Adapter',   width: '6%'  },
  { key: 'interface',   label: 'Interface', width: '10%' },
  { key: 'wwpn',        label: 'WWPN',      width: '22%' },
  { key: 'node_wwn',    label: 'Node WWN',  width: '22%' },
];

const POOL_COLS = [
  { key: 'type',      label: 'Type',      width: '10%' },
  { key: 'name',      label: 'Name',      width: '28%' },
  { key: 'size',      label: 'Size',      width: '10%' },
  { key: 'assigned',  label: 'Assigned',  width: '10%' },
  { key: 'available', label: 'Available', width: '10%' },
  { key: 'pct_used',  label: '% Used',    width: '10%' },
];

const CPU_COLS = [
  { key: 'chassis',    label: 'Chassis',    width: '6%'  },
  { key: 'blade',      label: 'Blade',      width: '5%'  },
  { key: 'blade_model', label: 'Server',    width: '12%' },
  { key: 'socket',    label: 'Socket',      width: '5%'  },
  { key: 'cpu_model', label: 'CPU Model',   width: '30%' },
  { key: 'cores',     label: 'Cores',       width: '5%'  },
  { key: 'threads',   label: 'Threads',     width: '6%'  },
  { key: 'speed_ghz', label: 'GHz',         width: '7%'  },
  { key: 'status',    label: 'Status',      width: '9%', badgeFn: operBadge },
];

const MEM_COLS = [
  { key: 'chassis',     label: 'Chassis',    width: '6%'  },
  { key: 'blade',       label: 'Blade',      width: '5%'  },
  { key: 'blade_model', label: 'Server',     width: '12%' },
  { key: 'slot',        label: 'DIMM Slot',  width: '10%' },
  { key: 'capacity_gb', label: 'GB',         width: '5%'  },
  { key: 'type',        label: 'Type',       width: '6%'  },
  { key: 'clock_mhz',  label: 'MHz',         width: '6%'  },
  { key: 'mem_model',  label: 'Part No.',    width: '25%' },
  { key: 'status',     label: 'Status',      width: '9%', badgeFn: operBadge },
];

const PSU_COLS = [
  { key: 'chassis', label: 'Chassis', width: '7%'  },
  { key: 'psu_id',  label: 'PSU #',   width: '6%'  },
  { key: 'model',   label: 'Model',   width: '28%' },
  { key: 'status',  label: 'Status',  width: '12%', badgeFn: operBadge },
  { key: 'power',   label: 'Power',   width: '10%' },
  { key: 'voltage', label: 'Voltage', width: '10%' },
  { key: 'serial',  label: 'Serial',  width: '20%' },
];

const FAN_COLS = [
  { key: 'chassis', label: 'Chassis', width: '8%'  },
  { key: 'module',  label: 'Module',  width: '8%'  },
  { key: 'model',   label: 'Model',   width: '50%' },
  { key: 'status',  label: 'Status',  width: '15%', badgeFn: operBadge },
];

const BLADEIPS_COLS = [
  { key: 'chassis',         label: 'Chassis',         width: '7%'  },
  { key: 'blade',           label: 'Blade',           width: '5%'  },
  { key: 'blade_model',     label: 'Model',           width: '14%' },
  { key: 'mgmt_ip',         label: 'Management IP',   width: '15%' },
  { key: 'service_profile', label: 'Service Profile', width: '35%' },
];

// ------------------------------------------------------------------ //
//  Hardware summary loader                                            //
// ------------------------------------------------------------------ //

async function loadHardwareSummary() {
  try {
    const data = await apiFetch('/hardware-summary');

    const loadEl = document.getElementById('cpu-loading');
    if (loadEl) loadEl.style.display = 'none';

    buildAdvancedTable('cpu-table',      'cpu-filter',      CPU_COLS,      data.cpus         || []);
    buildAdvancedTable('mem-table',      'mem-filter',      MEM_COLS,      data.memory_units || []);
    buildAdvancedTable('psu-table',      'psu-filter',      PSU_COLS,      data.psus         || []);
    buildAdvancedTable('fans-table',     'fans-filter',     FAN_COLS,      data.fans         || []);
    buildAdvancedTable('blade-ips-table','bladeips-filter', BLADEIPS_COLS, data.blade_mgmt   || []);
  } catch (err) {
    const loadEl = document.getElementById('cpu-loading');
    if (loadEl) { loadEl.textContent = `⚠ Hardware data failed: ${err.message}`; }
    console.error('Hardware summary load failed:', err);
  }
}

function renderKpi(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value ?? '–';
}

function renderFaultPills(summary) {
  const container = document.getElementById('fault-pills');
  if (!container) return;
  const total = Object.values(summary).reduce((a, b) => a + b, 0);
  if (total === 0) {
    container.innerHTML = '<span class="pill none">No Faults</span>';
    return;
  }
  container.innerHTML = Object.entries(summary)
    .filter(([, v]) => v > 0)
    .map(([k, v]) => `<span class="pill ${k}">${k}: ${v}</span>`)
    .join('');
}

function renderSystemTable(info) {
  const tbody = document.querySelector('#system-table tbody');
  if (!tbody) return;
  if (!info || Object.keys(info).length === 0) {
    tbody.innerHTML = '<tr><td colspan="2" style="color:var(--muted)">No data</td></tr>';
    return;
  }
  tbody.innerHTML = SYSTEM_KEYS.map(([key, label]) =>
    `<tr><td>${label}</td><td>${escapeHtml(info[key] ?? '–')}</td></tr>`
  ).join('');
}

// ------------------------------------------------------------------ //
//  Enriched Blade Table — chassis-grouped + sortable                  //
// ------------------------------------------------------------------ //

// [key, label, width%]
const BLADE_COL_DEFS = [
  ['serverId',        'Server',          '5%' ],
  ['model',           'Model',           '8%' ],
  ['cpu_summary',     'CPU',             '17%'],
  ['mem_summary',     'Memory',          '10%'],
  ['storage_summary', 'Storage',         '7%' ],
  ['raid_summary',    'RAID',            '6%' ],
  ['_state',          'State / Power',   '8%' ],
  ['assignedToDn',    'Service Profile', '9%' ],
  ['_vcenter',        'vCenter',         '10%'],
  ['_assignment',     'שיוך',            '10%'],
  ['_cabinet',        'ארון / מיקום',    '10%'],
];

function groupedAndSortedBlades(data) {
  // Group by chassis number (first segment of serverId)
  const chassisMap = new Map();
  for (const row of data) {
    const ch = String(row.serverId ?? '').split('/')[0];
    if (!chassisMap.has(ch)) chassisMap.set(ch, []);
    chassisMap.get(ch).push(row);
  }

  // Sort chassis numerically
  const chassisKeys = [...chassisMap.keys()].sort((a, b) => parseInt(a) - parseInt(b));

  // Sort within each chassis by the active sort column
  const sortKey = bladeSort.col !== null ? BLADE_COL_DEFS[bladeSort.col][0] : null;

  if (sortKey) {
    for (const ch of chassisKeys) {
      chassisMap.get(ch).sort((a, b) => {
        let av, bv;
        if (sortKey === '_state') {
          av = a.operState ?? ''; bv = b.operState ?? '';
        } else if (sortKey === '_assignment') {
          av = (manualCache[a.serverId] || {}).assignment || '';
          bv = (manualCache[b.serverId] || {}).assignment || '';
        } else if (sortKey === '_cabinet') {
          av = (manualCache[a.serverId] || {}).cabinet || '';
          bv = (manualCache[b.serverId] || {}).cabinet || '';
        } else {
          av = String(a[sortKey] ?? ''); bv = String(b[sortKey] ?? '');
        }
        const cmp = av.localeCompare(bv, undefined, { numeric: true, sensitivity: 'base' });
        return bladeSort.dir === 'asc' ? cmp : -cmp;
      });
    }
  }

  return { chassisKeys, chassisMap };
}

function renderBladesTable(blades) {
  if (blades) bladeData = blades;

  const tbl   = document.getElementById('blades-table');
  const thead = tbl.querySelector('thead');
  const tbody = tbl.querySelector('tbody');

  // Colgroup for fixed-width columns
  tbl.querySelectorAll('colgroup').forEach(c => c.remove());
  const cg = document.createElement('colgroup');
  BLADE_COL_DEFS.forEach(([,, w]) => {
    const col = document.createElement('col');
    col.style.width = w;
    cg.appendChild(col);
  });
  tbl.insertBefore(cg, tbl.firstChild);

  // Sortable header
  thead.innerHTML = `<tr>${BLADE_COL_DEFS.map(([key, label], i) => {
    const active = bladeSort.col === i;
    const cls = 'sortable' + (active ? (bladeSort.dir === 'asc' ? ' sort-asc' : ' sort-desc') : '');
    return `<th class="${cls}" data-col="${i}">${label}</th>`;
  }).join('')}</tr>`;

  if (!bladeData || bladeData.length === 0) {
    tbody.innerHTML = `<tr><td colspan="${BLADE_COL_DEFS.length}" style="text-align:center;color:var(--muted)">No blade data</td></tr>`;
  } else {
    const { chassisKeys, chassisMap } = groupedAndSortedBlades(bladeData);
    const rows = [];
    let chassisIdx = 0;

    for (const ch of chassisKeys) {
      const group = chassisMap.get(ch);
      rows.push(
        `<tr class="chassis-header"><td colspan="${BLADE_COL_DEFS.length}">` +
        `&#x1F5C4;&nbsp; Chassis ${ch}` +
        `<span style="font-weight:400;font-size:0.78rem;opacity:0.65;margin-right:0.6rem"> — ${group.length} blade${group.length !== 1 ? 's' : ''}</span>` +
        `</td></tr>`
      );
      const altClass = chassisIdx % 2 === 0 ? 'chassis-a' : 'chassis-b';
      chassisIdx++;

      for (const row of group) {
        const manual  = manualCache[row.serverId] || {};
        const isM5    = /M5/i.test(row.model || '');
        const stCls   = /operable/i.test(row.operState || '')        ? 'badge-ok'
                      : /inoperable|error|fail/i.test(row.operState || '') ? 'badge-err'
                      : 'badge-warn';
        const pwrCls  = /^on$/i.test(row.operPower || '')  ? 'badge-ok'
                      : /^off$/i.test(row.operPower || '') ? 'badge-warn' : '';
        const cpuPfx  = row.numOfCpus ? `${row.numOfCpus}× ` : '';

        rows.push(`<tr class="${altClass}${isM5 ? ' row-m5' : ''}">
          <td style="font-weight:700;color:var(--accent)" title="${escapeAttr(row.serverId)}">${escapeHtml(row.serverId ?? '–')}</td>
          <td title="${escapeAttr(row.model)}">${escapeHtml(row.model ?? '–')}</td>
          <td title="${escapeAttr(cpuPfx + (row.cpu_summary ?? ''))}">${escapeHtml(cpuPfx + (row.cpu_summary ?? '–'))}</td>
          <td title="${escapeAttr(row.mem_summary)}">${escapeHtml(row.mem_summary ?? '–')}</td>
          <td title="${escapeAttr(row.storage_summary)}">${escapeHtml(row.storage_summary ?? '–')}</td>
          <td>${escapeHtml(row.raid_summary ?? '–')}</td>
          <td>
            <span class="badge ${stCls}">${escapeHtml(row.operState ?? '–')}</span>
            ${row.operPower ? `<span class="badge ${pwrCls}">${escapeHtml(row.operPower)}</span>` : ''}
          </td>
          <td title="${escapeAttr(row.assignedToDn)}">${escapeHtml(shortSP(row.assignedToDn ?? ''))}</td>
          <td><input class="editable-cell" type="text" placeholder="vCenter..."
              value="${escapeAttr(manual.vcenter || '')}"
              data-server="${escapeAttr(row.serverId)}" data-field="vcenter" /></td>
          <td><input class="editable-cell" type="text" placeholder="שיוך..."
              value="${escapeAttr(manual.assignment || '')}"
              data-server="${escapeAttr(row.serverId)}" data-field="assignment" /></td>
          <td><input class="editable-cell" type="text" placeholder="ארון / מיקום..."
              value="${escapeAttr(manual.cabinet || '')}"
              data-server="${escapeAttr(row.serverId)}" data-field="cabinet" /></td>
        </tr>`);
      }
    }
    tbody.innerHTML = rows.join('');
  }

  // Sort click handlers
  thead.querySelectorAll('th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const ci = parseInt(th.dataset.col);
      if (bladeSort.col === ci) { bladeSort.dir = bladeSort.dir === 'asc' ? 'desc' : 'asc'; }
      else                       { bladeSort.col = ci; bladeSort.dir = 'asc'; }
      renderBladesTable();
    });
  });

  // Input listeners
  tbl.querySelectorAll('.editable-cell').forEach(input => {
    input.addEventListener('input', e => {
      debouncedSave(e.target.dataset.server, e.target.dataset.field, e.target.value);
    });
  });
}

// ------------------------------------------------------------------ //
//  CSV Export                                                          //
// ------------------------------------------------------------------ //

function exportExcel(tableId, filename) {
  const tbl = document.getElementById(tableId);
  if (!tbl) return;

  const data = [];
  tbl.querySelectorAll('tr').forEach(tr => {
    if (tr.classList.contains('chassis-header')) return;
    const cells = [];
    tr.querySelectorAll('th, td').forEach(td => {
      const inp = td.querySelector('input');
      const raw = inp ? inp.value : td.textContent;
      const trimmed = raw.replace(/[\r\n]+/g, ' ').trim();
      // Try to parse numbers so Excel treats them as numbers
      const num = Number(trimmed);
      cells.push(trimmed !== '' && !isNaN(num) ? num : trimmed);
    });
    if (cells.length) data.push(cells);
  });

  const ws = XLSX.utils.aoa_to_sheet(data);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Sheet1');
  XLSX.writeFile(wb, filename);
}

function initExportButtons() {
  const maps = [
    ['blades-section',    'blades-table',    'blades'],
    ['fi-section',        'fi-table',        'fabric_interconnects'],
    ['racks-section',     'racks-table',     'rack_servers'],
    ['cpu-section',       'cpu-table',       'cpu_summary'],
    ['mem-section',       'mem-table',       'memory'],
    ['psu-section',       'psu-table',       'psu'],
    ['fans-section',      'fans-table',      'fans'],
    ['blade-ips-section', 'blade-ips-table', 'blade_ips'],
    ['firmware-section',  'firmware-table',  'firmware'],
    ['power-section',     'power-table',     'power_stats'],
    ['adapters-section',  'adapters-table',  'adapters'],
    ['vnics-section',     'vnics-table',     'vnics'],
    ['vhbas-section',     'vhbas-table',     'vhbas'],
    ['pools-section',     'pools-table',     'pools'],
    ['faults-section',    'faults-table',    'faults'],
  ];
  maps.forEach(([secId, tblId, name]) => {
    const sec = document.getElementById(secId);
    if (!sec) return;
    const toggle = sec.querySelector('.card-toggle');
    if (!toggle) return;
    const btn = document.createElement('button');
    btn.className = 'csv-btn';
    btn.title = 'Export to Excel';
    btn.textContent = '⬇ Export to Excel';
    btn.addEventListener('click', e => {
      e.stopPropagation();
      exportExcel(tblId, `${FARM.name}_${name}.xlsx`);
    });
    const right = toggle.querySelector('.card-toggle-right');
    if (right) {
      right.insertBefore(btn, right.querySelector('.toggle-btn'));
    } else {
      const tb = toggle.querySelector('.toggle-btn');
      if (tb) toggle.insertBefore(btn, tb);
    }
  });
}

// ------------------------------------------------------------------ //
//  Extended data loaders (firmware / power / network / pools)         //
// ------------------------------------------------------------------ //

async function loadExtendedData() {
  // Firmware
  try {
    const fw = await apiFetch('/firmware');
    buildAdvancedTable('firmware-table', 'firmware-filter', FIRMWARE_COLS, fw || []);
  } catch (e) { console.warn('Firmware load failed:', e); }

  // Power & temperature
  try {
    const ps = await apiFetch('/power-stats');
    buildAdvancedTable('power-table', null, POWER_COLS, ps || []);
  } catch (e) { console.warn('Power stats load failed:', e); }

  // Network adapters, vNIC, vHBA
  try {
    const net = await apiFetch('/network-adapters');
    buildAdvancedTable('adapters-table', 'adapters-filter', ADAPTER_COLS, net.adapters || []);
    buildAdvancedTable('vnics-table',    'vnics-filter',    VNIC_COLS,    net.vnics    || []);
    buildAdvancedTable('vhbas-table',    'vhbas-filter',    VHBA_COLS,    net.vhbas    || []);
  } catch (e) { console.warn('Network adapters load failed:', e); }

  // Pools
  try {
    const pools = await apiFetch('/pools');
    buildAdvancedTable('pools-table', null, POOL_COLS, pools || []);
  } catch (e) { console.warn('Pools load failed:', e); }
}

// ------------------------------------------------------------------ //
//  Manual data save (debounced 800 ms)                                 //
// ------------------------------------------------------------------ //

function debouncedSave(serverId, field, value) {
  if (!manualCache[serverId]) manualCache[serverId] = {};
  manualCache[serverId][field] = value;
  const key = `${serverId}|${field}`;
  clearTimeout(saveTimers[key]);
  saveTimers[key] = setTimeout(() => doSaveManual(serverId), 800);
}

async function doSaveManual(serverId) {
  const entry = manualCache[serverId] || {};
  try {
    await fetch(FARM.apiPrefix + '/manual-data', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        server_key: serverId,
        assignment: entry.assignment || '',
        cabinet:    entry.cabinet    || '',
        vcenter:    entry.vcenter    || '',
      }),
    });
    document.querySelectorAll('.editable-cell').forEach(el => {
      if (el.dataset.server === serverId) {
        el.classList.add('saved');
        setTimeout(() => el.classList.remove('saved'), 1500);
      }
    });
  } catch (err) {
    console.error('Failed to save manual data:', err);
  }
}

// ------------------------------------------------------------------ //
//  Main load                                                           //
// ------------------------------------------------------------------ //

async function loadAll() {
  setStatus(`Connecting to ${FARM.host} (${FARM.name})…`, 'checking');

  // Step 1: connectivity ping
  try {
    await apiFetch('/ping');
    setStatus(`Connected – ${FARM.host} – ${FARM.name}`, 'ok');
  } catch (err) {
    setStatus(`Connection failed: ${err.message}`, 'error');
    return;
  }

  // Step 2: summary – fast (KPIs + FI, racks, faults)
  try {
    const data = await apiFetch('/summary');
    renderKpi('val-fi',      data.counts?.fabric_interconnects);
    renderKpi('val-chassis', data.counts?.chassis);
    renderKpi('val-blades',  data.counts?.blade_servers);
    renderKpi('val-racks',   data.counts?.rack_servers);
    renderKpi('val-sp',      data.counts?.service_profiles);
    renderFaultPills(data.fault_summary ?? {});
    renderSystemTable(data.system ?? {});
    buildTable('fi-table',     FI_COLS,   data.fabric_interconnects ?? []);
    buildTable('racks-table',  RACK_COLS, data.rack_servers ?? []);
    buildTable('faults-table', FAULT_COLS, data.faults ?? []);
  } catch (err) {
    setStatus(`Data load error: ${err.message}`, 'error');
    return;
  }

  // Step 3: enriched blades + manual data (slower)
  const loadingEl = document.getElementById('blades-loading');
  if (loadingEl) loadingEl.style.display = 'block';
  try {
    const [enriched, manual] = await Promise.all([
      apiFetch('/blades/enriched'),
      apiFetch('/manual-data'),
    ]);
    manualCache = manual || {};
    renderBladesTable(enriched);
  } catch (err) {
    console.error('Blade detail load failed:', err);
  } finally {
    if (loadingEl) loadingEl.style.display = 'none';
  }

  // Step 4: hardware summary (CPU detail, memory, PSU, fans, IPs)
  loadHardwareSummary();

  // Step 5: firmware, power, network adapters, pools
  loadExtendedData();
}

// ------------------------------------------------------------------ //
//  Collapsible card toggle                                             //
// ------------------------------------------------------------------ //

function initCollapsibles() {
  document.querySelectorAll('.card-toggle').forEach(toggle => {
    toggle.addEventListener('click', e => {
      // Don't collapse when clicking inside a filter input or its label area
      if (e.target.closest('.filter-input')) return;
      if (e.target.tagName === 'INPUT') return;
      const bodyId = toggle.dataset.target;
      const body   = document.getElementById(bodyId);
      const card   = toggle.closest('.card');
      const btn    = toggle.querySelector('.toggle-btn');
      if (!body) return;

      const isCollapsed = body.style.display === 'none';
      body.style.display = isCollapsed ? '' : 'none';
      card.classList.toggle('collapsed', !isCollapsed);
      if (btn) btn.innerHTML = isCollapsed ? '&#x25B2;' : '&#x25BC;';
    });
  });
}

// Auto-load on page open
window.addEventListener('DOMContentLoaded', () => {
  initCollapsibles();
  initExportButtons();
  loadAll();
});
