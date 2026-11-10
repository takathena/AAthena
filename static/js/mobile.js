/* ============================================================
   AAguard Mobile v8.0 — Batch 1-9 synced with desktop
   ============================================================ */
const getCsrf = () => (document.querySelector('meta[name="csrf-token"]')||{}).content||'';
const csrf = () => getCsrf();
const escAttr = s => String(s ?? '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

let __deviceDelegated = false;
function bindDeviceActions(){
  if(__deviceDelegated) return;
  __deviceDelegated = true;
  document.addEventListener('click', e => {
    const el = e.target.closest('[data-action]');
    if(!el || el.dataset.action === 'view-device' || el.dataset.action === 'acknowledge') return;
    const id = el.dataset.deviceId;
    if(!id) return;
    if(el.dataset.action === 'open'){ openDevice(id); }
    else if(el.dataset.action === 'sheet'){ e.stopPropagation(); openSheet(id); }
    else if(el.dataset.action === 'map'){ selectMapDevice(id); }
  });
}
bindDeviceActions();

/* Skip link + date/history filters: bound via JS (no inline handlers, CSP-safe). */
const skipLink = document.getElementById('skipLink');
skipLink?.addEventListener('focus', () => { skipLink.style.left = '0'; });
skipLink?.addEventListener('blur', () => { skipLink.style.left = '-9999px'; });
document.getElementById('alertDateStart')?.addEventListener('change', () => applyAlertDateFilter());
document.getElementById('alertDateEnd')?.addEventListener('change', () => applyAlertDateFilter());
document.getElementById('historyDeviceFilter')?.addEventListener('change', () => loadAlertHistory());
document.getElementById('historySeverityFilter')?.addEventListener('change', () => loadAlertHistory());

async function api(url, opts = {}){
  const m = (opts.method||'GET').toUpperCase();
  const h = { 'Accept':'application/json', ...(opts.headers||{}) };
  if(opts.body && !h['Content-Type']) h['Content-Type'] = 'application/json';
  if(['POST','PUT','DELETE','PATCH'].includes(m)) h['X-CSRFToken'] = csrf();
  const dashScope = ((document.querySelector('meta[name="dashboard-id"]')||{}).content||'').trim();
  if(dashScope && String(url).startsWith('/api/v1/') && !h['X-Dashboard-Id']) h['X-Dashboard-Id'] = dashScope;
  const res = await fetch(url, { ...opts, method:m, headers:h, credentials:'same-origin' });
  if(res.status === 401){
    try{ sessionStorage.removeItem('aaguard_back_url'); sessionStorage.removeItem('aaguard-last-section'); }catch(_){}
    if(!(window.location.pathname||'').startsWith('/login')) window.location.href = '/login';
  }
  return res;
}

/* ===== State ===== */
let devices = [];
let filterDash = 'all', filterDev = 'all';
let charts = [], timeMinutes = 1440;
let dashboardId = null, currentTabId = null, tabs = [];
let alerts = [], alertStatus = 'all', alertSev = '', alertSearch = '';
let alertDateStart = '', alertDateEnd = '';
let alertSelectedIds = new Set();
let sheetDeviceId = null;
let pendingRedirect = null;

// Map
let map = null, mapMarkers = {}, mapReady = false;
let selDeviceId = null, selLat = null, selLng = null, selMarker = null, mapDirty = false;
let mapFilter = 'all', mapSearch = '';
const MAP_DEFAULT_CENTER = [-2.5489, 118.0149];
const MAP_DEFAULT_ZOOM = 5;

// User / Dashboard / Admin state
let currentUser = null;
let dashboardsList = [], currentDashboardId = null, currentDashboardName = '', currentDashboardIcon = 'fa-layer-group';
let userListCache = [];
let bulkImportParsed = [];
let trendHours = 24;
let mobileTrendChart = null;

const DATA_KEYS = {
  temperature:{label:'Suhu',unit:'°C',color:'#f97316'},
  humidity:{label:'Kelembaban',unit:'%',color:'#3b82f6'},
  gas_level:{label:'Gas',unit:'ppm',color:'#ef4444'},
  smoke:{label:'Asap',unit:'ppm',color:'#8b5cf6'},
};

const PRESETS = {
  temperature:{label:'Suhu',defaults:{healthy:{min:20,max:26},warning:{min:15,max:30},danger:{min:10,max:35}}},
  humidity:{label:'Kelembaban',defaults:{healthy:{min:40,max:70},warning:{min:30,max:80},danger:{min:20,max:90}}},
  gas_level:{label:'Level Gas',defaults:{healthy:{min:0,max:70},warning:{min:0,max:85},danger:{min:0,max:100}}},
  smoke:{label:'Asap',defaults:{healthy:{min:0,max:50},warning:{min:0,max:70},danger:{min:0,max:100}}},
};

const SENSOR_LABELS = {
  temperature:'Suhu',humidity:'Kelembaban',gas_level:'Gas',smoke:'Asap',
};
const SENSOR_UNITS = {
  temperature:'°C',humidity:'%',gas_level:'ppm',smoke:'ppm',
};

const COLORS = ['#f97316','#22c55e','#ef4444','#8b5cf6','#3b82f6','#14b8a6','#f59e0b','#ec4899'];
const CHART_FONT = "'Geist', -apple-system, sans-serif";

/* ===== Helpers ===== */
const esc = s => { const d = document.createElement('div'); d.textContent = String(s ?? ''); return d.innerHTML; };
const fmtUp = s => {
  if(!s) return '-';
  s = parseInt(s)||0;
  const d = Math.floor(s/86400), h = Math.floor((s%86400)/3600), m = Math.floor((s%3600)/60);
  if(d>0) return `${d}h ${h}j`;
  if(h>0) return `${h}j ${m}m`;
  return `${m}m`;
};
const parseTs = iso => {
  if(!iso) return null;
  try{ return new Date(String(iso).replace(' ','T')+'+07:00'); }catch(e){ return null; }
};
const fmtTime = iso => {
  const d = parseTs(iso); if(!d) return '-';
  try{ return d.toLocaleTimeString('id-ID',{hour:'2-digit',minute:'2-digit',timeZone:'Asia/Jakarta'}); }
  catch(e){ return '-'; }
};
const fmtRelative = iso => {
  const d = parseTs(iso); if(!d) return '-';
  const diff = (Date.now() - d.getTime())/1000;
  if(diff < 60) return 'baru saja';
  if(diff < 3600) return `${Math.floor(diff/60)}m lalu`;
  if(diff < 86400) return `${Math.floor(diff/3600)}j lalu`;
  if(diff < 604800) return `${Math.floor(diff/86400)}h lalu`;
  return d.toLocaleDateString('id-ID',{day:'2-digit',month:'short',timeZone:'Asia/Jakarta'});
};
const deviceStatus = d => {
  if(d.status === 'offline') return 'offline';
  if(d.has_alert && d.top_alert_severity) return d.top_alert_severity;
  return d.status || 'offline';
};
const alertTypeLabel = type => {
  const map = {temperature:'Suhu',humidity:'Kelembaban',gas_level:'Gas',offline:'Offline',smoke:'Asap'};
  return map[type] || String(type||'').replace(/_/g,' ').replace(/\b\w/g,l=>l.toUpperCase());
};
const formatVal = (type, value) => {
  if(value === null || value === undefined) return null;
  const unit = SENSOR_UNITS[type] ?? '';
  const num = parseFloat(value);
  if(isNaN(num)) return String(value);
  return `${parseFloat(num.toFixed(2))}${unit}`;
};
const ackIdOf = a => a.alert_id != null ? a.alert_id : a.id;

function toast(msg){
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => {
    t.style.opacity = '0';
    t.style.transition = 'opacity .3s';
    setTimeout(() => t.remove(), 300);
  }, 1800);
}

function confirmModal(title, message, onConfirm){
  const modal = document.getElementById('m-confirm');
  document.getElementById('confirmTitle').textContent = title;
  document.getElementById('confirmMessage').textContent = message;
  const btn = document.getElementById('confirmActionBtn');
  const newBtn = btn.cloneNode(true);
  btn.parentNode.replaceChild(newBtn, btn);
  newBtn.addEventListener('click', () => {
    closeModal('m-confirm');
    onConfirm();
  });
  openModal('m-confirm');
}

/* ===== Drawer Nav ===== */
function openDrawer(){
  const d = document.getElementById('drawer');
  const b = document.getElementById('drawerBackdrop');
  if(d){ d.classList.add('open'); d.setAttribute('aria-hidden', 'false'); }
  if(b) b.classList.add('active');
  const m = document.getElementById('menuBtn'); if(m) m.setAttribute('aria-expanded', 'true');
  document.body.classList.add('drawer-open');
}
function closeDrawer(){
  const d = document.getElementById('drawer');
  const b = document.getElementById('drawerBackdrop');
  if(d){ d.classList.remove('open'); d.setAttribute('aria-hidden', 'true'); }
  if(b) b.classList.remove('active');
  const m = document.getElementById('menuBtn'); if(m) m.setAttribute('aria-expanded', 'false');
  document.body.classList.remove('drawer-open');
}
document.addEventListener('keydown', e => {
  if(e.key === 'Escape') closeDrawer();
});

/* ===== Modal ===== */
let __lastFocused = null;
function openModal(id){
  const el = document.getElementById(id);
  if(!el) return;
  __lastFocused = document.activeElement;
  el.classList.add('open');
  document.body.classList.add('modal-open');
  const f = el.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
  if(f) f.focus();
}
function closeModal(id){
  const el = document.getElementById(id);
  if(el) el.classList.remove('open');
  if(!document.querySelector('.modal.open')) document.body.classList.remove('modal-open');
  if(__lastFocused && document.contains(__lastFocused)) __lastFocused.focus();
  __lastFocused = null;
}
document.querySelectorAll('.modal').forEach(m => {
  m.addEventListener('click', e => { if(e.target === m) closeModal(m.id); });
});
document.addEventListener('keydown', e => {
  if(e.key === 'Escape'){
    document.querySelectorAll('.modal.open').forEach(m => closeModal(m.id));
    document.querySelectorAll('.ios-dd.open').forEach(m => m.classList.remove('open'));
  }
});

/* ===== Theme ===== */
updateThemeIcon();
window.ThemeManager.onChange(function(){
  updateThemeIcon();
  const analytics = document.getElementById('s-analytics');
  if(analytics && analytics.classList.contains('active')) loadCharts();
  if(typeof mobileTrendChart !== 'undefined' && mobileTrendChart) loadMobileTrend();
});
function updateThemeIcon(){
  const i = document.getElementById('themeIcon');
  if(i) i.className = document.documentElement.getAttribute('data-theme') === 'light'
    ? 'fa-solid fa-sun' : 'fa-solid fa-moon';
}

/* ===== Nav ===== */
function go(name, opts = {}){
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  const el = document.getElementById('s-' + name);
  if(el) el.classList.add('active');

  document.querySelectorAll('.drawer-item[data-tab]').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === name);
  });

  if(opts.filter) setFilterFull(opts.filter);
  closeDrawer();

  if(name === 'dashboard'){ loadDashboard(); loadActivity(); }
  else if(name === 'map') setTimeout(() => { if(window.AAGuardLazy) window.AAGuardLazy.loadMapLibs().then(()=> initMap()).catch(()=> initMap()); else initMap(); }, 100);
  else if(name === 'analytics') { const loadAnalytics = ()=> loadTabs().then(() => { if(currentTabId) loadCharts(); }); if(window.AAGuardLazy) window.AAGuardLazy.loadChartLibs().then(loadAnalytics).catch(()=>{ const cl=document.getElementById('chartsList'); if(cl) cl.innerHTML='<div class="empty" style="padding:30px;"><div class="empty-title">Chart.js gagal dimuat. Cek koneksi lalu buka lagi Analitik.</div></div>'; }); else loadAnalytics(); }
  else if(name === 'devices') renderDevicesFull();
  else if(name === 'alerts') loadAlerts();

  window.scrollTo({ top: 0, behavior: 'smooth' });
}
async function doLogout(){
  try{
    await fetch('/logout', { method:'POST', credentials:'same-origin', headers:{ 'X-CSRFToken': csrf() } });
    window.location.href = '/login';
  }catch(e){
    if(window.showToast) window.showToast('Gagal logout. Periksa koneksi lalu coba lagi.', 'error');
  }
}
function logout(){ confirmModal('Logout', 'Yakin ingin keluar dari AAguard?', () => { doLogout(); }); }
function openDevice(id){
  try{ sessionStorage.setItem('aaguard_back_url', '/mobile'); }catch(e){}
  window.location.href = '/device/' + encodeURIComponent(id);
}

/* ===== Izin — backend tetap sumber kebenaran ===== */
let permState = { loaded:false, isAdmin:false, perms:[] };
function hasPerm(p){
  if(!permState.loaded) return true;               // belum tahu: biarkan server memutuskan
  return permState.isAdmin || permState.perms.includes(p);
}
function applyPermGates(){
  document.querySelectorAll('[data-perm]').forEach(el => {
    const ok = hasPerm(el.getAttribute('data-perm'));
    el.style.display = ok ? '' : 'none';
  });
}

/* ===== User info + admin visibility ===== */
async function loadCurrentUser(){
  try{
    const r = await api('/api/v1/users/me');
    const d = await r.json();
    if(d.success && d.user){
      currentUser = d.user;
      const isAdmin = d.user.is_admin === true;
      permState = { loaded:true, isAdmin, perms: d.user.permissions || [] };
      applyPermGates();
      // Backend tetap sumber kebenaran (403); ini hanya menyembunyikan kontrol.
      document.body.classList.toggle('is-non-admin', !isAdmin);
      const adminSection = document.getElementById('adminSection');
      const adminItem = document.querySelector('.drawer-admin-item');
      if(adminSection) adminSection.style.display = isAdmin ? '' : 'none';
      if(adminItem) adminItem.style.display = isAdmin ? '' : 'none';
      const bulkBtn = document.getElementById('bulkImportBtnM');
      if(bulkBtn) bulkBtn.style.display = isAdmin ? '' : 'none';
    }
  }catch(e){ console.warn(e); }
}

/* ===== Dashboard ===== */
async function loadDashboard(){
  try{
    const r = await api('/api/v1/dashboard');
    const d = await r.json();
    if(!d.success) return;
    devices = d.devices || [];

    const total = d.summary.total_devices || 0;
    const online = d.summary.online_devices || 0;
    const offline = d.summary.offline_devices || 0;
    const alertCount = d.summary.active_alerts || 0;

    document.getElementById('sTotal').textContent = total;
    document.getElementById('sOnline').textContent = online;
    document.getElementById('sOffline').textContent = offline;
    document.getElementById('sAlert').textContent = alertCount;

    const deviceBadge = document.getElementById('drawerDeviceBadge');
    if(deviceBadge){
      deviceBadge.textContent = total;
      deviceBadge.style.display = total > 0 ? '' : 'none';
    }
    const alertBadge = document.getElementById('drawerAlertBadge');
    if(alertBadge){
      alertBadge.textContent = alertCount;
      alertBadge.style.display = alertCount > 0 ? '' : 'none';
    }

    updateRing(d.summary);
    updateCounts();
    renderDevices();
    renderDevicesFull();
    updateActiveDashboardBanner();
  }catch(e){ console.error(e); }
}
function updateRing(s){
  const healthy = s.healthy_devices ?? 0, total = s.total_devices ?? 0;
  const pct = total > 0 ? Math.round((healthy/total)*100) : 0;
  const circ = 2*Math.PI*42, offset = circ - (pct/100)*circ;
  const ring = document.getElementById('ringProg');
  if(ring){ ring.setAttribute('stroke-dasharray', circ.toFixed(1)); ring.style.strokeDashoffset = offset; }
  document.getElementById('ringPct').textContent = pct + '%';
  document.getElementById('ringTitle').textContent = total > 0 ? `${healthy} perangkat sehat` : 'Belum ada perangkat';
  document.getElementById('ringSub').textContent = total > 0
    ? `dari ${total} perangkat terdaftar`
    : 'Tambahkan perangkat untuk memulai monitoring';
}
function updateCounts(){
  const online = devices.filter(d => d.status === 'online').length;
  const offline = devices.filter(d => d.status === 'offline').length;
  const alert = devices.filter(d => d.has_alert === true).length;
  document.getElementById('cAll').textContent = devices.length;
  document.getElementById('cOnline').textContent = online;
  document.getElementById('cOffline').textContent = offline;
  document.getElementById('cAlert').textContent = alert;
  document.getElementById('deviceCountSub').textContent = `${devices.length} perangkat terdaftar`;
  document.getElementById('deviceSubFull').textContent = `${devices.length} perangkat`;
}

function setFilter(f){
  filterDash = f;
  document.querySelectorAll('#filterChips .chip').forEach(c => c.classList.toggle('active', c.dataset.f === f));
  renderDevices();
}
function setFilterFull(f){
  filterDev = f;
  document.querySelectorAll('#deviceChips .chip').forEach(c => c.classList.toggle('active', c.dataset.f === f));
  renderDevicesFull();
}
function filterList(list, f){
  if(f === 'online') return list.filter(d => d.status === 'online');
  if(f === 'offline') return list.filter(d => d.status === 'offline');
  if(f === 'alert') return list.filter(d => d.has_alert === true);
  return list;
}
function renderDevices(){ renderDeviceRows(filterList(devices, filterDash), 'deviceList'); }
function renderDevicesFull(){ renderDeviceRows(filterList(devices, filterDev), 'deviceListFull'); }

function renderDeviceRows(list, targetId){
  const c = document.getElementById(targetId);
  if(!c) return;
  if(!list.length){
    c.innerHTML = '<div class="empty"><i class="fa-solid fa-microchip"></i><div class="empty-title">Tidak ada perangkat</div></div>';
    return;
  }
  c.innerHTML = list.map(d => {
    const st = deviceStatus(d);
    const type = d.device_type || 'Universal';
    const loc = d.location || d.latest_wifi_ssid || '—';
    const uptime = fmtUp(d.latest_uptime_seconds || 0);
    return `<div class="row" data-action="open" data-device-id="${escAttr(d.device_id)}">
      <span class="row-status ${st}"></span>
      <div class="row-main">
        <div class="row-title">${esc(d.device_name)}</div>
        <div class="row-sub"><span class="badge-type">${esc(type)}</span>${esc(d.device_id)} · ${esc(loc)} · ${uptime}</div>
      </div>
      <button class="row-more" data-action="sheet" data-device-id="${escAttr(d.device_id)}">
        <i class="fa-solid fa-ellipsis"></i>
      </button>
    </div>`;
  }).join('');
}

/* ===== Activity ===== */
async function loadActivity(){
  const c = document.getElementById('activityList');
  if(!c) return;
  try{
    const r = await api('/api/v1/alerts/all?limit=15');
    const d = await r.json();
    const events = [];
    if(d.success && Array.isArray(d.alerts)){
      d.alerts.slice(0,8).forEach(a => events.push({
        sev: a.severity || 'info',
        title: a.device_name || a.device_id,
        msg: a.message || a.alert_type,
        ts: a.created_at,
        dev: a.device_id
      }));
    }
    devices.forEach(x => {
      if(!x.last_seen) return;
      events.push({
        sev: x.status === 'online' ? 'online' : 'offline',
        title: x.device_name,
        msg: x.status === 'online' ? 'Baru saja online' : 'Terakhir terlihat',
        ts: x.last_seen,
        dev: x.device_id
      });
    });
    events.sort((a,b) => new Date(b.ts) - new Date(a.ts));
    const top = events.slice(0, 8);
    if(!top.length){
      c.innerHTML = '<div class="empty" style="padding:30px;"><div class="empty-title">Belum ada aktivitas</div></div>';
      return;
    }
    const icons = {danger:'fa-fire',warning:'fa-triangle-exclamation',info:'fa-circle-info',online:'fa-circle-check',offline:'fa-power-off'};
    c.innerHTML = top.map(ev => `
      <div class="activity-item" data-action="open" data-device-id="${escAttr(ev.dev)}">
        <div class="activity-icon ${ev.sev}"><i class="fa-solid ${icons[ev.sev] || 'fa-bell'}"></i></div>
        <div class="activity-body">
          <div class="activity-text"><strong>${esc(ev.title)}</strong> — ${esc(String(ev.msg).slice(0,70))}</div>
          <div class="activity-time">${fmtTime(ev.ts)}</div>
        </div>
      </div>
    `).join('');
  }catch(e){ c.innerHTML = '<div class="empty" style="padding:30px;"><div class="empty-title">Gagal memuat</div></div>'; }
}

/* ===== Map ===== */
// Leaflet must re-measure after display/layout settles
function invalidateMap(){
  if(!map) return;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    try{ map.invalidateSize(); }catch(e){}
  }));
  setTimeout(() => { try{ map.invalidateSize(); }catch(e){} }, 200);
}
function initMap(force){
  if(mapReady && !force){
    invalidateMap();
    return;
  }
  if(force && map){ try{ map.remove(); }catch(e){} map = null; mapMarkers = {}; mapReady = false; }
  const el = document.getElementById('mMapFull'); if(!el) return;
  // Leaflet lazy-load saat section peta dibuka; fallback bila offline
  if(typeof L === 'undefined'){
    el.innerHTML = '<div class="empty" style="padding:30px;"><div class="empty-title">Gagal memuat peta (offline?). Cek koneksi lalu buka lagi section Peta.</div></div>';
    return;
  }
  map = L.map('mMapFull', {zoomControl:true, attributionControl:false}).setView(MAP_DEFAULT_CENTER, MAP_DEFAULT_ZOOM);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:19}).addTo(map);
  map.on('click', e => { if(selDeviceId) placeMarker(e.latlng.lat, e.latlng.lng); });
  mapReady = true;
  if(!window.__aaguardMaps) window.__aaguardMaps = [];
  if(!window.__aaguardMaps.includes(map)) window.__aaguardMaps.push(map);
  invalidateMap();
  loadMapMarkers(); renderMapList();
}
window.addEventListener('resize', () => {
  clearTimeout(window.__mMapResizeTO);
  window.__mMapResizeTO = setTimeout(() => { if(map) try{ map.invalidateSize(); }catch(e){} }, 150);
});
function resetMapView(){
  if(!map) return;
  map.flyTo(MAP_DEFAULT_CENTER, MAP_DEFAULT_ZOOM, {duration:.8});
  if(selMarker){ try{ map.removeLayer(selMarker); }catch(e){} selMarker = null; }
  selDeviceId = null; selLat = null; selLng = null; mapDirty = false;
  updateMapBanner();
  toast('View direset');
}
function mapStyle(d){
  if(d.status === 'offline') return {color:'#ef4444', label:'OFF'};
  if(d.has_alert && d.top_alert_severity){
    if(d.top_alert_severity === 'danger') return {color:'#ef4444', label:'ALERT'};
    if(d.top_alert_severity === 'warning') return {color:'#f97316', label:'WARN'};
    if(d.top_alert_severity === 'info') return {color:'#8b5cf6', label:'INFO'};
  }
  if(d.status === 'online') return {color:'#22c55e', label:'ON'};
  return {color:'#737373', label:'—'};
}
function loadMapMarkers(){
  if(!map || typeof L === 'undefined') return;
  Object.values(mapMarkers).forEach(m => { try{ map.removeLayer(m); }catch(e){} });
  mapMarkers = {};
  devices.forEach(d => {
    if(!d.latitude || !d.longitude || (d.latitude === 0 && d.longitude === 0)) return;
    const s = mapStyle(d);
    const m = L.circleMarker([d.latitude,d.longitude], {radius:7, color:s.color, fillColor:s.color, fillOpacity:.9, weight:2}).addTo(map);
    m.bindPopup(`<b>${esc(d.device_name)}</b><br><span style="font-size:11px;color:#888;">${esc(d.device_id)}</span>`);
    mapMarkers[d.device_id] = m;
  });
}
function setMapFilter(f){
  mapFilter = f;
  document.querySelectorAll('#mapChips .chip').forEach(c => c.classList.toggle('active', c.dataset.mf === f));
  renderMapList();
}
document.getElementById('mapSearch').addEventListener('input', e => {
  mapSearch = e.target.value.toLowerCase().trim(); renderMapList();
});
function renderMapList(){
  const c = document.getElementById('mapList'); if(!c) return;
  let list = devices.slice();
  if(mapFilter === 'online') list = list.filter(d => d.status === 'online');
  else if(mapFilter === 'offline') list = list.filter(d => d.status === 'offline');
  else if(mapFilter === 'alert') list = list.filter(d => d.has_alert === true);
  if(mapSearch) list = list.filter(d =>
    (d.device_name||'').toLowerCase().includes(mapSearch) ||
    (d.device_id||'').toLowerCase().includes(mapSearch));

  if(!list.length){
    c.innerHTML = '<div class="empty"><i class="fa-solid fa-map"></i><div class="empty-title">Tidak ada device</div></div>';
    return;
  }
  c.innerHTML = list.map(d => {
    const s = mapStyle(d);
    const hasLoc = d.latitude && d.longitude && !(d.latitude === 0 && d.longitude === 0);
    return `<div class="row" data-action="map" data-device-id="${escAttr(d.device_id)}">
      <span class="row-status" style="background:${s.color};box-shadow:0 0 0 3px ${s.color}22;"></span>
      <div class="row-main">
        <div class="row-title">${esc(d.device_name)}</div>
        <div class="row-sub">${esc(d.device_id)}${!hasLoc ? ' · belum ada lokasi' : ''}</div>
      </div>
      <i class="fa-solid fa-chevron-right row-chevron"></i>
    </div>`;
  }).join('');
}
function selectMapDevice(id){
  const d = devices.find(x => x.device_id === id); if(!d) return;
  selDeviceId = id; mapDirty = false;
  selLat = null; selLng = null;
  const hasLoc = d.latitude && d.longitude && !(d.latitude === 0 && d.longitude === 0);
  if(hasLoc){
    selLat = d.latitude; selLng = d.longitude;
    if(map) map.flyTo([d.latitude,d.longitude], 14, {duration:.8});
  } else if(map){
    const c = map.getCenter();
    placeMarker(c.lat, c.lng);
  }
  updateMapBanner(); renderMapList();
}
function placeMarker(lat, lng){
  if(!map) return;
  selLat = lat; selLng = lng;
  if(selMarker) selMarker.setLatLng([lat,lng]);
  else{
    selMarker = L.marker([lat,lng], {draggable:true}).addTo(map);
    selMarker.on('dragend', e => {
      const p = e.target.getLatLng();
      selLat = p.lat; selLng = p.lng; mapDirty = true; updateMapBanner();
    });
  }
  mapDirty = true; updateMapBanner();
}
function updateMapBanner(){
  const b = document.getElementById('mapBanner');
  if(!selDeviceId){ b.classList.add('hidden'); invalidateMap(); return; }
  const d = devices.find(x => x.device_id === selDeviceId); if(!d){ b.classList.add('hidden'); invalidateMap(); return; }
  const s = mapStyle(d);
  b.classList.remove('hidden');
  document.getElementById('mapBannerName').textContent = d.device_name;
  document.getElementById('mapBannerDot').style.background = s.color;
  const coordEl = document.getElementById('mapBannerCoord');
  coordEl.innerHTML = selLat != null
    ? `${selLat.toFixed(5)}, ${selLng.toFixed(5)}${mapDirty ? ' · belum disimpan' : ''}`
    : 'Belum ada koordinat';
  document.getElementById('mapSaveBtn').disabled = !(selLat != null && mapDirty);
  invalidateMap();
}
function clearMapSel(){
  if(mapDirty && !confirm('Batalkan perubahan?')) return;
  selDeviceId = null; selLat = null; selLng = null; mapDirty = false;
  if(selMarker && map){ map.removeLayer(selMarker); selMarker = null; }
  updateMapBanner(); renderMapList();
}
async function saveMapLoc(){
  if(!selDeviceId || selLat == null) return;
  const r = await api(`/api/v1/devices/${encodeURIComponent(selDeviceId)}`, {
    method:'PUT', body:JSON.stringify({latitude:selLat, longitude:selLng})
  });
  const d = await r.json();
  if(d.success){
    const dev = devices.find(x => x.device_id === selDeviceId);
    if(dev){ dev.latitude = selLat; dev.longitude = selLng; }
    mapDirty = false; updateMapBanner(); loadMapMarkers(); toast('Lokasi tersimpan');
  } else alert(d.error || 'Gagal');
}

/* ==========================================
   iOS Custom Dropdown
   ========================================== */
function bindIosDD(id, onChange) {
  const dd = document.getElementById(id);
  if (!dd) return;
  const trigger = dd.querySelector('.ios-dd-trigger');
  const label = dd.querySelector('.ios-dd-label');
  const items = dd.querySelectorAll('.ios-dd-item');
  if (!trigger || !label) return;

  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    document.querySelectorAll('.ios-dd.open').forEach(el => {
      if (el !== dd) el.classList.remove('open');
    });
    dd.classList.toggle('open');
  });

  items.forEach(item => {
    item.addEventListener('click', (e) => {
      e.stopPropagation();
      const value = item.dataset.value || item.dataset.min || '';
      const textEl = item.querySelector('span');
      const text = textEl ? textEl.textContent.trim() : '';
      dd.dataset.value = value;
      label.textContent = text;
      items.forEach(i => i.classList.toggle('active', i === item));
      dd.classList.remove('open');
      if (typeof onChange === 'function') onChange(value, text);
    });
  });
}

document.addEventListener('click', (e) => {
  if (!e.target.closest('.ios-dd')) {
    document.querySelectorAll('.ios-dd.open').forEach(el => el.classList.remove('open'));
  }
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.ios-dd.open').forEach(el => el.classList.remove('open'));
  }
});

/* ===== Analytics ===== */
let __analyticsBound = false;
function bindAnalyticsDropdowns() {
  if (__analyticsBound) return;
  __analyticsBound = true;

  bindIosDD('timeDD', (val) => {
    const m = parseInt(val) || 1440;
    timeMinutes = m;
    const label = m < 60 ? `${m} Menit` :
                  m < 1440 ? `${Math.round(m/60)} Jam` :
                  m < 10080 ? `${Math.round(m/1440)} Hari` :
                  m < 43200 ? `${Math.round(m/10080)} Minggu` :
                  `${Math.round(m/43200)} Bulan`;
    const lbl = document.getElementById('timeLabel');
    if (lbl) lbl.textContent = label;
    loadCharts();
  });
}
bindAnalyticsDropdowns();

async function loadTabs(){
  try{
    const r = await api('/api/v1/dashboards');
    const d = await r.json();
    if(!d.success || !d.dashboards.length){ tabs = []; return; }
    const def = d.dashboards.find(x => x.id === currentDashboardId)
             || d.dashboards.find(x => x.is_default)
             || d.dashboards[0];
    dashboardId = def.id;
    currentDashboardId = def.id;
    currentDashboardName = def.name;
    currentDashboardIcon = def.icon || 'fa-layer-group';
    const tr = await api(`/api/v1/dashboards/${def.id}/analytics-tabs`);
    const td = await tr.json();
    tabs = td.success ? (td.tabs || []) : [];
    if(!currentTabId && tabs.length) currentTabId = tabs[0].id;
    renderTabs();
    updateActiveDashboardBanner();
  }catch(e){ console.error(e); }
}

function renderTabs(){
  const label = document.getElementById('tabLabel');
  const menu = document.getElementById('tabMenu');
  const dd = document.getElementById('tabDD');
  if (!label || !menu) return;
  const cur = tabs.find(t => t.id === currentTabId);
  label.textContent = cur ? cur.name : 'Pilih Tab';

  let html = tabs.map(t => `
    <div class="ios-dd-item ${t.id === currentTabId ? 'active' : ''}" data-tab-id="${t.id}" style="cursor:pointer;">
      <i class="fa-solid ${esc(t.icon || 'fa-chart-line')}"></i>
      <span style="flex:1;text-align:left;overflow:hidden;text-overflow:ellipsis;">${esc(t.name)}</span>
      <span class="tab-actions" style="display:flex;gap:2px;flex-shrink:0;">
        <button type="button" class="tab-action-btn" data-action="edit-tab" data-tab-id="${t.id}" title="Edit">
          <i class="fa-solid fa-pen"></i>
        </button>
        <button type="button" class="tab-action-btn" data-action="delete-tab" data-tab-id="${t.id}" title="Hapus">
          <i class="fa-solid fa-trash"></i>
        </button>
      </span>
    </div>
  `).join('');
  html += `<div style="height:1px;background:var(--hairline);margin:4px 6px;"></div>`;
  html += `<button type="button" class="ios-dd-item" data-action="new-tab">
    <i class="fa-solid fa-plus"></i>
    <span>Tambah Tab</span>
  </button>`;
  menu.innerHTML = html;

  menu.querySelectorAll('[data-tab-id]').forEach(item => {
    item.addEventListener('click', (e) => {
      if (e.target.closest('.tab-actions')) return;
      e.stopPropagation();
      switchTab(parseInt(item.dataset.tabId, 10));
      if (dd) dd.classList.remove('open');
    });
  });
  menu.querySelectorAll('[data-action="edit-tab"]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = parseInt(btn.dataset.tabId, 10);
      if (!Number.isFinite(id)) return;
      const tab = tabs.find(t => t.id === id);
      openTabModal('edit', id, tab ? tab.name : '');
    });
  });
  menu.querySelectorAll('[data-action="delete-tab"]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = parseInt(btn.dataset.tabId, 10);
      if (Number.isFinite(id)) confirmDeleteTabMobile(id);
    });
  });
  const addBtn = menu.querySelector('[data-action="new-tab"]');
  if (addBtn) addBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    openTabModal('new');
    if (dd) dd.classList.remove('open');
  });

  if (dd && !dd.__bound) {
    dd.__bound = true;
    const trigger = dd.querySelector('.ios-dd-trigger');
    if (trigger) trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      document.querySelectorAll('.ios-dd.open').forEach(el => {
        if (el !== dd) el.classList.remove('open');
      });
      dd.classList.toggle('open');
    });
  }
}

window.confirmDeleteTabMobile = function(tabId) {
  confirmModal('Hapus Tab', 'Hapus tab ini beserta diagramnya?', async () => {
    const r = await api(`/api/v1/analytics-tabs/${tabId}`, { method: 'DELETE' });
    const d = await r.json();
    if (d.success) {
      toast('Tab dihapus');
      if (currentTabId === tabId) currentTabId = null;
      await loadTabs();
      if (tabs.length) switchTab(tabs[0].id);
      else loadCharts();
    } else {
      alert(d.error || 'Gagal hapus');
    }
  });
};

function switchTab(id){
  currentTabId = id; renderTabs();
  const dd = document.getElementById('tabDD'); if (dd) dd.classList.remove('open');
  loadCharts();
}
function openTabModal(mode, id, name){
  document.getElementById('tabModalTitle').textContent = mode === 'edit' ? 'Edit Tab' : 'Tambah Tab';
  document.getElementById('tabMode').value = mode;
  document.getElementById('tabId').value = id || '';
  document.getElementById('tabName').value = name || '';
  document.getElementById('tabDeleteBtn').classList.toggle('hidden', mode !== 'edit');
  openModal('m-tab');
}
async function saveTab(){
  const mode = document.getElementById('tabMode').value;
  const id = document.getElementById('tabId').value;
  const name = document.getElementById('tabName').value.trim();
  if(!name){ alert('Nama tab wajib'); return; }
  let url, method;
  if(mode === 'edit' && id){ url = `/api/v1/analytics-tabs/${id}`; method = 'PUT'; }
  else{ url = `/api/v1/dashboards/${dashboardId}/analytics-tabs`; method = 'POST'; }
  const r = await api(url, {method, body:JSON.stringify({name, icon:'fa-chart-line'})});
  const d = await r.json();
  if(d.success){ closeModal('m-tab'); await loadTabs(); if(d.id) currentTabId = d.id; loadCharts(); }
  else alert(d.error || 'Gagal');
}
async function deleteTab(){
  const id = document.getElementById('tabId').value; if(!id) return;
  if(!confirm('Hapus tab ini beserta diagramnya?')) return;
  const r = await api(`/api/v1/analytics-tabs/${id}`, {method:'DELETE'});
  const d = await r.json();
  if(d.success){ closeModal('m-tab'); currentTabId = null; await loadTabs(); if(tabs.length) switchTab(tabs[0].id); else loadCharts(); }
  else alert(d.error || 'Gagal');
}

const toChart = t => ({line_chart:'line', bar_chart:'bar', area_chart:'area', doughnut_chart:'doughnut', pie_chart:'pie', polar_area:'polarArea', radar_chart:'radar', horizontal_bar:'horizontalBar', stacked_bar:'stackedBar', stacked_area:'stackedArea'}[t] || 'line');
const toWidget = t => ({line:'line_chart', bar:'bar_chart', area:'area_chart', doughnut:'doughnut_chart', pie:'pie_chart', polarArea:'polar_area', radar:'radar_chart', horizontalBar:'horizontal_bar', stackedBar:'stacked_bar', stackedArea:'stacked_area'}[t] || 'line_chart');

async function loadCharts(){
  const c = document.getElementById('chartsList'); if(!c) return;
  if(!currentTabId){
    document.getElementById('chartCountSub').textContent = 'Belum ada tab';
    c.innerHTML = '<div class="empty"><i class="fa-solid fa-chart-column"></i><div class="empty-title">Belum ada tab</div></div>';
    return;
  }
  c.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  try{
    const r = await api(`/api/v1/dashboards/${dashboardId}/analytics-tabs/${currentTabId}/widgets`);
    const d = await r.json();
    if(!d.success){
      c.innerHTML = '<div class="empty"><i class="fa-solid fa-triangle-exclamation"></i><div class="empty-title">Gagal memuat</div></div>';
      return;
    }
    const widgets = d.widgets || [];
    charts.forEach(ch => { if(ch.chartInstance) try{ ch.chartInstance.destroy(); }catch(e){} });
    charts = widgets.map(w => {
      const cfg = w.config || {};
      const devs = Array.isArray(cfg.devices) && cfg.devices.length ? cfg.devices : (w.device_id ? [w.device_id] : []);
      return {id:`chart_${w.id}`, widgetId:w.id, title:w.title, deviceIds:devs, chartType:toChart(w.widget_type), showData:cfg.show_data || {}, chartInstance:null};
    });
    document.getElementById('chartCountSub').textContent = `${charts.length} diagram`;
    if(!charts.length){
      c.innerHTML = '<div class="empty"><i class="fa-solid fa-chart-column"></i><div class="empty-title">Belum ada diagram</div><div class="empty-sub">Tap + untuk menambahkan</div></div>';
      return;
    }
    c.innerHTML = charts.map(ch => {
      const deviceNames = ch.deviceIds.map(id => devices.find(d => d.device_id === id)?.device_name || id).join(', ');
      const dataLabels = Object.entries(ch.showData).filter(([_,v])=>v).map(([k])=>DATA_KEYS[k]?.label).filter(Boolean).join(', ');
      return `
      <div class="chart-card" id="${ch.id}">
        <div class="chart-head">
          <div class="chart-info">
            <div class="chart-title">${esc(ch.title)}</div>
            <div class="chart-sub">${esc(deviceNames)}${dataLabels ? ' · ' + esc(dataLabels) : ''}</div>
          </div>
          <div class="chart-actions">
            <button class="chart-act" data-action="open-chart" data-chart-id="${escAttr(ch.id)}"><i class="fa-solid fa-pen"></i></button>
            <button class="chart-act danger" data-action="remove-chart" data-chart-id="${escAttr(ch.id)}"><i class="fa-solid fa-trash"></i></button>
          </div>
        </div>
        <div class="chart-canvas"><canvas id="${ch.id}_c"></canvas></div>
      </div>`;
    }).join('');
    c.querySelectorAll('[data-action="open-chart"]').forEach(btn => {
      btn.addEventListener('click', (e) => { e.stopPropagation(); openChart(btn.dataset.chartId); });
    });
    c.querySelectorAll('[data-action="remove-chart"]').forEach(btn => {
      btn.addEventListener('click', (e) => { e.stopPropagation(); removeChart(btn.dataset.chartId); });
    });
    await loadChartsData();
  }catch(e){ console.error(e); c.innerHTML = '<div class="empty"><div class="empty-title">Koneksi gagal</div></div>'; }
}
async function loadChartsData(){
  const devSet = new Set();
  charts.forEach(ch => ch.deviceIds.forEach(d => devSet.add(d)));
  if(!devSet.size) return;
  const hours = Math.max(1, Math.ceil(timeMinutes/60));
  const limit = Math.min(Math.max(hours*60, 500), 5000);
  const results = await Promise.all(Array.from(devSet).map(did =>
    api(`/api/v1/devices/${encodeURIComponent(did)}/history?hours=${hours}&limit=${limit}`)
      .then(r => r.json())
      .then(j => ({did, data: j.success ? (j.history || []) : []}))
      .catch(() => ({did, data: []}))
  ));
  const hist = {}; results.forEach(r => { hist[r.did] = r.data; });
  charts.forEach(ch => renderChart(ch, hist));
}

function renderChart(ch, hist){
  const canvas = document.getElementById(`${ch.id}_c`); if(!canvas) return;
  // Chart.js lazy-load: fallback pesan bila offline/baru gagal
  if(typeof Chart === 'undefined'){ const w=document.getElementById(ch.id); if(w) w.innerHTML += '<div class="empty" style="padding:20px;"><div class="empty-title">Chart.js gagal dimuat. Cek koneksi internet/CDN.</div></div>'; return; }
  const ctx = canvas.getContext('2d');
  if(ch.chartInstance) try{ ch.chartInstance.destroy(); }catch(e){}
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  const gridC = isLight ? 'rgba(0,0,0,.05)' : 'rgba(255,255,255,.05)';
  const labelC = isLight ? '#737373' : '#a3a3a3';
  const legendC = isLight ? '#525252' : '#a3a3a3';
  const tooltipBg = isLight ? '#0a0a0a' : '#fafafa';
  const tooltipTitleColor = isLight ? '#fafafa' : '#0a0a0a';
  const tooltipBodyColor = isLight ? '#a3a3a3' : '#525252';
  const pointBorderColor = isLight ? '#fafafa' : '#0a0a0a';

  const activeKeys = Object.entries(ch.showData).filter(([k,v]) => v).map(([k]) => k);

  if(['doughnut','pie','polarArea','radar'].includes(ch.chartType)){
    const labels = [], vals = [];
    ch.deviceIds.forEach(did => {
      const h = hist[did] || []; if(!h.length) return;
      const last = h[h.length - 1];
      const dn = devices.find(x => x.device_id === did)?.device_name || did;
      activeKeys.forEach(k => {
        const info = DATA_KEYS[k]; if(!info) return;
        const v = last.data?.[k];
        if(v != null){ labels.push(ch.deviceIds.length > 1 ? `${dn} — ${info.label}` : info.label); vals.push(v); }
      });
    });
    if(!vals.length) return;
    ch.chartInstance = new Chart(ctx, {
      type: ch.chartType,
      data: {
        labels,
        datasets: [{
          data: vals,
          backgroundColor: vals.map((_,i) => COLORS[i%COLORS.length] + '99'),
          borderColor: vals.map((_,i) => COLORS[i%COLORS.length]),
          borderWidth: 2,
        }],
      },
      options: {
        responsive:true, maintainAspectRatio:false,
        plugins:{
          legend:{
            position:'bottom',
            labels:{color:legendC,font:{size:10,weight:'500',family:CHART_FONT},boxWidth:8,boxHeight:8,padding:8,usePointStyle:true,pointStyle:'circle'},
          },
        },
      },
    });
    return;
  }

  const tsSet = new Set();
  ch.deviceIds.forEach(did => (hist[did] || []).forEach(it => tsSet.add(it.timestamp)));
  if(!tsSet.size) return;
  const cutoff = Date.now() - timeMinutes*60*1000;
  const allTs = Array.from(tsSet).sort();
  const inRange = allTs.filter(ts => {
    const d = parseTs(ts); return d && d.getTime() >= cutoff;
  });
  const usedTs = (inRange.length ? inRange : allTs).slice(-200);
  const labels = usedTs.map(ts => fmtTime(ts));
  const datasets = []; let ci = 0;

  ch.deviceIds.forEach(did => {
    const h = hist[did] || []; if(!h.length) return;
    const dn = devices.find(x => x.device_id === did)?.device_name || did;
    const tsMap = {}; h.forEach(it => { tsMap[it.timestamp] = it.data || {}; });

    activeKeys.forEach(k => {
      const info = DATA_KEYS[k]; if(!info) return;
      const values = usedTs.map(ts => { const o = tsMap[ts]; return o ? (o[k] ?? null) : null; });
      if(!values.some(v => v != null)) return;

      const color = COLORS[ci % COLORS.length]; ci++;
      const isArea = ch.chartType === 'area' || ch.chartType === 'stackedArea';
      const isStacked = ch.chartType === 'stackedBar' || ch.chartType === 'stackedArea';

      datasets.push({
        label: ch.deviceIds.length > 1 ? `${dn} — ${info.label}` : `${info.label} (${info.unit})`,
        data: values,
        borderColor: color,
        backgroundColor: isArea ? color+'22' : color,
        fill: isArea,
        tension: .3,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: color,
        pointHoverBorderColor: pointBorderColor,
        pointHoverBorderWidth: 2,
        pointBackgroundColor: color,
        pointBorderColor: pointBorderColor,
        pointBorderWidth: 0,
        borderWidth: 2,
        spanGaps: true,
        stack: isStacked ? 'stack1' : undefined,
      });
    });
  });

  if(!datasets.length) return;

  let type = ch.chartType;
  if(type === 'area' || type === 'stackedArea') type = 'line';
  if(type === 'horizontalBar' || type === 'stackedBar') type = 'bar';

  ch.chartInstance = new Chart(ctx, {
    type,
    data: {labels, datasets},
    options: {
      responsive:true, maintainAspectRatio:false,
      interaction:{mode:'index', intersect:false},
      indexAxis: ch.chartType === 'horizontalBar' ? 'y' : 'x',
      animation:{duration:300, easing:'easeOutQuart'},
      plugins:{
        legend:{
          labels:{color:legendC,font:{size:10,weight:'500',family:CHART_FONT},boxWidth:8,boxHeight:8,padding:8,usePointStyle:true,pointStyle:'circle'},
        },
        tooltip:{
          backgroundColor: tooltipBg, titleColor: tooltipTitleColor, bodyColor: tooltipBodyColor,
          borderColor: isLight ? 'rgba(0,0,0,0.08)' : 'rgba(255,255,255,0.1)',
          borderWidth: 1, padding: 10, cornerRadius: 8, displayColors: true, boxPadding: 4,
          titleFont:{size:11, family:CHART_FONT, weight:'600'},
          bodyFont:{size:11, family:CHART_FONT, weight:'500'},
        },
      },
      scales:{
        x:{
          grid:{color: gridC, drawBorder:false, drawTicks:false},
          border:{display:false},
          ticks:{color: labelC, font:{size:9.5, family:CHART_FONT, weight:'500'}, maxTicksLimit:6, maxRotation:0, autoSkip:true, padding:4},
          stacked: ch.chartType === 'stackedBar' || ch.chartType === 'stackedArea',
        },
        y:{
          grid:{color: gridC, drawBorder:false, drawTicks:false},
          border:{display:false},
          ticks:{color: labelC, font:{size:9.5, family:CHART_FONT, weight:'500'}, padding:6},
          stacked: ch.chartType === 'stackedBar' || ch.chartType === 'stackedArea',
          beginAtZero:true,
        },
      },
    },
  });
}

function resetChartsLayout(){
  if(!currentTabId){ toast('Tidak ada tab aktif'); return; }
  confirmModal('Reset Layout', 'Reset layout diagram di tab ini?', () => {
    loadCharts();
    toast('Layout direset');
  });
}

/* ===== Chart Modal ===== */
function genChartDeviceCbs(sel = []){
  const c = document.getElementById('chartDeviceCbs'); if(!c) return;
  const s = new Set(sel);
  if(!devices.length){ c.innerHTML = '<div style="padding:8px;color:var(--text-3);font-size:11px;grid-column:1/-1;">Belum ada perangkat</div>'; return; }
  c.innerHTML = devices.map(d => `<label class="cb"><input type="checkbox" class="chart-dev" data-id="${esc(d.device_id)}" ${s.has(d.device_id)?'checked':''}><span>${esc(d.device_name)}</span></label>`).join('');
}
function genChartDataCbs(sel = {}){
  const c = document.getElementById('chartDataCbs'); if(!c) return;
  c.innerHTML = Object.entries(DATA_KEYS).map(([k,i]) =>
    `<label class="cb"><input type="checkbox" class="chart-data" data-key="${k}" ${sel[k]?'checked':''}><span class="dot-color" style="background:${i.color};"></span><span>${i.label}</span></label>`
  ).join('');
}
function openChart(id){
  if(!currentTabId){ alert('Buat tab analitik dulu'); go('analytics'); return; }
  if(id){
    const ch = charts.find(c => c.id === id); if(!ch) return;
    document.getElementById('chartModalTitle').textContent = 'Edit Diagram';
    document.getElementById('editChartId').value = id;
    document.getElementById('chartTitle').value = ch.title;
    document.getElementById('chartType').value = ch.chartType;
    genChartDeviceCbs(ch.deviceIds);
    genChartDataCbs(ch.showData);
  } else {
    document.getElementById('chartModalTitle').textContent = 'Tambah Diagram';
    document.getElementById('editChartId').value = '';
    document.getElementById('chartTitle').value = '';
    document.getElementById('chartType').value = 'line';
    genChartDeviceCbs(devices[0] ? [devices[0].device_id] : []);
    genChartDataCbs({temperature:true});
  }
  openModal('m-chart');
}
async function saveChart(){
  const editId = document.getElementById('editChartId').value;
  const title = document.getElementById('chartTitle').value.trim() || 'Diagram';
  const chartType = document.getElementById('chartType').value;
  const deviceIds = []; document.querySelectorAll('.chart-dev:checked').forEach(cb => deviceIds.push(cb.dataset.id));
  const showData = {}; document.querySelectorAll('.chart-data').forEach(cb => { showData[cb.dataset.key] = cb.checked; });
  if(!deviceIds.length){ alert('Pilih minimal 1 perangkat'); return; }
  if(!Object.values(showData).some(v => v)){ alert('Pilih minimal 1 jenis data'); return; }
  const wt = toWidget(chartType);
  const config = {show_data: showData, devices: deviceIds};
  let url, method;
  if(editId){ const ch = charts.find(c => c.id === editId); if(!ch) return; url = `/api/v1/widgets/${ch.widgetId}`; method = 'PUT'; }
  else{ url = `/api/v1/dashboards/${dashboardId}/widgets`; method = 'POST'; }
  const body = {title, device_id: deviceIds[0], widget_type: wt, config};
  if(!editId) Object.assign(body, {grid_x:0, grid_y:0, grid_w:6, grid_h:2, analytics_tab_id:currentTabId});
  const r = await api(url, {method, body:JSON.stringify(body)});
  const d = await r.json();
  if(d.success){ closeModal('m-chart'); loadCharts(); toast(editId ? 'Diagram diupdate' : 'Diagram ditambahkan'); }
  else alert(d.error || 'Gagal');
}
function removeChart(id){
  const ch = charts.find(c => c.id === id); if(!ch) return;
  confirmModal('Hapus Diagram', `Hapus diagram "${ch.title}"?`, async () => {
    await api(`/api/v1/widgets/${ch.widgetId}`, {method:'DELETE'});
    loadCharts();
  });
}

/* ===== Alerts ===== */
let __alertDDsBound = false;
function bindAlertDropdowns() {
  if (__alertDDsBound) return;
  __alertDDsBound = true;

  bindIosDD('alertStatusDD', (val) => {
    alertStatus = val || 'all';
    loadAlerts();
  });
  bindIosDD('alertSevDD', (val) => {
    alertSev = val || '';
    loadAlerts();
  });
}
bindAlertDropdowns();

document.getElementById('alertSearch').addEventListener('input', e => {
  clearTimeout(window.__aST);
  window.__aST = setTimeout(() => { alertSearch = e.target.value.trim(); renderAlerts(); }, 200);
});

async function loadAlerts(){
  const c = document.getElementById('alertsList'); if(!c) return;
  try{
    const sr = await api('/api/v1/alerts/stats');
    const sd = await sr.json();
    if(sd.success){
      document.getElementById('aTotal').textContent = sd.summary.total;
      document.getElementById('aDanger').textContent = sd.summary.danger;
      document.getElementById('aWarning').textContent = sd.summary.warning;
      document.getElementById('aInfo').textContent = sd.summary.info;
      document.getElementById('alertSub').textContent = `${sd.summary.total} alert aktif`;
    }
    const params = new URLSearchParams();
    if(alertStatus !== 'all') params.set('status', alertStatus);
    if(alertSev) params.set('severity', alertSev);
    params.set('limit', '1000');
    const r = await api(`/api/v1/alerts/all?${params}`);
    const d = await r.json();
    alerts = d.success ? (d.alerts || []) : [];
    const validIds = new Set(alerts.filter(a => a.is_still_active === 1 && a.severity !== 'healthy').map(ackIdOf).filter(x=>x!=null));
    Array.from(alertSelectedIds).forEach(id => { if(!validIds.has(id)) alertSelectedIds.delete(id); });
    renderAlerts();
  }catch(e){ c.innerHTML = '<div class="empty"><div class="empty-title">Koneksi gagal</div></div>'; }
}

function inAlertDateRange(iso){
  if(!alertDateStart && !alertDateEnd) return true;
  const d = parseTs(iso); if(!d) return true;
  const t = d.getTime();
  if(alertDateStart){
    const st = new Date(alertDateStart+'T00:00:00+07:00').getTime();
    if(t < st) return false;
  }
  if(alertDateEnd){
    const en = new Date(alertDateEnd+'T23:59:59+07:00').getTime();
    if(t > en) return false;
  }
  return true;
}

function applyAlertDateFilter(){
  alertDateStart = document.getElementById('alertDateStart').value;
  alertDateEnd = document.getElementById('alertDateEnd').value;
  renderAlerts();
}
function resetAlertDateFilter(){
  document.getElementById('alertDateStart').value = '';
  document.getElementById('alertDateEnd').value = '';
  alertDateStart = '';
  alertDateEnd = '';
  renderAlerts();
}

function getFilteredAlerts(){
  let list = alerts.slice();
  list = list.filter(a => inAlertDateRange(a.created_at));
  if(alertSearch){
    const t = alertSearch.toLowerCase();
    list = list.filter(a =>
      (a.device_name||'').toLowerCase().includes(t) ||
      (a.device_id||'').toLowerCase().includes(t) ||
      (a.message||'').toLowerCase().includes(t) ||
      (a.alert_type||'').toLowerCase().includes(t) ||
      (a.label||'').toLowerCase().includes(t));
  }
  return list;
}

function renderAlerts(){
  const c = document.getElementById('alertsList'); if(!c) return;
  const list = getFilteredAlerts();

  if(!list.length){
    c.innerHTML = '<div class="empty"><i class="fa-solid fa-bell-slash"></i><div class="empty-title">Tidak ada alert</div></div>';
    updateAlertBulkBar();
    return;
  }

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7*86400000);

  let html = '';
  let currentGroup = '', groupOpen = false;

  list.forEach(a => {
    const d = parseTs(a.created_at);
    let group;
    if(!d) group = 'Tidak Diketahui';
    else if(d >= today) group = 'Hari Ini';
    else if(d >= yesterday) group = 'Kemarin';
    else if(d >= weekAgo) group = '7 Hari Terakhir';
    else group = 'Lebih Lama';

    if(group !== currentGroup){
      if(groupOpen) html += '</div>';
      html += `<div class="alert-group"><div class="alert-group-label">${group}</div>`;
      currentGroup = group;
      groupOpen = true;
    }
    html += renderAlertRow(a);
  });
  if(groupOpen) html += '</div>';

  c.innerHTML = html;
  bindAlertRowEvents();
  updateAlertBulkBar();
}

function renderAlertRow(a){
  const active = a.is_still_active === 1;
  const sev = a.severity || 'info';
  const healthy = sev === 'healthy';
  const cls = healthy ? 'resolved' : (active ? sev : 'resolved');
  const id = ackIdOf(a);
  const canAck = active && !healthy && id != null;
  const isChecked = id != null && alertSelectedIds.has(id);
  const valueDisplay = formatVal(a.alert_type, a.value);
  const typeLabel = a.label || alertTypeLabel(a.alert_type);

  const checkHtml = canAck
    ? `<label class="alert-check">
         <input type="checkbox" class="alert-cb" data-alert-id="${id}" ${isChecked?'checked':''}>
       </label>`
    : `<div class="alert-check hidden"></div>`;

  return `<div class="alert-item ${cls}" data-alert-id="${a.id}" data-device-id="${esc(a.device_id)}">
    ${checkHtml}
    <div class="alert-body">
      <div class="alert-head">
        <span class="alert-sev ${sev}">${sev}</span>
        <span class="alert-head-type">${esc(a.alert_type || '')}</span>
        ${valueDisplay ? `<span class="alert-val">${esc(valueDisplay)}</span>` : ''}
      </div>
      <div class="alert-title">${esc(typeLabel)}</div>
      <div class="alert-msg">${esc(a.message || '-')}</div>
      <div class="alert-meta">
        <span><i class="fa-solid fa-microchip"></i> ${esc(a.device_name || a.device_id)}</span>
        <span class="dot"></span>
        <span>${fmtRelative(a.created_at)}</span>
      </div>
      ${(active || canAck) ? `<div class="alert-actions">
        <button class="alert-act-btn" data-action="view-device" data-device-id="${esc(a.device_id)}">
          <i class="fa-solid fa-eye"></i> Detail
        </button>
        ${canAck ? `<button class="alert-act-btn ok" data-action="acknowledge" data-alert-id="${id}">
          <i class="fa-solid fa-check"></i> Tandai
        </button>` : ''}
      </div>` : ''}
    </div>
  </div>`;
}

function bindAlertRowEvents(){
  document.querySelectorAll('.alert-item [data-action="view-device"]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      openDevice(btn.dataset.deviceId);
    });
  });
  document.querySelectorAll('.alert-item [data-action="acknowledge"]').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const id = parseInt(btn.dataset.alertId, 10);
      if(!Number.isFinite(id)) return;
      const ok = await ackAlert(id);
      if(ok){ loadAlerts(); toast('Alert ditandai selesai'); }
      else alert('Gagal');
    });
  });
  document.querySelectorAll('.alert-cb').forEach(cb => {
    cb.addEventListener('change', e => {
      const id = parseInt(e.target.dataset.alertId, 10);
      if(!Number.isFinite(id)) return;
      if(e.target.checked) alertSelectedIds.add(id);
      else alertSelectedIds.delete(id);
      updateAlertBulkBar();
    });
  });
  document.querySelectorAll('.alert-item').forEach(item => {
    item.addEventListener('click', e => {
      if(e.target.closest('button') || e.target.closest('label') || e.target.closest('input')) return;
      const id = item.dataset.deviceId;
      if(id) openDevice(id);
    });
  });
}

function updateAlertBulkBar(){
  const bar = document.getElementById('alertBulkBar');
  if(!bar) return;
  const activeVisible = getFilteredAlerts().filter(a =>
    a.is_still_active === 1 && a.severity !== 'healthy' && ackIdOf(a) != null);
  if(activeVisible.length === 0){
    bar.style.display = 'none';
    return;
  }
  bar.style.display = 'flex';
  document.getElementById('alertSelectedCount').textContent = `${alertSelectedIds.size} dipilih`;
  const selAll = document.getElementById('alertSelectAll');
  const allIds = activeVisible.map(ackIdOf);
  selAll.checked = allIds.length > 0 && allIds.every(id => alertSelectedIds.has(id));
}

document.getElementById('alertSelectAll').addEventListener('change', e => {
  const activeVisible = getFilteredAlerts().filter(a =>
    a.is_still_active === 1 && a.severity !== 'healthy' && ackIdOf(a) != null);
  if(e.target.checked){
    activeVisible.forEach(a => alertSelectedIds.add(ackIdOf(a)));
  } else {
    alertSelectedIds.clear();
  }
  renderAlerts();
});

async function bulkAckAlerts(){
  if(alertSelectedIds.size === 0){ toast('Pilih minimal satu alert'); return; }
  confirmModal('Tandai Selesai', `Tandai ${alertSelectedIds.size} alert sebagai selesai?`, async () => {
    const ids = Array.from(alertSelectedIds);
    try{
      const r = await api('/api/v1/alerts/bulk-acknowledge', {
        method:'POST', body:JSON.stringify({ids})
      });
      const d = await r.json();
      if(d.success){
        toast(`${d.acknowledged || ids.length} alert ditandai selesai`);
        alertSelectedIds.clear();
        loadAlerts();
      } else alert(d.error || 'Gagal');
    }catch(e){ alert('Koneksi gagal'); }
  });
}

async function markAllVisibleAlerts(){
  const visible = getFilteredAlerts().filter(a =>
    a.is_still_active === 1 && a.severity !== 'healthy' && ackIdOf(a) != null);
  if(!visible.length){ toast('Tidak ada alert aktif di filter ini'); return; }
  confirmModal('Tandai Semua', `Tandai ${visible.length} alert sebagai selesai?`, async () => {
    const ids = visible.map(ackIdOf);
    try{
      const r = await api('/api/v1/alerts/bulk-acknowledge', {
        method:'POST', body:JSON.stringify({ids})
      });
      const d = await r.json();
      if(d.success){ toast(`${d.acknowledged || ids.length} alert ditandai selesai`); loadAlerts(); }
      else alert(d.error || 'Gagal');
    }catch(e){ alert('Koneksi gagal'); }
  });
}

async function ackAlert(id){
  try{
    const r = await api(`/api/v1/alerts/${id}/acknowledge`, {method:'POST'});
    const d = await r.json();
    return d.success === true;
  }catch(e){ return false; }
}

/* ===== Alert Trend ===== */
function openAlertTrend(){
  openModal('m-alert-trend');
  setTimeout(() => loadMobileTrend(), 100);
}

function setTrendRange(hours, btn){
  trendHours = hours;
  document.querySelectorAll('#m-alert-trend .trend-range-btn').forEach(b => b.classList.remove('active'));
  if(btn) btn.classList.add('active');
  loadMobileTrend();
}

async function loadMobileTrend(){
  const canvas = document.getElementById('mobileTrendCanvas');
  const empty = document.getElementById('mobileTrendEmpty');
  if(!canvas) return;
  // Chart.js lazy: muat dulu bila belum siap; fallback bila offline
  if(typeof Chart === 'undefined'){
    if(window.AAGuardLazy){ try{ await window.AAGuardLazy.loadChartLibs(); }catch(e){ if(empty){ empty.style.display='flex'; empty.textContent='Chart.js gagal dimuat. Cek koneksi internet/CDN.'; } return; } }
    if(typeof Chart === 'undefined'){ if(empty){ empty.style.display='flex'; empty.textContent='Chart.js gagal dimuat. Cek koneksi internet/CDN.'; } return; }
  }

  try{
    const r = await api(`/api/v1/alerts/trend?hours=${trendHours}`);
    const d = await r.json();
    if(!d.success) return;

    const buckets = {};
    (d.trend || []).forEach(row => {
      if(!buckets[row.hour_bucket]) buckets[row.hour_bucket] = {danger:0, warning:0, info:0};
      if(buckets[row.hour_bucket][row.severity] !== undefined) buckets[row.hour_bucket][row.severity] = row.count;
    });

    const labels = Object.keys(buckets).sort();
    if(labels.length === 0){
      if(empty) empty.style.display = 'flex';
      canvas.style.display = 'none';
      if(mobileTrendChart){ mobileTrendChart.destroy(); mobileTrendChart = null; }
      return;
    }
    if(empty) empty.style.display = 'none';
    canvas.style.display = '';

    const dangerData = labels.map(l => buckets[l].danger || 0);
    const warningData = labels.map(l => buckets[l].warning || 0);
    const infoData = labels.map(l => buckets[l].info || 0);

    const isLongRange = trendHours > 48;
    const displayLabels = labels.map(l => {
      const parts = String(l).split(' ');
      const date = parts[0] || '';
      const time = parts[1] || '';
      if(isLongRange) return `${date.slice(5)} ${time.slice(0,2)}h`;
      return time.slice(0, 5);
    });

    if(mobileTrendChart){ mobileTrendChart.destroy(); mobileTrendChart = null; }

    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    const gridC = isLight ? 'rgba(0,0,0,.05)' : 'rgba(255,255,255,.05)';
    const labelC = isLight ? '#737373' : '#a3a3a3';
    const legendC = isLight ? '#525252' : '#a3a3a3';

    mobileTrendChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: displayLabels,
        datasets: [
          {label:'Bahaya', data: dangerData, backgroundColor:'rgba(239,68,68,0.75)', borderRadius:4, stack:'s'},
          {label:'Peringatan', data: warningData, backgroundColor:'rgba(249,115,22,0.75)', borderRadius:4, stack:'s'},
          {label:'Info', data: infoData, backgroundColor:'rgba(139,92,246,0.75)', borderRadius:4, stack:'s'},
        ],
      },
      options: {
        responsive:true, maintainAspectRatio:false,
        interaction:{mode:'index', intersect:false},
        plugins:{
          legend:{
            position:'bottom',
            labels:{color: legendC, font:{size:10, weight:'500', family:CHART_FONT}, boxWidth:8, boxHeight:8, padding:8, usePointStyle:true, pointStyle:'circle'},
          },
        },
        scales:{
          x:{stacked:true, grid:{display:false}, border:{display:false},
             ticks:{color: labelC, font:{size:9, family:CHART_FONT}, maxRotation:0, autoSkip:true, maxTicksLimit:10, padding:4}},
          y:{stacked:true, beginAtZero:true,
             grid:{color: gridC, drawBorder:false, drawTicks:false}, border:{display:false},
             ticks:{color: labelC, font:{size:9, family:CHART_FONT}, padding:4, precision:0}},
        },
      },
    });
  }catch(e){ console.error(e); }
}

/* ===== Alert History ===== */
async function openAlertHistory(){
  openModal('m-alert-history');
  await populateAlertHistoryDevices();
  await loadAlertHistory();
}

async function populateAlertHistoryDevices(){
  const sel = document.getElementById('historyDeviceFilter');
  if(!sel || sel.dataset.populated === '1') return;
  try{
    const r = await api('/api/v1/devices');
    const d = await r.json();
    if(!d.success) return;
    (d.devices || []).forEach(dev => {
      const opt = document.createElement('option');
      opt.value = dev.device_id;
      opt.textContent = `${dev.device_name} (${dev.device_id})`;
      sel.appendChild(opt);
    });
    sel.dataset.populated = '1';
  }catch(e){ console.warn(e); }
}

async function loadAlertHistory(){
  const body = document.getElementById('alertHistoryBody');
  if(!body) return;
  body.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

  const deviceId = (document.getElementById('historyDeviceFilter')||{}).value || '';
  const severity = (document.getElementById('historySeverityFilter')||{}).value || '';
  const params = new URLSearchParams();
  if(deviceId) params.set('device_id', deviceId);
  params.set('limit', '500');

  try{
    const r = await api(`/api/v1/alerts/history?${params}`);
    const d = await r.json();
    if(!d.success){
      body.innerHTML = '<div class="empty"><div class="empty-title">Gagal memuat</div></div>';
      return;
    }
    let history = Array.isArray(d.history) ? d.history : [];
    if(severity) history = history.filter(h => h.severity === severity);

    if(history.length === 0){
      body.innerHTML = '<div class="empty"><div class="empty-title">Belum ada riwayat</div></div>';
      return;
    }

    const actionLabels = {created:'Dibuat', acknowledged:'Ditandai', cleared:'Selesai', severity_changed:'Severity Berubah'};
    const severityLabels = {danger:'Bahaya', warning:'Peringatan', info:'Info', healthy:'Normal'};

    body.innerHTML = history.map(h => {
      const sev = h.severity || 'info';
      const action = h.action || '';
      const actionLabel = actionLabels[action] || action;
      const sevLabel = severityLabels[sev] || sev;
      const valDisplay = h.value != null ? formatVal(h.alert_type, h.value) : null;
      const deviceName = h.device_name || h.device_id || '—';

      return `<div class="history-item">
        <div class="history-head">
          <span class="alert-sev ${sev}">${esc(sevLabel)}</span>
          <span class="history-action ${action}">${esc(actionLabel)}</span>
          <span class="history-time">${fmtRelative(h.created_at)}</span>
        </div>
        <div class="history-title">
          <strong>${esc(alertTypeLabel(h.alert_type))}</strong>
          ${valDisplay ? `<span class="alert-val">${esc(valDisplay)}</span>` : ''}
        </div>
        <div class="history-msg">${esc(h.message || '-')}</div>
        <div class="history-dev"><i class="fa-solid fa-microchip"></i> ${esc(deviceName)}</div>
      </div>`;
    }).join('');
  }catch(e){
    body.innerHTML = '<div class="empty"><div class="empty-title">Koneksi gagal</div></div>';
  }
}

/* ===== Device CRUD ===== */
function openAddDevice(){
  document.getElementById('addId').value = '';
  document.getElementById('addName').value = '';
  document.getElementById('addLocation').value = '';
  document.getElementById('addFirmware').value = '';
  document.getElementById('addDescription').value = '';
  document.getElementById('addInterval').value = '';
  document.getElementById('addTimeout').value = '';
  document.getElementById('addOfflineSeverity').value = 'danger';
  document.getElementById('addRules').innerHTML = '<div class="rule-empty">Belum ada custom rule</div>';
  openModal('m-add');
}
async function submitAddDevice(){
  const id = document.getElementById('addId').value.trim();
  const name = document.getElementById('addName').value.trim();
  if(!id || !name){ alert('ID dan Nama wajib diisi'); return; }
  const payload = {
    device_id: id, device_name: name,
    device_type: document.getElementById('addType').value,
    location: document.getElementById('addLocation').value,
    description: document.getElementById('addDescription').value,
    firmware_version: document.getElementById('addFirmware').value,
    offline_alert_severity: document.getElementById('addOfflineSeverity').value || 'danger',
  };
  const interval = document.getElementById('addInterval').value;
  if(interval && parseInt(interval) >= 10) payload.expected_interval = parseInt(interval);
  const to = document.getElementById('addTimeout').value;
  if(to) payload.offline_timeout = parseInt(to);
  const rules = collectRules('add'); if(rules) payload.alert_rules = rules;
  try{
    const r = await api('/api/v1/devices', {method:'POST', body:JSON.stringify(payload)});
    const d = await r.json();
    if(d.success){
      closeModal('m-add');
      document.getElementById('apiKeyValue').textContent = d.device.api_key;
      pendingRedirect = d.device.device_id;
      openModal('m-apikey');
      loadDashboard();
    } else {
      const msg = typeof d.error === 'object' ? Object.values(d.error).flat().join(', ') : d.error;
      alert(msg || 'Gagal');
    }
  }catch(e){ alert('Error: ' + e.message); }
}
function copyApiKey(){
  const k = document.getElementById('apiKeyValue').textContent;
  if(navigator.clipboard) navigator.clipboard.writeText(k).then(() => toast('API Key disalin'));
  else alert('Copy manual: ' + k);
}
function closeApiKeyModal(){
  closeModal('m-apikey');
  if(pendingRedirect){
    const id = pendingRedirect; pendingRedirect = null;
    setTimeout(() => openDevice(id), 200);
  }
}
async function openSheet(id){
  const d = devices.find(x => x.device_id === id); if(!d) return;
  sheetDeviceId = id;
  document.getElementById('sheetTitle').textContent = d.device_name;
  openModal('m-sheet');
}
function sheetAction(action){
  const id = sheetDeviceId;
  closeModal('m-sheet');
  if(!id) return;
  setTimeout(() => {
    if(action === 'detail') openDevice(id);
    else if(action === 'config') openEditConfig(id);
    else if(action === 'key') regenKey(id);
    else if(action === 'delete') openDelete(id);
  }, 180);
}
async function regenKey(id){
  confirmModal('Regenerate API Key', `Buat key baru untuk "${id}"? Key lama tidak akan berfungsi lagi.`, async () => {
    const r = await api(`/api/v1/devices/${encodeURIComponent(id)}/regenerate-key`, {method:'POST'});
    const d = await r.json();
    if(d.success){
      document.getElementById('apiKeyValue').textContent = d.api_key;
      pendingRedirect = null;
      openModal('m-apikey');
      loadDashboard();
    } else alert(d.error || 'Gagal');
  });
}
async function openEditConfig(id){
  try{
    const r = await api(`/api/v1/devices/${encodeURIComponent(id)}`);
    const d = await r.json();
    if(!d.success){ alert('Gagal memuat'); return; }
    const dev = d.device;
    document.getElementById('editId').value = id;
    document.getElementById('editName').value = dev.device_name || '';
    document.getElementById('editLocation').value = dev.location || '';
    document.getElementById('editDescription').value = dev.description || '';
    document.getElementById('editFirmware').value = dev.firmware_version || '';
    document.getElementById('editType').value = dev.device_type || 'ESP32';
    document.getElementById('editInterval').value = dev.expected_interval || '';
    document.getElementById('editIntervalDisplay').textContent = dev.expected_interval ? `${dev.expected_interval} detik` : 'Menunggu data...';
    document.getElementById('editTimeout').value = dev.offline_timeout || '';
    document.getElementById('editOfflineSeverity').value = dev.offline_alert_severity || 'danger';
    populateRules('edit', dev.alert_rules);
    openModal('m-edit');
  }catch(e){ alert('Error: ' + e.message); }
}
async function submitEditConfig(){
  const id = document.getElementById('editId').value; if(!id) return;
  const name = document.getElementById('editName').value.trim();
  if(!name){ alert('Nama perangkat wajib diisi'); return; }
  const rules = collectRules('edit');
  const payload = {
    device_name: name,
    device_type: document.getElementById('editType').value,
    location: document.getElementById('editLocation').value,
    description: document.getElementById('editDescription').value,
    firmware_version: document.getElementById('editFirmware').value,
    offline_alert_severity: document.getElementById('editOfflineSeverity').value || 'danger',
    alert_rules: rules,
  };
  const interval = document.getElementById('editInterval').value;
  if(interval && parseInt(interval) >= 10) payload.expected_interval = parseInt(interval);
  else if(interval === '') payload.expected_interval = null; // kosong = kembali ke mode otomatis
  const to = document.getElementById('editTimeout').value;
  if(to) payload.offline_timeout = parseInt(to);
  else payload.offline_timeout = null;
  const r = await api(`/api/v1/devices/${encodeURIComponent(id)}`, {method:'PUT', body:JSON.stringify(payload)});
  const d = await r.json();
  if(d.success){ closeModal('m-edit'); loadDashboard(); toast('Tersimpan'); }
  else alert(d.error || 'Gagal');
}
async function resetDeviceAlertRules(){
  const id = document.getElementById('editId').value; if(!id) return;
  confirmModal('Reset Alert Rules', 'Reset semua custom alert rules ke default global?', async () => {
    const r = await api(`/api/v1/devices/${encodeURIComponent(id)}/alert-rules`, {method:'DELETE'});
    const d = await r.json();
    if(d.success){
      document.getElementById('editRules').innerHTML = '<div class="rule-empty">Belum ada custom rule</div>';
      toast('Rules direset ke global');
    } else alert(d.error || 'Gagal');
  });
}

/* ===== Delete ===== */
let delTarget = null;
function openDelete(id){
  const d = devices.find(x => x.device_id === id);
  const name = d ? d.device_name : id;
  delTarget = id;
  document.getElementById('deleteTitle').textContent = 'Hapus Perangkat';
  document.getElementById('deleteText').textContent = `Perangkat "${name}" akan dihapus permanen. Tindakan ini tidak bisa dibatalkan.`;
  document.getElementById('deleteLabel').innerHTML = `Ketik <span class="mono" style="color:var(--text);background:var(--surface-2);padding:3px 8px;border-radius:6px;">${esc(id)}</span> untuk konfirmasi`;
  document.getElementById('deleteInput').value = '';
  document.getElementById('deleteInput').placeholder = `Ketik ${id}...`;
  document.getElementById('deleteConfirm').disabled = true;
  openModal('m-delete');
}
document.getElementById('deleteInput').addEventListener('input', e => {
  document.getElementById('deleteConfirm').disabled = e.target.value.trim() !== (delTarget || '');
});
async function confirmDelete(){
  if(!delTarget) return;
  const input = document.getElementById('deleteInput').value.trim();
  if(input !== delTarget){ alert('Konfirmasi salah'); return; }
  const r = await api(`/api/v1/devices/${encodeURIComponent(delTarget)}`, {method:'DELETE'});
  const d = await r.json();
  if(d.success){ closeModal('m-delete'); delTarget = null; loadDashboard(); toast('Perangkat dihapus'); }
  else alert(d.error || 'Gagal');
}

/* ===== Alert Rules Builder ===== */
function addRule(mode){
  const c = document.getElementById(mode === 'add' ? 'addRules' : 'editRules'); if(!c) return;
  const empty = c.querySelector('.rule-empty'); if(empty) empty.remove();
  const used = Array.from(c.querySelectorAll('.rule-select')).map(s => s.value);
  const avail = Object.keys(PRESETS).find(k => !used.includes(k)) || Object.keys(PRESETS)[0];
  const p = PRESETS[avail];
  const item = document.createElement('div');
  item.className = 'rule';
  item.innerHTML = `
    <div class="rule-head">
      <select class="rule-select">${Object.entries(PRESETS).map(([k,v]) => `<option value="${k}" ${k===avail?'selected':''}>${v.label}</option>`).join('')}</select>
      <button class="rule-remove" data-action="remove-rule" data-mode="${escAttr(mode)}"><i class="fa-solid fa-xmark"></i></button>
    </div>
    ${sevRow('healthy', p.defaults.healthy)}
    ${sevRow('warning', p.defaults.warning)}
    ${sevRow('danger', p.defaults.danger)}
  `;
  c.appendChild(item);
  item.querySelector('.rule-remove').addEventListener('click', function(){
    this.closest('.rule')?.remove();
    checkRulesEmpty(this.dataset.mode);
  });
  item.querySelector('.rule-select').addEventListener('change', function(){
    const pr = PRESETS[this.value];
    item.querySelectorAll('.rule-sev').forEach(row => {
      const sev = Array.from(row.classList).find(x => ['healthy','warning','danger'].includes(x));
      if(sev && pr.defaults[sev]){
        row.querySelector('[data-field="min"]').value = pr.defaults[sev].min;
        row.querySelector('[data-field="max"]').value = pr.defaults[sev].max;
      }
    });
  });
}
const sevRow = (sev, v) => `<div class="rule-sev ${sev}">
  <div class="rule-sev-label"><span class="dot"></span>${sev === 'healthy' ? 'Normal' : sev === 'warning' ? 'Warning' : 'Bahaya'}</div>
  <input type="number" step="0.1" data-field="min" value="${v.min}">
  <input type="number" step="0.1" data-field="max" value="${v.max}">
</div>`;
function checkRulesEmpty(mode){
  const c = document.getElementById(mode === 'add' ? 'addRules' : 'editRules');
  if(c && !c.querySelector('.rule')) c.innerHTML = '<div class="rule-empty">Belum ada custom rule</div>';
}
function collectRules(mode){
  const c = document.getElementById(mode === 'add' ? 'addRules' : 'editRules'); if(!c) return null;
  const rules = {};
  c.querySelectorAll('.rule').forEach(item => {
    const key = item.querySelector('.rule-select').value;
    const rule = {};
    item.querySelectorAll('.rule-sev').forEach(row => {
      const sev = Array.from(row.classList).find(x => ['healthy','warning','danger'].includes(x));
      if(!sev) return;
      const mn = parseFloat(row.querySelector('[data-field="min"]').value);
      const mx = parseFloat(row.querySelector('[data-field="max"]').value);
      if(!isNaN(mn) && !isNaN(mx)) rule[sev] = {min:mn, max:mx};
    });
    if(Object.keys(rule).length) rules[key] = rule;
  });
  return Object.keys(rules).length ? rules : null;
}
function populateRules(mode, rules){
  const c = document.getElementById(mode === 'add' ? 'addRules' : 'editRules'); if(!c) return;
  c.innerHTML = '';
  if(!rules || !Object.keys(rules).length){
    c.innerHTML = '<div class="rule-empty">Belum ada custom rule</div>'; return;
  }
  Object.entries(rules).forEach(([key, rule]) => {
    const item = document.createElement('div');
    item.className = 'rule';
    item.innerHTML = `
      <div class="rule-head">
        <select class="rule-select">${Object.entries(PRESETS).map(([k,v]) => `<option value="${k}" ${k===key?'selected':''}>${v.label}</option>`).join('')}</select>
        <button class="rule-remove" data-action="remove-rule" data-mode="${escAttr(mode)}"><i class="fa-solid fa-xmark"></i></button>
      </div>
      ${rule.healthy ? sevRow('healthy', rule.healthy) : ''}
      ${rule.warning ? sevRow('warning', rule.warning) : ''}
      ${rule.danger ? sevRow('danger', rule.danger) : ''}
    `;
    c.appendChild(item);
    item.querySelector('.rule-remove').addEventListener('click', function(){
      this.closest('.rule')?.remove();
      checkRulesEmpty(this.dataset.mode);
    });
  });
}

/* ==========================================
   ADMIN PANEL (Batch 8)
   ========================================== */
function openAdminPanel(){
  openModal('m-admin');
}

/* ===== Dashboard Switcher ===== */
function updateActiveDashboardBanner(){
  const nameEl = document.getElementById('activeDashboardName');
  const slugEl = document.getElementById('activeDashboardSlug');
  const iconEl = document.getElementById('activeDashboardIcon');
  const subEl = document.getElementById('dashSwitcherSub');
  if(nameEl) nameEl.textContent = currentDashboardName || 'Dashboard';
  if(slugEl) slugEl.textContent = dashboardsList.find(d => d.id === currentDashboardId)?.slug || 'default';
  if(iconEl) iconEl.className = 'fa-solid ' + (currentDashboardIcon || 'fa-layer-group');
  if(subEl) subEl.textContent = currentDashboardName || '—';
}

async function openDashboardSwitcher(){
  openModal('m-dash-switch');
  await loadDashboardList();
}

async function loadDashboardList(){
  const listEl = document.getElementById('dashSwitchList');
  if(!listEl) return;
  listEl.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

  try{
    const r = await api('/api/v1/dashboards');
    const d = await r.json();
    if(!d.success){ listEl.innerHTML = '<div class="empty"><div class="empty-title">Gagal memuat</div></div>'; return; }
    dashboardsList = d.dashboards || [];

    if(!dashboardsList.length){
      listEl.innerHTML = '<div class="empty"><div class="empty-title">Belum ada dashboard</div></div>';
      return;
    }

    listEl.innerHTML = dashboardsList.map(db => {
      const isActive = db.id === currentDashboardId;
      const isDefault = db.is_default === 1;
      return `<div class="dash-switch-item ${isActive?'active':''}" data-action="switch-dashboard" data-dashboard-id="${db.id}">
        <span class="dash-switch-icon"><i class="fa-solid ${esc(db.icon || 'fa-chart-line')}"></i></span>
        <div class="dash-switch-info">
          <div class="dash-switch-name">${esc(db.name)} ${isDefault ? '<span style="color:var(--accent-warn);font-size:11px;">★</span>' : ''}</div>
          <div class="dash-switch-slug">${esc(db.slug)}</div>
        </div>
        <div class="dash-switch-actions">
          ${!isDefault ? `<button class="dash-act-btn" data-action="set-default" data-dashboard-id="${db.id}" title="Set Default"><i class="fa-solid fa-star"></i></button>` : ''}
          <button class="dash-act-btn" data-action="edit-dashboard" data-dashboard-id="${db.id}" title="Edit"><i class="fa-solid fa-pen"></i></button>
        </div>
      </div>`;
    }).join('');
    listEl.querySelectorAll('[data-action="switch-dashboard"]').forEach(item => {
      item.addEventListener('click', (e) => {
        if (e.target.closest('.dash-switch-actions')) return;
        const id = parseInt(item.dataset.dashboardId, 10);
        if (Number.isFinite(id)) switchDashboard(id);
      });
    });
    listEl.querySelectorAll('[data-action="set-default"]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = parseInt(btn.dataset.dashboardId, 10);
        if (Number.isFinite(id)) setDashDefault(id);
      });
    });
    listEl.querySelectorAll('[data-action="edit-dashboard"]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = parseInt(btn.dataset.dashboardId, 10);
        if (Number.isFinite(id)) openDashboardForm(id);
      });
    });
  }catch(e){ listEl.innerHTML = '<div class="empty"><div class="empty-title">Gagal memuat</div></div>'; }
}

function switchDashboard(id){
  const db = dashboardsList.find(d => d.id === id);
  if(!db) return;
  if(id === currentDashboardId){ closeModal('m-dash-switch'); return; }
  closeModal('m-dash-switch');
  const url = db.is_default === 1 ? '/mobile' : `/mobile`;
  // Mobile tidak support /d/<slug>, jadi langsung ganti current + reload
  currentDashboardId = id;
  currentDashboardName = db.name;
  currentDashboardIcon = db.icon || 'fa-layer-group';
  // Save to localStorage for persistence
  try { localStorage.setItem('aaguard-mobile-dashboard', String(id)); } catch(e) {}
  toast(`Dashboard: ${db.name}`);
  setTimeout(() => window.location.reload(), 400);
}

async function setDashDefault(id){
  try{
    const r = await api(`/api/v1/dashboards/${id}/set-default`, {method:'POST'});
    const d = await r.json();
    if(d.success){ toast('Default diperbarui'); await loadDashboardList(); }
    else alert(d.error || 'Gagal');
  }catch(e){ alert('Koneksi gagal'); }
}

function openDashboardForm(id){
  closeModal('m-dash-switch');
  const title = document.getElementById('dashFormTitle');
  const editId = document.getElementById('dashFormId');
  const nameEl = document.getElementById('dashFormName');
  const slugEl = document.getElementById('dashFormSlug');
  const descEl = document.getElementById('dashFormDescription');
  const iconEl = document.getElementById('dashFormIcon');
  const defaultGroup = document.getElementById('dashFormDefaultGroup');
  const delBtn = document.getElementById('dashFormDeleteBtn');

  if(id){
    const db = dashboardsList.find(d => d.id === id); if(!db) return;
    title.textContent = 'Edit Dashboard';
    editId.value = String(id);
    nameEl.value = db.name || '';
    slugEl.value = db.slug || '';
    slugEl.setAttribute('readonly', 'readonly');
    slugEl.style.opacity = '0.6';
    descEl.value = db.description || '';
    iconEl.value = db.icon || 'fa-chart-line';
    defaultGroup.style.display = 'block';
    document.getElementById('dashFormIsDefault').checked = db.is_default === 1;
    delBtn.classList.toggle('hidden', db.is_default === 1);
  } else {
    title.textContent = 'Dashboard Baru';
    editId.value = '';
    nameEl.value = '';
    slugEl.value = '';
    slugEl.removeAttribute('readonly');
    slugEl.style.opacity = '';
    descEl.value = '';
    iconEl.value = 'fa-chart-line';
    defaultGroup.style.display = 'none';
    document.getElementById('dashFormIsDefault').checked = false;
    delBtn.classList.add('hidden');
  }
  openModal('m-dash-form');
}

async function saveDashboard(){
  const id = document.getElementById('dashFormId').value;
  const name = document.getElementById('dashFormName').value.trim();
  const slug = document.getElementById('dashFormSlug').value.trim().toLowerCase();
  const description = document.getElementById('dashFormDescription').value.trim();
  const icon = document.getElementById('dashFormIcon').value;
  const isDefault = document.getElementById('dashFormIsDefault').checked;

  if(!name){ alert('Nama dashboard wajib diisi'); return; }

  try{
    if(id){
      const r = await api(`/api/v1/dashboards/${id}`, {
        method: 'PUT',
        body: JSON.stringify({ name, description, icon }),
      });
      const d = await r.json();
      if(!d.success){ alert(d.error || 'Gagal'); return; }
      if(isDefault){
        await api(`/api/v1/dashboards/${id}/set-default`, { method: 'POST' });
      }
      closeModal('m-dash-form');
      toast('Dashboard diperbarui');
      await loadDashboardList();
    } else {
      const payload = { name, description, icon };
      if(slug) payload.slug = slug;
      const r = await api('/api/v1/dashboards', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      if(!d.success){ alert(d.error || 'Gagal'); return; }
      if(isDefault){
        await api(`/api/v1/dashboards/${d.id}/set-default`, { method: 'POST' });
      }
      closeModal('m-dash-form');
      toast('Dashboard dibuat');
      await loadDashboardList();
    }
  }catch(e){ alert('Error: ' + e.message); }
}

function deleteDashboard(){
  const id = document.getElementById('dashFormId').value;
  if(!id) return;
  const db = dashboardsList.find(d => d.id === parseInt(id, 10));
  if(!db) return;
  confirmModal('Hapus Dashboard', `Hapus dashboard "${db.name}" beserta semua widget di dalamnya?`, async () => {
    const r = await api(`/api/v1/dashboards/${id}`, { method: 'DELETE' });
    const d = await r.json();
    if(d.success){
      closeModal('m-dash-form');
      toast('Dashboard dihapus');
      await loadDashboardList();
    } else alert(d.error || 'Gagal');
  });
}

/* ===== User Management ===== */
async function openUserManagement(){
  openModal('m-users');
  switchUserView('list');
  await loadUsers();
}

function switchUserView(view){
  document.getElementById('userListView').style.display = view === 'form' ? 'none' : '';
  document.getElementById('userFormView').style.display = view === 'form' ? '' : 'none';
  const errEl = document.getElementById('userFormError');
  if(errEl) errEl.style.display = 'none';
}

async function loadUsers(){
  const listEl = document.getElementById('userList');
  if(!listEl) return;
  listEl.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

  try{
    const r = await api('/api/v1/users');
    const d = await r.json();
    if(!d.success){ listEl.innerHTML = '<div class="empty"><div class="empty-title">Gagal memuat</div></div>'; return; }
    userListCache = d.users || [];
    if(!userListCache.length){
      listEl.innerHTML = '<div class="empty"><div class="empty-title">Belum ada user</div></div>';
      return;
    }

    listEl.innerHTML = userListCache.map(u => {
      const isMe = currentUser && u.id === currentUser.id;
      const adminBadge = u.is_admin ? '<span class="user-badge admin">Admin</span>' : '<span class="user-badge">User</span>';
      const meBadge = isMe ? '<span class="user-badge me">Anda</span>' : '';
      const delBtn = !isMe ? `<button class="user-act-btn danger" data-action="delete-user" data-user-id="${u.id}"><i class="fa-solid fa-trash"></i></button>` : '';
      return `<div class="user-card">
        <div class="user-avatar ${u.is_admin ? 'admin' : ''}">
          <i class="fa-solid ${u.is_admin ? 'fa-shield-halved' : 'fa-user'}"></i>
        </div>
        <div class="user-info">
          <div class="user-name">${esc(u.display_name || u.username)} ${adminBadge} ${meBadge}</div>
          <div class="user-username">@${esc(u.username)}</div>
        </div>
        <div class="user-actions">
          <button class="user-act-btn" data-action="edit-user" data-user-id="${u.id}"><i class="fa-solid fa-pen"></i></button>
          ${delBtn}
        </div>
      </div>`;
    }).join('');
    listEl.querySelectorAll('[data-action="edit-user"]').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = parseInt(btn.dataset.userId, 10);
        if (Number.isFinite(id)) openUserForm(id);
      });
    });
    listEl.querySelectorAll('[data-action="delete-user"]').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = parseInt(btn.dataset.userId, 10);
        if (Number.isFinite(id)) deleteUser(id);
      });
    });
  }catch(e){ listEl.innerHTML = '<div class="empty"><div class="empty-title">Gagal memuat</div></div>'; }
}

function openUserForm(id){
  switchUserView('form');
  const idEl = document.getElementById('userFormId');
  const userEl = document.getElementById('userFormUsername');
  const nameEl = document.getElementById('userFormDisplayName');
  const passEl = document.getElementById('userFormPassword');
  const adminEl = document.getElementById('userFormIsAdmin');
  const saveLabel = document.getElementById('userSaveBtn');

  if(id){
    const u = userListCache.find(x => x.id === id); if(!u) return;
    idEl.value = String(u.id);
    userEl.value = u.username || '';
    userEl.setAttribute('readonly', 'readonly');
    nameEl.value = u.display_name || '';
    passEl.value = '';
    adminEl.checked = u.is_admin === true;
    document.getElementById('userFormPasswordLabel').textContent = 'Password Baru (kosongkan jika tidak diubah)';
    if(saveLabel) saveLabel.textContent = 'Update';
  } else {
    idEl.value = '';
    userEl.value = '';
    userEl.removeAttribute('readonly');
    nameEl.value = '';
    passEl.value = '';
    adminEl.checked = false;
    document.getElementById('userFormPasswordLabel').textContent = 'Password';
    if(saveLabel) saveLabel.textContent = 'Simpan';
  }
}

async function saveUserForm(){
  const id = document.getElementById('userFormId').value;
  const username = document.getElementById('userFormUsername').value.trim();
  const displayName = document.getElementById('userFormDisplayName').value.trim();
  const password = document.getElementById('userFormPassword').value;
  const isAdmin = document.getElementById('userFormIsAdmin').checked;

  const errEl = document.getElementById('userFormError');
  errEl.style.display = 'none';

  if(!id){
    if(!username || username.length < 3){ errEl.textContent = 'Username minimal 3 karakter'; errEl.style.display = 'block'; return; }
    if(!password || password.length < 8){ errEl.textContent = 'Password minimal 8 karakter'; errEl.style.display = 'block'; return; }
  } else {
    if(password && password.length < 8){ errEl.textContent = 'Password baru minimal 8 karakter'; errEl.style.display = 'block'; return; }
  }

  try{
    if(!id){
      const r = await api('/api/v1/users', {
        method: 'POST',
        body: JSON.stringify({ username, password, display_name: displayName || username, is_admin: isAdmin }),
      });
      const d = await r.json();
      if(d.success){ toast('User dibuat'); switchUserView('list'); await loadUsers(); }
      else { errEl.textContent = d.error || 'Gagal'; errEl.style.display = 'block'; }
    } else {
      const payload = { is_admin: isAdmin };
      if(displayName) payload.display_name = displayName;
      if(password) payload.password = password;
      const r = await api(`/api/v1/users/${id}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      if(d.success){ toast('User diperbarui'); switchUserView('list'); await loadUsers(); }
      else { errEl.textContent = d.error || 'Gagal'; errEl.style.display = 'block'; }
    }
  }catch(e){ errEl.textContent = 'Koneksi gagal'; errEl.style.display = 'block'; }
}

function deleteUser(id, username){
  const u = userListCache.find(x => x.id === id);
  const name = username != null ? username : (u ? u.username : '');
  confirmModal('Hapus User', `Hapus user @${name}? Semua dashboard miliknya akan ikut terhapus.`, async () => {
    const r = await api(`/api/v1/users/${id}`, { method: 'DELETE' });
    const d = await r.json();
    if(d.success){ toast('User dihapus'); await loadUsers(); }
    else alert(d.error || 'Gagal');
  });
}

/* ===== Backup ===== */
async function openBackupPanel(){
  openModal('m-backup');
  await loadBackupList();
}

async function loadBackupList(){
  const listEl = document.getElementById('backupList');
  const countEl = document.getElementById('backupListCount');
  const autoEl = document.getElementById('backupAutoStatus');
  const intEl = document.getElementById('backupInterval');
  const retEl = document.getElementById('backupRetention');
  if(!listEl) return;

  listEl.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

  try{
    const r = await api('/api/v1/system/backups');
    const d = await r.json();
    if(!d.success){
      listEl.innerHTML = '<div class="empty"><div class="empty-title">Gagal memuat</div></div>';
      return;
    }
    if(autoEl){ autoEl.textContent = d.auto_backup_enabled ? 'Aktif' : 'Nonaktif'; autoEl.style.color = d.auto_backup_enabled ? 'var(--accent-ok)' : 'var(--text-3)'; }
    if(intEl) intEl.textContent = d.auto_backup_enabled ? `${d.backup_interval_hours} jam` : '—';
    if(retEl) retEl.textContent = `${d.retention_days} hari`;

    const backups = d.backups || [];
    if(countEl) countEl.textContent = backups.length ? `${backups.length} file` : '';
    if(!backups.length){
      listEl.innerHTML = '<div class="empty"><div class="empty-title">Belum ada backup</div></div>';
      return;
    }

    listEl.innerHTML = backups.map(b => `
      <div class="backup-item-m">
        <div class="backup-item-icon"><i class="fa-solid fa-database"></i></div>
        <div class="backup-item-info">
          <div class="backup-item-name">${esc(b.filename)}</div>
          <div class="backup-item-meta">${(b.size_bytes/1024/1024).toFixed(2)} MB · ${esc(b.created_at)}</div>
        </div>
        <a class="backup-dl-btn" href="/api/v1/system/backups/${encodeURIComponent(b.filename)}" download>
          <i class="fa-solid fa-download"></i>
        </a>
      </div>
    `).join('');
  }catch(e){ listEl.innerHTML = '<div class="empty"><div class="empty-title">Koneksi gagal</div></div>'; }
}

async function triggerBackup(){
  const btn = document.getElementById('backupNowBtn');
  if(!btn) return;
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Memproses...';
  try{
    const r = await api('/api/v1/system/backup', { method: 'POST' });
    const d = await r.json();
    if(d.success){ toast(d.message || 'Backup dibuat'); await loadBackupList(); }
    else alert(d.error || 'Gagal');
  }catch(e){ alert('Koneksi gagal'); }
  finally{ btn.disabled = false; btn.innerHTML = orig; }
}

/* ===== Restore ===== */
async function openRestore(){
  document.getElementById('restoreConfirmInput').value = '';
  document.getElementById('restoreConfirmBtn').disabled = true;
  document.getElementById('restoreError').style.display = 'none';
  openModal('m-restore');
  await loadRestoreFileList();

  const sel = document.getElementById('restoreFileSelect');
  const inp = document.getElementById('restoreConfirmInput');
  sel.onchange = updateRestoreBtn;
  inp.oninput = updateRestoreBtn;
}

async function loadRestoreFileList(){
  const sel = document.getElementById('restoreFileSelect');
  if(!sel) return;
  sel.innerHTML = '<option value="">— Memuat —</option>';
  try{
    const r = await api('/api/v1/system/backups');
    const d = await r.json();
    if(!d.success) return;
    const backups = d.backups || [];
    if(!backups.length){
      sel.innerHTML = '<option value="">Tidak ada file</option>';
      return;
    }
    sel.innerHTML = '<option value="">— Pilih file —</option>' + backups.map(b =>
      `<option value="${esc(b.filename)}">${esc(b.filename)} (${b.size_mb} MB)</option>`
    ).join('');
  }catch(e){}
}

function updateRestoreBtn(){
  const sel = document.getElementById('restoreFileSelect');
  const inp = document.getElementById('restoreConfirmInput');
  const btn = document.getElementById('restoreConfirmBtn');
  if(!btn) return;
  btn.disabled = !(sel.value && inp.value.trim().toUpperCase() === 'RESTORE');
}

function submitRestore(){
  const sel = document.getElementById('restoreFileSelect');
  const inp = document.getElementById('restoreConfirmInput');
  const errEl = document.getElementById('restoreError');
  const btn = document.getElementById('restoreConfirmBtn');
  if(!sel.value || inp.value.trim().toUpperCase() !== 'RESTORE'){
    errEl.textContent = 'Pilih file + ketik RESTORE';
    errEl.style.display = 'block';
    return;
  }
  const filename = sel.value;
  confirmModal('Restore Database', `YAKIN restore dari "${filename}"? Semua data akan digantikan!`, async () => {
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Restore...';
    try{
      const r = await api('/api/v1/system/restore', {
        method: 'POST',
        body: JSON.stringify({ filename, confirm: 'RESTORE' }),
      });
      const d = await r.json();
      if(d.success){
        closeModal('m-restore');
        toast('Restore berhasil! Reload halaman.', 'success');
        setTimeout(() => window.location.reload(), 2000);
      } else {
        errEl.textContent = d.error || 'Gagal';
        errEl.style.display = 'block';
      }
    }catch(e){
      errEl.textContent = 'Koneksi gagal';
      errEl.style.display = 'block';
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> Restore';
    }
  });
}

/* ===== Bulk Import ===== */
function openBulkImport(){
  switchBulkView('paste');
  document.getElementById('bulkJson').value = '';
  document.getElementById('bulkFileName').style.display = 'none';
  document.getElementById('bulkPreview').style.display = 'none';
  document.getElementById('bulkError').style.display = 'none';
  bulkImportParsed = [];
  openModal('m-bulk');

  document.getElementById('bulkJson').oninput = debounce(parseBulkJson, 400);
  document.getElementById('bulkFileInput').onchange = (e) => {
    const f = e.target.files[0]; if(f) handleBulkCsvFile(f);
  };
}

function debounce(fn, ms){
  let t;
  return function(...args){
    clearTimeout(t);
    t = setTimeout(() => fn.apply(this, args), ms);
  };
}

function switchBulkView(mode){
  document.querySelectorAll('#m-bulk .bulk-import-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.mode === mode);
  });
  document.getElementById('bulkPasteView').style.display = mode === 'paste' ? '' : 'none';
  document.getElementById('bulkCsvView').style.display = mode === 'csv' ? '' : 'none';
}

function parseBulkJson(){
  const txt = document.getElementById('bulkJson');
  const err = document.getElementById('bulkError');
  if(!txt) return;
  err.style.display = 'none';
  const raw = txt.value.trim();
  if(!raw){ bulkImportParsed = []; renderBulkPreview(); return; }
  try{
    const parsed = JSON.parse(raw);
    if(!Array.isArray(parsed)) throw new Error('Harus array');
    bulkImportParsed = parsed;
    renderBulkPreview();
  }catch(e){
    bulkImportParsed = [];
    err.textContent = 'JSON tidak valid: ' + e.message;
    err.style.display = 'block';
    renderBulkPreview();
  }
}

function handleBulkCsvFile(file){
  const nameEl = document.getElementById('bulkFileName');
  nameEl.textContent = file.name + ' (' + (file.size/1024).toFixed(1) + ' KB)';
  nameEl.style.display = 'block';

  const reader = new FileReader();
  reader.onload = (e) => {
    const lines = e.target.result.split(/\r?\n/).filter(l => l.trim());
    if(lines.length < 2){ bulkImportParsed = []; renderBulkPreview(); return; }
    const headers = lines[0].split(',').map(h => h.trim().toLowerCase().replace(/\s+/g, '_'));
    const rows = [];
    for(let i = 1; i < lines.length; i++){
      const cells = lines[i].split(',').map(c => c.trim().replace(/^"|"$/g, ''));
      const obj = {};
      headers.forEach((h, idx) => {
        if(cells[idx] !== undefined && cells[idx] !== '') obj[h] = cells[idx];
      });
      rows.push(obj);
    }
    bulkImportParsed = rows;
    renderBulkPreview();
  };
  reader.readAsText(file);
}

function renderBulkPreview(){
  const wrap = document.getElementById('bulkPreview');
  const listEl = document.getElementById('bulkPreviewList');
  const countEl = document.getElementById('bulkPreviewCount');
  if(!wrap || !listEl) return;
  if(!bulkImportParsed.length){ wrap.style.display = 'none'; return; }
  wrap.style.display = 'block';
  if(countEl) countEl.textContent = `${bulkImportParsed.length} device`;

  listEl.innerHTML = bulkImportParsed.slice(0, 30).map((item, idx) => {
    const err = !item.device_id || !item.device_name;
    return `<div class="bulk-import-preview-item ${err ? 'error' : ''}">
      <span class="bulk-import-preview-row">${idx + 1}</span>
      <span class="bulk-import-preview-id">${esc(item.device_id || '?')}</span>
      <span class="bulk-import-preview-name">${esc(item.device_name || '—')}</span>
      ${err ? '<span class="bulk-import-preview-error">ID & Nama wajib</span>' : ''}
    </div>`;
  }).join('') + (bulkImportParsed.length > 30
    ? `<div style="text-align:center;padding:8px;font-size:11px;color:var(--text-3);">...+${bulkImportParsed.length - 30} baris</div>` : '');
}

function fillBulkSample(){
  document.getElementById('bulkJson').value = JSON.stringify([
    { device_id: "ESP32-001", device_name: "Sensor Suhu Server", device_type: "ESP32", location: "Ruang Server" },
    { device_id: "ESP32-002", device_name: "Sensor Gudang", device_type: "ESP32", location: "Gudang A" },
  ], null, 2);
  parseBulkJson();
}

function downloadBulkTemplate(){
  const csv = 'device_id,device_name,device_type,location,description,firmware_version\nESP32-001,Sensor Suhu Server,ESP32,Ruang Server,Monitoring suhu,\nESP32-002,Sensor Gudang,ESP32,Gudang A,,\n';
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'aaguard-bulk-template.csv';
  a.click();
  URL.revokeObjectURL(url);
}

async function submitBulkImport(){
  const errEl = document.getElementById('bulkError');
  errEl.style.display = 'none';

  const pasteV = document.getElementById('bulkPasteView');
  if(pasteV && pasteV.style.display !== 'none') parseBulkJson();

  if(!bulkImportParsed.length){
    errEl.textContent = 'Tidak ada device';
    errEl.style.display = 'block';
    return;
  }
  if(bulkImportParsed.length > 200){
    errEl.textContent = `Maks 200 device (dikirim ${bulkImportParsed.length})`;
    errEl.style.display = 'block';
    return;
  }

  const btn = document.getElementById('bulkSubmitBtn');
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Import...';

  try{
    const r = await api('/api/v1/devices/bulk-import', {
      method: 'POST',
      body: JSON.stringify({ devices: bulkImportParsed }),
    });
    const d = await r.json();
    if(d.success){
      closeModal('m-bulk');
      showBulkResult(d);
      loadDashboard();
    } else {
      errEl.textContent = d.error || 'Gagal';
      errEl.style.display = 'block';
    }
  }catch(e){ errEl.textContent = 'Koneksi gagal'; errEl.style.display = 'block'; }
  finally { btn.disabled = false; btn.innerHTML = orig; }
}

function showBulkResult(d){
  const s = d.summary || {};
  document.getElementById('bulkResultSummary').innerHTML = `
    <div class="bulk-result-stat ok"><div class="bulk-result-stat-value">${s.created||0}</div><div class="bulk-result-stat-label">Dibuat</div></div>
    <div class="bulk-result-stat warn"><div class="bulk-result-stat-value">${s.skipped||0}</div><div class="bulk-result-stat-label">Skip</div></div>
    <div class="bulk-result-stat crit"><div class="bulk-result-stat-value">${s.errors||0}</div><div class="bulk-result-stat-label">Error</div></div>
  `;
  const created = d.created || [];
  if(created.length){
    document.getElementById('bulkResultCreatedSection').style.display = 'block';
    document.getElementById('bulkResultCreatedCount').textContent = created.length;
    document.getElementById('bulkResultCreatedList').innerHTML = created.map(c => `
      <div class="bulk-result-row-m">
        <div><b>${esc(c.device_id)}</b> — ${esc(c.device_name)}</div>
        <code>${esc(c.api_key || '')}</code>
      </div>`).join('');
  } else {
    document.getElementById('bulkResultCreatedSection').style.display = 'none';
  }

  const skipped = d.skipped || [];
  if(skipped.length){
    document.getElementById('bulkResultSkippedSection').style.display = 'block';
    document.getElementById('bulkResultSkippedCount').textContent = skipped.length;
    document.getElementById('bulkResultSkippedList').innerHTML = skipped.map(s => `<div class="bulk-result-row-m">#${s.row} <b>${esc(s.device_id)}</b> — ${esc(s.reason||'')}</div>`).join('');
  } else {
    document.getElementById('bulkResultSkippedSection').style.display = 'none';
  }

  const errors = d.errors || [];
  if(errors.length){
    document.getElementById('bulkResultErrorSection').style.display = 'block';
    document.getElementById('bulkResultErrorCount').textContent = errors.length;
    document.getElementById('bulkResultErrorList').innerHTML = errors.map(e => `<div class="bulk-result-row-m">#${e.row||'?'} <b>${esc(e.device_id||'?')}</b> — ${esc(e.error||'')}</div>`).join('');
  } else {
    document.getElementById('bulkResultErrorSection').style.display = 'none';
  }

  window.__bulkCreated = created;
  openModal('m-bulk-result');
}

function copyBulkKeys(){
  const created = window.__bulkCreated || [];
  if(!created.length) return;
  const text = created.map(c => `${c.device_id} | ${c.api_key}`).join('\n');
  if(navigator.clipboard) navigator.clipboard.writeText(text).then(() => toast(`${created.length} key disalin`));
  else alert(text);
}

function downloadBulkCsv(){
  const created = window.__bulkCreated || [];
  if(!created.length) return;
  const csv = 'device_id,device_name,api_key\n' + created.map(c => `"${c.device_id}","${c.device_name}","${c.api_key}"`).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `bulk-keys-${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/* ===== Global Rules ===== */
async function openGlobalRules(){
  openModal('m-global-rules');
  await loadGlobalRules();
}

async function loadGlobalRules(){
  const listEl = document.getElementById('globalRulesList');
  const statusEl = document.getElementById('globalRulesStatus');
  const resetBtn = document.getElementById('globalRulesResetBtn');
  if(!listEl) return;

  listEl.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

  try{
    const r = await api('/api/v1/system/alert-rules');
    const d = await r.json();
    if(!d.success){ listEl.innerHTML = '<div class="empty"><div class="empty-title">Gagal memuat</div></div>'; return; }

    const rules = d.alert_rules || {};
    const isCustom = d.is_custom === true;

    if(statusEl){
      statusEl.style.display = 'block';
      if(isCustom){
        statusEl.style.background = 'var(--accent-info-bg)';
        statusEl.style.color = 'var(--accent-info)';
        statusEl.innerHTML = '<i class="fa-solid fa-pen"></i> Menggunakan rules custom';
      } else {
        statusEl.style.background = 'var(--surface-2)';
        statusEl.style.color = 'var(--text-3)';
        statusEl.innerHTML = '<i class="fa-solid fa-circle-check"></i> Default dari config';
      }
    }
    if(resetBtn) resetBtn.classList.toggle('hidden', !isCustom);

    const keys = Object.keys(rules);
    if(!keys.length){ listEl.innerHTML = '<div class="empty"><div class="empty-title">Tidak ada rules</div></div>'; return; }

    listEl.innerHTML = keys.map(key => {
      const rule = rules[key] || {};
      const label = SENSOR_LABELS[key] || key;
      const unit = SENSOR_UNITS[key] ?? '';
      const sevLabels = {healthy:'Normal', warning:'Warning', danger:'Bahaya'};
      const rows = ['healthy','warning','danger'].map(sev => {
        const r2 = rule[sev]; if(!r2) return '';
        return `<div class="rule-sev ${sev}">
          <div class="rule-sev-label"><span class="dot"></span>${sevLabels[sev]}</div>
          <input type="number" step="0.1" class="grule-input" data-sensor="${esc(key)}" data-severity="${sev}" data-field="min" value="${r2.min ?? 0}">
          <input type="number" step="0.1" class="grule-input" data-sensor="${esc(key)}" data-severity="${sev}" data-field="max" value="${r2.max ?? 0}">
        </div>`;
      }).join('');
      return `<div class="rule" style="margin-bottom:10px;">
        <div class="rule-head">
          <div style="font-weight:600;font-size:13px;flex:1;">${esc(label)}${unit ? ` <span style="font-family:var(--mono);color:var(--text-3);font-size:11px;">(${esc(unit)})</span>` : ''}</div>
        </div>
        ${rows}
      </div>`;
    }).join('');
  }catch(e){ listEl.innerHTML = '<div class="empty"><div class="empty-title">Koneksi gagal</div></div>'; }
}

async function saveGlobalRules(){
  const listEl = document.getElementById('globalRulesList');
  const rules = {};
  const sevMap = {};
  listEl.querySelectorAll('.grule-input').forEach(inp => {
    const key = inp.dataset.sensor;
    const sev = inp.dataset.severity;
    const field = inp.dataset.field;
    const val = parseFloat(inp.value);
    if(isNaN(val)) return;
    if(!sevMap[key]) sevMap[key] = {};
    if(!sevMap[key][sev]) sevMap[key][sev] = {};
    sevMap[key][sev][field] = val;
  });
  Object.keys(sevMap).forEach(key => {
    const rule = {};
    ['healthy','warning','danger'].forEach(sev => {
      if(sevMap[key][sev] && sevMap[key][sev].min !== undefined && sevMap[key][sev].max !== undefined){
        rule[sev] = sevMap[key][sev];
      }
    });
    if(Object.keys(rule).length) rules[key] = rule;
  });

  if(!Object.keys(rules).length){ alert('Minimal 1 rule'); return; }

  const btn = document.getElementById('globalRulesSaveBtn');
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Simpan...';

  try{
    const r = await api('/api/v1/system/alert-rules', { method: 'PUT', body: JSON.stringify(rules) });
    const d = await r.json();
    if(d.success){ toast('Global rules tersimpan'); closeModal('m-global-rules'); }
    else alert(d.error || 'Gagal');
  }catch(e){ alert('Koneksi gagal'); }
  finally { btn.disabled = false; btn.innerHTML = orig; }
}

async function resetGlobalRules(){
  confirmModal('Reset Global Rules', 'Reset ke default dari config.py?', async () => {
    const r = await api('/api/v1/system/alert-rules', { method: 'DELETE' });
    const d = await r.json();
    if(d.success){ toast('Direset ke default'); await loadGlobalRules(); }
    else alert(d.error || 'Gagal');
  });
}

/* ===== Notification Config ===== */
async function openNotifConfig(){
  openModal('m-notif');
  const body = document.getElementById('notifConfigBody');
  body.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

  try{
    const r = await api('/api/v1/notifications/config');
    const d = await r.json();
    if(!d.success){ body.innerHTML = '<div class="empty"><div class="empty-title">Gagal memuat</div></div>'; return; }
    const cfg = d.config || {};
    const tg = cfg.telegram || {};
    const vc = v => v ? 'ok' : 'crit';
    const bs = v => v ? 'Ya' : 'Tidak';

    body.innerHTML = `
      <div class="notif-config-section">
        <div class="notif-config-section-title">Umum</div>
        <div class="notif-config-row"><span class="notif-config-label">Notifikasi</span><span class="notif-config-value ${vc(cfg.notify_enabled)}">${bs(cfg.notify_enabled)}</span></div>
        <div class="notif-config-row"><span class="notif-config-label">Min Severity</span><span class="notif-config-value">${esc((cfg.min_severity||'warning').toUpperCase())}</span></div>
        <div class="notif-config-row"><span class="notif-config-label">Notif saat pulih</span><span class="notif-config-value ${vc(cfg.notify_on_cleared)}">${bs(cfg.notify_on_cleared)}</span></div>
      </div>
      <div class="notif-config-section">
        <div class="notif-config-section-title">Telegram</div>
        <div class="notif-config-row"><span class="notif-config-label">Aktif</span><span class="notif-config-value ${vc(tg.enabled)}">${bs(tg.enabled)}</span></div>
        <div class="notif-config-row"><span class="notif-config-label">Bot Token</span><span class="notif-config-value ${vc(tg.has_token)}">${tg.has_token ? '✓ Ada' : '✗ Kosong'}</span></div>
        <div class="notif-config-row"><span class="notif-config-label">Chat ID</span><span class="notif-config-value ${vc(tg.has_chat_id)}">${tg.has_chat_id ? '✓ Ada' : '✗ Kosong'}</span></div>
      </div>
      <div style="margin-top:14px;">
        <button class="btn btn-primary" id="testNotifBtn" style="width:100%;" ${!tg.enabled ? 'disabled' : ''}>
          <i class="fa-solid fa-paper-plane"></i> Test Telegram
        </button>
      </div>
      ${!cfg.notify_enabled ? `
        <div style="margin-top:14px;padding:10px;background:var(--accent-warn-bg);border-radius:var(--radius-md);font-size:11.5px;color:var(--accent-warn);line-height:1.5;">
          <i class="fa-solid fa-circle-info"></i> Aktifkan <code style="font-family:var(--mono);">NOTIFY_ENABLED=True</code> di .env
        </div>` : ''}
    `;
    const testBtn = document.getElementById('testNotifBtn');
    if (testBtn) testBtn.addEventListener('click', () => testNotifTelegram());
  }catch(e){ body.innerHTML = '<div class="empty"><div class="empty-title">Koneksi gagal</div></div>'; }
}

async function testNotifTelegram(){
  try{
    const r = await api('/api/v1/notifications/test-channel', {
      method: 'POST',
      body: JSON.stringify({ channel: 'telegram' }),
    });
    const d = await r.json();
    if(d.success) toast('Notifikasi terkirim');
    else alert('Gagal: ' + (d.error || 'Unknown'));
  }catch(e){ alert('Koneksi gagal'); }
}

/* ===== Cleanup ===== */
function openCleanup(){
  confirmModal('Cleanup Data', 'Jalankan cleanup data lama sekarang? Data lebih tua dari batas retensi akan dihapus.', async () => {
    toast('Cleanup berjalan...');
    try{
      const r = await api('/api/v1/system/cleanup', { method: 'POST' });
      const d = await r.json();
      if(d.success){
        toast(`Cleanup: ${d.total_deleted || 0} baris`);
        loadDashboard();
      } else alert(d.error || 'Gagal');
    }catch(e){ alert('Koneksi gagal'); }
  });
}

/* ===== System Info ===== */
async function openSystemInfo(){
  openModal('m-system');
  const body = document.getElementById('systemInfoBody');
  body.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

  try{
    const r = await api('/api/v1/system/info');
    const d = await r.json();
    if(!d.success){ body.innerHTML = '<div class="empty"><div class="empty-title">Gagal</div></div>'; return; }
    const i = d.info || {};
    const rows = [
      ['Versi', i.version || '—'],
      ['Perangkat', i.device_count ?? 0],
      ['Data Sensor', (i.sensor_data_count ?? 0).toLocaleString('id-ID')],
      ['Alert Aktif', i.active_alerts ?? 0],
      ['Riwayat Alert', (i.alert_history_count ?? 0).toLocaleString('id-ID')],
      ['Ukuran DB', `${i.database_size_mb ?? 0} MB`],
      ['Retensi', `${i.data_retention_days ?? 30} hari`],
    ];
    body.innerHTML = `<div class="info-list">
      ${rows.map(([l, v]) => `<div class="info-row"><span class="info-label">${esc(l)}</span><span class="info-value mono">${esc(String(v))}</span></div>`).join('')}
    </div>`;
  }catch(e){ body.innerHTML = '<div class="empty"><div class="empty-title">Gagal</div></div>'; }
}

/* ===== Change Password ===== */
function openChangePassword(){
  document.getElementById('cpOld').value = '';
  document.getElementById('cpNew').value = '';
  document.getElementById('cpConfirm').value = '';
  document.getElementById('cpError').style.display = 'none';
  openModal('m-chpw');
}

async function submitChangePassword(){
  const oldPw = document.getElementById('cpOld').value;
  const newPw = document.getElementById('cpNew').value;
  const confirmPw = document.getElementById('cpConfirm').value;
  const errEl = document.getElementById('cpError');
  errEl.style.display = 'none';

  if(!oldPw){ errEl.textContent = 'Password lama wajib'; errEl.style.display = 'block'; return; }
  if(!newPw || newPw.length < 8){ errEl.textContent = 'Password baru min 8 karakter'; errEl.style.display = 'block'; return; }
  if(newPw !== confirmPw){ errEl.textContent = 'Konfirmasi tidak cocok'; errEl.style.display = 'block'; return; }
  if(oldPw === newPw){ errEl.textContent = 'Password baru harus berbeda'; errEl.style.display = 'block'; return; }

  const btn = document.getElementById('cpSaveBtn');
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>...';

  try{
    const r = await api('/api/v1/users/me/password', {
      method: 'POST',
      body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
    });
    const d = await r.json();
    if(d.success){ closeModal('m-chpw'); toast('Password berhasil diubah'); }
    else { errEl.textContent = d.error || 'Gagal'; errEl.style.display = 'block'; }
  }catch(e){ errEl.textContent = 'Koneksi gagal'; errEl.style.display = 'block'; }
  finally { btn.disabled = false; btn.innerHTML = orig; }
}

/* ===== Toast helper (fallback) ===== */
if(!window.showToast){
  window.showToast = function(msg, type){
    const t = document.createElement('div');
    t.className = 'toast';
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => {
      t.style.opacity = '0';
      t.style.transition = 'opacity .3s';
      setTimeout(() => t.remove(), 300);
    }, 1800);
  };
}

/* ===== Init ===== */
(async function initMobile(){
  await loadCurrentUser();
  await loadDashboard();

  // Load dashboards for switcher
  try{
    const r = await api('/api/v1/dashboards');
    const d = await r.json();
    if(d.success){
      dashboardsList = d.dashboards || [];
      const saved = localStorage.getItem('aaguard-mobile-dashboard');
      const target = saved ? dashboardsList.find(x => x.id === parseInt(saved, 10)) : null;
      const def = target || dashboardsList.find(x => x.is_default) || dashboardsList[0];
      if(def){
        currentDashboardId = def.id;
        currentDashboardName = def.name;
        currentDashboardIcon = def.icon || 'fa-layer-group';
      }
      updateActiveDashboardBanner();
    }
  }catch(e){ console.warn(e); }
})();

// Periodic refresh
setInterval(loadDashboard, 30000);
setInterval(() => { if(document.getElementById('s-dashboard').classList.contains('active')) loadActivity(); }, 60000);
setInterval(() => { if(document.getElementById('s-alerts').classList.contains('active')) loadAlerts(); }, 20000);
