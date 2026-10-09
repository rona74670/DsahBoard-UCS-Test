'use strict';

function sbToggle() {
  document.body.classList.toggle('sb-collapsed');
  localStorage.setItem('sb-collapsed', document.body.classList.contains('sb-collapsed') ? '1' : '0');
}

function sbThemeToggle() {
  var light = document.body.classList.toggle('light-mode');
  localStorage.setItem('cockpit_theme', light ? 'light' : 'dark');
  var btn = document.getElementById('hdr-theme-btn');
  if (btn) btn.textContent = light ? '\u2600' : '\u263D';
}

(function () {
  var s = document.createElement('style');
  s.textContent = [
    '#sb-user-bar{direction:ltr;display:flex;align-items:center;gap:0.4rem;',
    'padding:0.35rem 0.7rem;border-bottom:1px solid var(--border,#1e3550);flex-shrink:0;}',
    '.sb-user-badge{background:#6e40c9;color:#fff;border-radius:50%;width:22px;height:22px;',
    'font-size:0.7rem;font-weight:700;display:flex;align-items:center;justify-content:center;',
    'flex-shrink:0;text-transform:uppercase;}',
    '.sb-username-txt{flex:1;font-size:0.72rem;color:var(--muted,#8b949e);',
    'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
    '.sb-logout-btn{background:transparent;border:1px solid #30363d;color:var(--muted,#8b949e);',
    'border-radius:4px;padding:0.18rem 0.5rem;font-size:0.7rem;cursor:pointer;white-space:nowrap;}',
    '.sb-logout-btn:hover{border-color:#e63946;color:#e63946;}',
    '.sb-section{font-size:0.75rem;font-weight:700;letter-spacing:.07em;',
    'color:#58a6ff;text-transform:uppercase;padding:0.7rem 0.9rem 0.2rem;}',
    'body.sb-collapsed .sb-section{display:none!important;}',
    'body.sb-collapsed .sb-item{justify-content:center!important;padding:0.55rem!important;}',
    'body.sb-collapsed #sb-user-bar .sb-username-txt,',
    'body.sb-collapsed #sb-user-bar .sb-logout-btn{display:none!important;}',
    'body.sb-collapsed #sb-user-bar{justify-content:center!important;}',
    '#hdr-theme-btn{margin-left:auto;background:transparent;border:1px solid #30363d;',
    'color:var(--muted,#8b949e);border-radius:4px;padding:0.18rem 0.7rem;font-size:1.15rem;',
    'cursor:pointer;line-height:1.5;transition:border-color 0.15s,color 0.15s;flex-shrink:0;}',
    '#hdr-theme-btn:hover{border-color:var(--accent,#1f6feb);color:var(--accent,#1f6feb);}',

    '#ai-chat-btn{position:fixed;bottom:1.2rem;left:1.2rem;width:52px;height:52px;border-radius:50%;',
    'background:#1f6feb;color:#fff;border:none;font-size:1.4rem;cursor:pointer;z-index:9998;',
    'box-shadow:0 2px 10px rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;}',
    '#ai-chat-btn:hover{background:#388bfd;}',
    '#ai-chat-panel{position:fixed;bottom:5.2rem;left:1.2rem;width:340px;max-width:90vw;height:460px;',
    'max-height:70vh;background:var(--panel-bg,#161b22);border:1px solid var(--border,#30363d);',
    'border-radius:10px;box-shadow:0 4px 24px rgba(0,0,0,.45);display:none;flex-direction:column;',
    'z-index:9999;overflow:hidden;}',
    '#ai-chat-panel.open{display:flex;}',
    '#ai-chat-head{background:#1f6feb;color:#fff;padding:0.5rem 0.8rem;font-size:0.85rem;',
    'font-weight:700;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;}',
    '#ai-chat-head button{background:transparent;border:none;color:#fff;font-size:1.1rem;',
    'cursor:pointer;line-height:1;}',
    '#ai-chat-body{flex:1;overflow-y:auto;padding:0.6rem;font-size:0.82rem;',
    'display:flex;flex-direction:column;gap:0.5rem;}',
    '.ai-msg{max-width:85%;padding:0.4rem 0.6rem;border-radius:8px;white-space:pre-wrap;word-break:break-word;}',
    '.ai-msg.user{align-self:flex-end;background:#1f6feb;color:#fff;}',
    '.ai-msg.bot{align-self:flex-start;background:var(--card-bg,#0d1117);',
    'border:1px solid var(--border,#30363d);color:var(--fg,#e6edf3);}',
    '.ai-msg.pending{opacity:0.6;font-style:italic;}',
    '#ai-chat-form{display:flex;gap:0.4rem;padding:0.5rem;border-top:1px solid var(--border,#30363d);flex-shrink:0;}',
    '#ai-chat-input{flex:1;resize:none;height:2.2rem;border-radius:6px;border:1px solid var(--border,#30363d);',
    'background:var(--card-bg,#0d1117);color:var(--fg,#e6edf3);padding:0.35rem 0.5rem;font-size:0.82rem;}',
    '#ai-chat-send{background:#1f6feb;color:#fff;border:none;border-radius:6px;padding:0 0.8rem;cursor:pointer;}',
    '#ai-chat-send:disabled{opacity:0.5;cursor:default;}'

  ].join('');
  document.head.appendChild(s);

  function isAdmin() { return localStorage.getItem('cockpit_auth_role') === 'admin'; }

  function getUsername() {
    var u = localStorage.getItem('cockpit_username');
    if (u) return u;
    try { return JSON.parse(atob((localStorage.getItem('cockpit_auth_token')||'').split('.')[1])).sub || ''; }
    catch(e) { return ''; }
  }

  var path  = window.location.pathname;
  var user  = getUsername();
  var badge = user ? user[0].toUpperCase() : 'U';

  function a(href, icon, label) {
    var baseHref = String(href || '').split('#')[0];
    var cls = 'sb-item' + (path === baseHref ? ' active' : '');
    return '<a href="' + href + '" class="' + cls + '"><span class="sb-icon">' + icon + '</span><span class="sb-label">' + label + '</span></a>';
  }

  function section(label) { return '<div class="sb-section">' + label + '</div>'; }

  var nav = '';
  nav += section('Management');
  nav += a('/admin/overview', '&#x1F4CA;', 'Executive Summary');
  nav += section('vCenter');
  nav += a('/vcenter/overview', '&#x1F310;', 'Overview');
  nav += a('/vcenter/vm-create', '&#x1F195;', 'VM Create');
  nav += a('/vcenter/history',  '&#x1F551;', 'History');
  nav += a('/vcenter/perf',     '&#x1F4C8;', 'ביצועים (CPU/RAM)');
  nav += a('/vcenter/rightsizing', '&#x2696;&#xFE0F;', 'Right-Sizing');
  nav += a('/vcenter/reports','&#x1F4CA;', 'דוחות שינויים');
  nav += a('/vcenter/changes',  '&#x1F4CB;', 'Change Tracking');
  nav += a('/vcenter/pt',       '&#x1F5A5;', 'PT vCenter');
  nav += a('/vcenter/tc',       '&#x1F5A5;', 'TC vCenter');
  nav += a('/vcenter/tc8',      '&#x1F5A5;', 'TC vCenter8');
  nav += a('/vcenter/fattal',   '&#x1F5A5;', 'Fattal vCenter');
  nav += section('Backup');
  nav += a('/backup',         '&#x1F4BE;', 'Backup EM');
  nav += a('/backup/tc',        '&#x1F4BE;', 'TC Backup');
  nav += a('/backup/lifesaver', '&#x1F4BE;', 'Lifesaver Backup');
  nav += a('/backup/pt',        '&#x1F4BE;', 'PT Backup');
  nav += a('/backup/fattal',  '&#x1F4BE;', 'Fattal Backup');
  nav += section('DR');
  nav += a('/dr', '&#x21D4;', 'DR Dashboard');
  nav += section('Infinidat');
  nav += a('/infinidat/tc',     '&#x1F4BE;', 'TC iBox-03');
  nav += a('/infinidat/tc-old', '&#x1F4BE;', 'TC iBox (Old)');
  nav += a('/infinidat/pt',     '&#x1F4BE;', 'PT iBox');
  nav += section('UCS');
  nav += a('/',        '&#x2609;', 'TC Farm');
  nav += a('/pt',      '&#x2609;', 'PT Farm');
  nav += a('/fattal',  '&#x2609;', 'Fattal Farm');
  nav += a('/compare', '&#x1F4CA;', 'Compare');
  if (isAdmin()) {
    nav += section('Admin');
    nav += a('/admin/overview#sso', '&#9881;', 'SSO / SSL');
    nav += a('/admin/permissions', '&#x1F512;', 'ניהול הרשאות');
    nav += a('/admin/billing', '&#x1F4B0;', 'הגדרות חיוב');
    nav += a('/customers', '&#x1F465;', 'Customers');
    nav += a('/devices',   '&#x1F5C4;', 'Device Registry');
  }

  function buildSidebar() {
    var sb = document.getElementById('sidebar');
    if (!sb) return;

    var isLight = localStorage.getItem('cockpit_theme') === 'light';

    var toggleHtml =
      '<button id="sb-toggle" onclick="sbToggle()" title="Toggle sidebar">' +
        '<span class="sb-icon" style="font-size:1.1rem;">&#9776;</span>' +
      '</button>';

    var userBarHtml =
      '<div id="sb-user-bar">' +
        '<span class="sb-user-badge">' + badge + '</span>' +
        '<span class="sb-username-txt">' + (user || '') + '</span>' +
        '<button class="sb-logout-btn" onclick="window.cockpitLogout&&cockpitLogout()">Logout &#x23FB;</button>' +
      '</div>';

    sb.innerHTML = toggleHtml + userBarHtml + '<nav class="sb-nav">' + nav + '</nav>';

    // Inject theme toggle into the page header (top bar)
    var hdr = document.querySelector('header');
    if (hdr && !document.getElementById('hdr-theme-btn')) {
      var btn = document.createElement('button');
      btn.id = 'hdr-theme-btn';
      btn.title = 'Toggle light / dark mode';
      btn.textContent = isLight ? '\u2600' : '\u263D';
      btn.onclick = sbThemeToggle;
      hdr.appendChild(btn);
    }

    if (localStorage.getItem('sb-collapsed') === '1') document.body.classList.add('sb-collapsed');
  }

  // ── Floating AI assistant chat widget ─────────────────────────────────
  var aiHistory = [];
  var aiBusy = false;

  function aiGatherContext() {
    var el = document.querySelector('main, #content, .container') || document.body;
    var text = (el.innerText || '').trim().replace(/\s+\n/g, '\n');
    // A page can expose window.aiExtraContext(): structured data about what the user is looking at
    // (e.g. the last analysed server). It goes first and the page text fills the remaining budget.
    var extra = '';
    try { extra = (typeof window.aiExtraContext === 'function' ? window.aiExtraContext() : '') || ''; } catch (x) {}
    extra = extra.slice(0, 3500);
    var head = (extra ? 'STRUCTURED SERVER DATA:\n' + extra + '\n\nPAGE TEXT:\n' : '') + (document.title ? document.title + '\n' : '');
    return head + text.slice(0, Math.max(1000, 6000 - head.length));
  }

  function aiAppendMessage(role, text, pending) {
    var body = document.getElementById('ai-chat-body');
    if (!body) return null;
    var div = document.createElement('div');
    div.className = 'ai-msg ' + (role === 'user' ? 'user' : 'bot') + (pending ? ' pending' : '');
    div.textContent = text;
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
    return div;
  }

  function aiSend() {
    if (aiBusy) return;
    var input = document.getElementById('ai-chat-input');
    var msg = (input.value || '').trim();
    if (!msg) return;
    input.value = '';
    aiAppendMessage('user', msg);
    var pendingEl = aiAppendMessage('bot', '...', true);
    aiBusy = true;
    document.getElementById('ai-chat-send').disabled = true;

    fetch('/api/ai/chat', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': window.getCsrfToken ? window.getCsrfToken() : '',
      },
      body: JSON.stringify({ message: msg, history: aiHistory, context: aiGatherContext() }),
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        var reply = res.ok ? (res.d.reply || '') : ('שגיאה: ' + (res.d.detail || 'AI server unavailable'));
        pendingEl.textContent = reply;
        pendingEl.classList.remove('pending');
        if (res.ok) {
          aiHistory.push({ role: 'user', content: msg });
          aiHistory.push({ role: 'assistant', content: reply });
          if (aiHistory.length > 20) aiHistory = aiHistory.slice(-20);
        }
      })
      .catch(function () {
        pendingEl.textContent = 'שגיאה בתקשורת עם שרת ה-AI';
        pendingEl.classList.remove('pending');
      })
      .finally(function () {
        aiBusy = false;
        document.getElementById('ai-chat-send').disabled = false;
      });
  }

  function buildChatWidget() {
    if (document.getElementById('ai-chat-btn') || !getUsername()) return;

    var btn = document.createElement('button');
    btn.id = 'ai-chat-btn';
    btn.title = 'עוזר AI';
    btn.textContent = '\uD83E\uDD16';
    document.body.appendChild(btn);

    var panel = document.createElement('div');
    panel.id = 'ai-chat-panel';
    panel.innerHTML =
      '<div id="ai-chat-head"><span>עוזר AI</span><button id="ai-chat-close">&times;</button></div>' +
      '<div id="ai-chat-body"></div>' +
      '<form id="ai-chat-form">' +
        '<textarea id="ai-chat-input" placeholder="שאל/י על חומרה, משאבים או המלצות..."></textarea>' +
        '<button type="submit" id="ai-chat-send">שלח</button>' +
      '</form>';
    document.body.appendChild(panel);

    aiAppendMessage('bot', 'שלום! אפשר לשאול אותי על חומרה, משאבים והמלצות בהתאם לנתונים בדשבורד.');

    btn.onclick = function () { panel.classList.toggle('open'); };
    document.getElementById('ai-chat-close').onclick = function () { panel.classList.remove('open'); };
    document.getElementById('ai-chat-form').onsubmit = function (e) { e.preventDefault(); aiSend(); };
    document.getElementById('ai-chat-input').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); aiSend(); }
    });
  }

  window.addEventListener('cockpit-auth-updated', buildSidebar);
  window.addEventListener('cockpit-auth-updated', buildChatWidget);

  if (localStorage.getItem('cockpit_theme') === 'light') document.body.classList.add('light-mode');
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildSidebar);
    document.addEventListener('DOMContentLoaded', buildChatWidget);
  } else {
    buildSidebar();
    buildChatWidget();
  }
})();
