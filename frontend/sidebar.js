// sidebar.js — Collapsible sidebar navigation
// Loaded by all dashboard pages.

function sbToggle() {
  document.body.classList.toggle('sb-collapsed');
  localStorage.setItem('sb-collapsed',
    document.body.classList.contains('sb-collapsed') ? '1' : '0');
}

function sbGroup(id) {
  const items = document.getElementById('items-' + id);
  const hdr   = document.getElementById('grp-' + id);
  if (items) items.classList.toggle('closed');
  if (hdr)   hdr.classList.toggle('open');
}
