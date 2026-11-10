/* ============================================================
   AAguard Device Detail — v5
   Batch 7 integrated
   ============================================================ */
const CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
const deviceId = (document.querySelector('meta[name="device-id"]') || {}).content || '';

/* Skip link: bound via JS (no inline handlers, CSP-safe). */
const skipLink = document.getElementById('skipLink');
skipLink?.addEventListener('focus', () => { skipLink.style.left = '0'; });
skipLink?.addEventListener('blur', () => { skipLink.style.left = '-9999px'; });

/* ---------- Sensor meta ---------- */
const SENSOR_META = {
  temperature: {icon:'fa-temperature-half', color:'#ef6a6a', unit:'°C', range:[0,50]},
  humidity:    {icon:'fa-droplet',          color:'#5b9eff', unit:'%',  range:[0,100]},
  smoke:       {icon:'fa-smog',             color:'#a78bfa', unit:'ppm',range:[0,1000]},
  gas_level:   {icon:'fa-fire',             color:'#f59e0b', unit:'ppm',range:[0,100]},
};

const getSensor = k => SENSOR_META[k] || {icon:'fa-microchip', color:'#adb5c2', unit:'', range:[0,100]};
const gaugePct = (k,v) => {
  const [a,b] = getSensor(k).range;
  return Math.min(100, Math.max(0, ((v-a)/(b-a))*100));
};

/* ---------- Helpers ---------- */
const esc = s => { const d = document.createElement('div'); d.textContent = String(s ?? ''); return d.innerHTML; };
const fmtUp = s => {
  if(!s && s !== 0) return '—';
  s = parseInt(s) || 0;
  if(s < 60) return `${s}s`;
  const d = Math.floor(s/86400), h = Math.floor((s%86400)/3600), m = Math.floor((s%3600)/60);
  if(d > 0) return `${d}h ${h}j`;
  if(h > 0) return `${h}j ${m}m`;
  return `${m}m`;
};
const fmtTime = iso => {
  if(!iso) return '—';
  try{
    const d = new Date(String(iso).replace(' ','T') + '+07:00');
    return d.toLocaleString('id-ID', {
      day:'2-digit', month:'short', year:'numeric',
      hour:'2-digit', minute:'2-digit', second:'2-digit',
      timeZone:'Asia/Jakarta'
    }) + ' WIB';
  }catch(e){ return '—'; }
};
const fmtRelative = iso => {
  if(!iso) return '—';
  try{
    const d = new Date(String(iso).replace(' ','T') + '+07:00');
    const diff = (Date.now() - d.getTime()) / 1000;
    if(diff < 60) return 'baru saja';
    if(diff < 3600) return `${Math.floor(diff/60)} mnt lalu`;
    if(diff < 86400) return `${Math.floor(diff/3600)} jam lalu`;
    if(diff < 604800) return `${Math.floor(diff/86400)} hari lalu`;
    return d.toLocaleDateString('id-ID', {day:'2-digit', month:'short', timeZone:'Asia/Jakarta'});
  }catch(e){ return '—'; }
};

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

/* ---------- Modal ---------- */
function openModal(id){
  const el = document.getElementById(id);
  if(el){ el.classList.add('open'); document.body.style.overflow = 'hidden'; }
}
function closeModal(id){
  const el = document.getElementById(id);
  if(el) el.classList.remove('open');
  if(!document.querySelector('.modal.open')) document.body.style.overflow = '';
}
document.querySelectorAll('.modal').forEach(m => {
  m.addEventListener('click', e => { if(e.target === m) closeModal(m.id); });
});
document.addEventListener('keydown', e => {
  if(e.key === 'Escape') document.querySelectorAll('.modal.open').forEach(m => closeModal(m.id));
});

/* ---------- Theme ---------- */
updateThemeIcon();
window.ThemeManager.onChange(function(theme){
  updateThemeIcon();
  if(historyChart) loadHistoryChart();
});
function updateThemeIcon(){
  const i = document.getElementById('themeIcon');
  if(i) i.className = document.documentElement.getAttribute('data-theme') === 'light'
    ? 'fa-solid fa-sun'
    : 'fa-solid fa-moon';
}

/* ---------- Back ---------- */
(function setupBack(){
  const btn = document.getElementById('btnBack');
  let back = '/mobile';
  try{
    const stored = sessionStorage.getItem('aaguard_back_url');
    if(stored && stored.startsWith('/')) back = stored;
  }catch(e){}
  btn.onclick = () => {
    try{ sessionStorage.removeItem('aaguard_back_url'); }catch(e){}
    window.location.href = back;
  };
})();

/* ---------- Export ---------- */
(function setupExport(){
  const btn = document.getElementById('btnExport');
  const menu = document.getElementById('exportMenu');
  if(!btn || !menu) return;

  function closeMenu(){ menu.classList.remove('open'); }
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    menu.classList.toggle('open');
  });
  menu.querySelectorAll('.hdr-export-item').forEach(item => {
    item.addEventListener('click', (e) => {
      e.stopPropagation();
      const fmt = item.dataset.format || 'csv';
      const hours = item.dataset.hours || '24';
      window.location.href = `/api/v1/devices/${encodeURIComponent(deviceId)}/export?format=${encodeURIComponent(fmt)}&hours=${encodeURIComponent(hours)}`;
      closeMenu();
      toast(`Export ${fmt.toUpperCase()} (${hours} jam)...`);
    });
  });
  document.addEventListener('click', (e) => {
    if(!e.target.closest('.hdr-export-wrap')) closeMenu();
  });
  document.addEventListener('keydown', e => {
    if(e.key === 'Escape') closeMenu();
  });
})();

/* ---------- Status ---------- */
function renderStatus(device){
  const bar = document.getElementById('statusBar');
  const pulse = document.getElementById('statusPulse');
  const label = document.getElementById('statusLabel');
  const sub = document.getElementById('statusSub');
  const live = document.getElementById('liveBadge');

  let statusClass = device.status || 'offline';
  let statusText = statusClass.toUpperCase();
  let subText = '';
  let barClass = statusClass === 'online' ? 'ok' : 'crit';

  if(device.status === 'online'){
    subText = `Aktif ${fmtRelative(device.last_seen)}`;
  } else {
    subText = device.last_seen
      ? `Terakhir aktif ${fmtRelative(device.last_seen)}`
      : 'Belum pernah aktif';
  }

  if(device.active_alerts && device.active_alerts.length > 0){
    const top = device.active_alerts[0].severity;
    statusClass = top;
    if(top === 'danger'){ statusText = 'BAHAYA'; barClass = 'crit'; }
    else if(top === 'warning'){ statusText = 'PERINGATAN'; barClass = 'warn'; }
    else if(top === 'info'){ statusText = 'INFO'; barClass = 'info'; }
    subText = `${device.active_alerts.length} alert • ${subText}`;
  }

  bar.className = 'status-bar ' + barClass;
  pulse.className = 'status-pulse ' + statusClass;
  label.textContent = statusText;
  sub.textContent = subText;
  live.style.display = device.status === 'online' ? 'inline-flex' : 'none';
}

/* ---------- Alerts ---------- */
function renderAlerts(alerts){
  const body = document.getElementById('alertBody');
  const count = document.getElementById('alertCount');

  if(!alerts || !alerts.length){
    count.textContent = '';
    body.innerHTML = `
      <div class="empty">
        <i class="fa-solid fa-circle-check" style="color:var(--accent-ok);opacity:1;"></i>
        <div class="empty-title" style="color:var(--accent-ok);">Semua Normal</div>
        <div class="empty-sub">Tidak ada alert aktif</div>
      </div>`;
    return;
  }

  count.textContent = `${alerts.length} alert`;
  body.innerHTML = alerts.map(a => {
    const sev = a.severity || 'info';
    return `<div class="alert-item">
      <div class="alert-head">
        <span class="alert-sev ${sev}">${esc(sev)}</span>
        <span class="alert-head-type">${esc(a.alert_type || '')}</span>
      </div>
      <div class="alert-msg">${esc(a.message || '—')}</div>
      <div class="alert-meta">
        <span>${fmtTime(a.created_at)}</span>
      </div>
    </div>`;
  }).join('');
}

/* ---------- Info ---------- */
function renderInfo(device){
  const wifi = device.latest_data?.wifi_ssid || null;
  const uptime = fmtUp(device.latest_data?.uptime_seconds || 0);
  const interval = fmtUp(device.expected_interval || 60);
  const timeout = fmtUp(device.offline_timeout || 900);
  const lastSeen = device.last_seen ? fmtTime(device.last_seen) : null;

  const rows = [
    {label:'ID Perangkat', value:device.device_id, mono:true},
    {label:'Tipe', value:device.device_type || 'Universal'},
    {label:'Firmware', value:device.firmware_version || null, mono:true, muted:!device.firmware_version, emptyText:'—'},
    {label:'Lokasi', value:device.location || null, muted:!device.location, emptyText:'Belum diatur'},
    {label:'WiFi SSID', value:wifi, mono:true, muted:!wifi, emptyText:'—'},
    {label:'Uptime', value:uptime, mono:true},
    {label:'Interval Kirim', value:interval, mono:true},
    {label:'Offline Timeout', value:timeout, mono:true},
    {label:'Terakhir Aktif', value:lastSeen, muted:!lastSeen, emptyText:'Belum pernah'},
  ];

  if(device.description){
    rows.push({label:'Deskripsi', value:device.description});
  }

  document.getElementById('infoBody').innerHTML = `
    <div class="info-list">
      ${rows.map(r => {
        const cls = ['info-value', r.mono ? 'mono' : '', r.muted ? 'muted' : ''].filter(Boolean).join(' ');
        const val = r.value ?? (r.emptyText || '—');
        return `<div class="info-row">
          <span class="info-label">${esc(r.label)}</span>
          <span class="${cls}">${esc(val)}</span>
        </div>`;
      }).join('')}
    </div>
  `;
}

/* ---------- Sensors ---------- */
function renderSensors(device){
  const body = document.getElementById('sensorBody');
  const meta = document.getElementById('sensorMeta');

  if(!device.latest_data?.data){
    meta.textContent = '';
    body.innerHTML = `
      <div class="empty">
        <i class="fa-solid fa-satellite-dish"></i>
        <div class="empty-title">Belum Ada Data</div>
        <div class="empty-sub">Perangkat belum mengirimkan data sensor</div>
      </div>`;
    return;
  }

  const sd = device.latest_data.data;
  const entries = Object.entries(sd).filter(([k]) => k !== 'uid' && k !== 'card_id');

  meta.textContent = device.latest_data.sensor_type || '';

  if(!entries.length){
    body.innerHTML = '<div class="empty"><div class="empty-title">Tidak ada data sensor</div></div>';
    return;
  }

  body.innerHTML = `
    <div class="sensor-grid">
      ${entries.map(([k, v]) => {
        const m = getSensor(k);
        const label = k.replace(/_/g,' ').replace(/\b\w/g, c => c.toUpperCase());
        const pct = typeof v === 'number' ? gaugePct(k, v) : 0;
        return `<div class="sensor-card">
          <div class="sensor-head">
            <div class="sensor-icon" style="background:${m.color}22;color:${m.color};">
              <i class="fa-solid ${m.icon}"></i>
            </div>
            <div class="sensor-name">${esc(label)}</div>
          </div>
          <div class="sensor-value" style="color:${m.color};">${esc(String(v))}</div>
          <div class="sensor-unit">${esc(m.unit || '\u00A0')}</div>
          <div class="sensor-gauge">
            <div class="sensor-gauge-fill" style="width:${pct}%;background:${m.color};color:${m.color};"></div>
          </div>
        </div>`;
      }).join('')}
    </div>
  `;
}

/* ---------- Chart History (ECharts) ---------- */
let historyChart = null; // chart DOM element
let historyHours = 24;

const CHART_COLORS = [
  '#f97316', '#3b82f6', '#ef4444', '#8b5cf6',
  '#22c55e', '#14b8a6', '#f59e0b', '#ec4899',
];

function getChartTheme(){
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  return {
    grid: isLight ? 'rgba(0,0,0,0.06)' : 'rgba(255,255,255,0.08)',
    label: isLight ? '#737373' : '#a3a3a3',
  };
}

function ensureChart(el){
  if(!el || typeof echarts === 'undefined') return null;
  let inst = echarts.getInstanceByDom(el);
  if(!inst) inst = echarts.init(el, null, {renderer:'canvas'});
  if(!el._ro && typeof ResizeObserver !== 'undefined'){
    el._ro = new ResizeObserver(() => { try{ inst && !inst.isDisposed() && inst.resize(); }catch(e){} });
    el._ro.observe(el);
  }
  return inst;
}
function disposeChart(el){
  if(!el) return;
  try{ const inst = echarts.getInstanceByDom(el); if(inst) inst.dispose(); }catch(e){}
  try{ if(el._ro){ el._ro.disconnect(); el._ro=null; } }catch(e){}
}

function showChartFallback(msg){
  const el = document.getElementById('historyChartCanvas');
  const legendEl = document.getElementById('chartLegend');
  if(legendEl) legendEl.innerHTML = '';
  if(!el) return;
  disposeChart(el);
  historyChart = null;
  el.innerHTML = '';
  const parent = el.parentElement;
  if(parent && !parent.querySelector('.chart-empty-msg')){
    const msgEl = document.createElement('div');
    msgEl.className = 'chart-empty-msg';
    msgEl.innerHTML = '<i class="fa-solid fa-satellite-dish"></i><span>' + esc(msg) + '</span>';
    parent.appendChild(msgEl);
  } else if(parent){
    const m = parent.querySelector('.chart-empty-msg span'); if(m) m.textContent = msg;
  }
}

async function loadHistoryChart(){
  const canvas = document.getElementById('historyChartCanvas');
  if(!canvas) return;

  if(typeof echarts === 'undefined'){
    try{ if(window.AAGuardLazy) await window.AAGuardLazy.loadChartLibs(); }
    catch(e){ showChartFallback('ECharts gagal dimuat. Cek koneksi internet/CDN.'); return; }
    if(typeof echarts === 'undefined'){ showChartFallback('ECharts gagal dimuat. Cek koneksi internet/CDN.'); return; }
  }

  try{
    const limit = Math.min(historyHours * 100, 5000);
    const r = await fetch(`/api/v1/devices/${encodeURIComponent(deviceId)}/history?hours=${historyHours}&limit=${limit}`);
    const d = await r.json();

    if(!d.success || !d.history || !d.history.length){
      disposeChart(canvas); historyChart = null;
      const lg = document.getElementById('chartLegend'); if(lg) lg.innerHTML = '';
      canvas.innerHTML = '';
      const parent = canvas.parentElement;
      if(parent && !parent.querySelector('.chart-empty-msg')){
        const msg = document.createElement('div');
        msg.className = 'chart-empty-msg';
        msg.innerHTML = '<i class="fa-solid fa-satellite-dish"></i><span>Belum ada data history</span>';
        parent.appendChild(msg);
      }
      return;
    }

    const old = canvas.parentElement && canvas.parentElement.querySelector('.chart-empty-msg');
    if(old) old.remove();

    const allKeys = new Set();
    d.history.forEach(h => {
      Object.keys(h.data || {}).forEach(k => { if(k !== 'uid' && k !== 'card_id') allKeys.add(k); });
    });
    const keys = Array.from(allKeys);
    if(keys.length === 0){ disposeChart(canvas); historyChart = null; canvas.innerHTML=''; return; }

    const tsMs = d.history.map(h => {
      const ts = String(h.timestamp || '').replace(' ','T');
      const dt = new Date(/[+-]\d\d:\d\d$|Z$/.test(ts) ? ts : ts + '+07:00');
      return isNaN(dt.getTime()) ? null : dt.getTime();
    });

    const theme = getChartTheme();
    const font = 'Geist, -apple-system, sans-serif';
    const series = keys.map((key, i) => {
      const meta = getSensor(key);
      const color = CHART_COLORS[i % CHART_COLORS.length];
      const data = tsMs.map((t, idx) => {
        const v = d.history[idx].data?.[key];
        return (t==null) ? null : [t, (typeof v === 'number') ? v : null];
      }).filter(x => x && x[0]!=null);
      const name = key.replace(/_/g,' ').replace(/\b\w/g, c => c.toUpperCase()) + (meta.unit ? ` (${meta.unit})` : '');
      return {
        name, type: 'line', data, showSymbol: false, smooth: true,
        sampling: 'lttb', lineStyle: { width: 2.5, color }, itemStyle: { color },
        areaStyle: keys.length === 1 ? { color: color + '22' } : undefined,
        connectNulls: true, emphasis: { focus: 'series' },
      };
    });

    const chart = ensureChart(canvas);
    if(!chart) return;
    chart.setOption({
      animation: false,
      grid: { left: 42, right: 12, top: 8, bottom: 28, containLabel: false },
      tooltip: { trigger: 'axis', confine: true, axisPointer: { type: 'line' } },
      xAxis: { type: 'time', axisLine: { show:false }, axisTick: { show:false }, axisLabel: { color: theme.label, fontSize: 10, fontFamily: font }, splitLine: { show:false } },
      yAxis: { type: 'value', scale: true, axisLabel: { color: theme.label, fontSize: 10, fontFamily: font }, splitLine: { lineStyle: { color: theme.grid } } },
      series,
    }, { notMerge: true, lazyUpdate: true });
    historyChart = canvas;

    const legendEl = document.getElementById('chartLegend');
    if(legendEl){
      legendEl.innerHTML = series.map(s => `<div class="chart-legend-item"><span class="chart-legend-dot" style="background:${s.lineStyle.color};"></span><span class="chart-legend-label">${esc(s.name)}</span></div>`).join('');
    }
  }catch(e){
    console.error('[Chart] Error:', e);
  }
}

function bindChartRange(){
  const picker = document.getElementById('chartRangePicker');
  if(!picker) return;
  picker.querySelectorAll('.chart-range-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      picker.querySelectorAll('.chart-range-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      historyHours = parseInt(btn.dataset.hours, 10) || 24;
      loadHistoryChart();
    });
  });
}


/* ---------- Status History ---------- */
function statusReasonLabel(reason){
  if(!reason) return '—';
  const map = {
    'data_received': 'Data diterima',
    'recovered': 'Pulih',
    'never_seen': 'Belum pernah terdeteksi',
  };
  if(map[reason]) return map[reason];
  if(reason.startsWith('timeout_')) {
    const secs = parseInt(reason.replace('timeout_','').replace('s',''));
    if(!isNaN(secs)) return `Timeout ${secs}s`;
  }
  return reason;
}

function renderStatusHistory(history){
  const body = document.getElementById('statusHistoryBody');
  const meta = document.getElementById('statusHistoryMeta');

  if(!history || !history.length){
    if(meta) meta.textContent = '';
    body.innerHTML = `
      <div class="empty">
        <i class="fa-solid fa-clock-rotate-left"></i>
        <div class="empty-title">Belum Ada Riwayat</div>
        <div class="empty-sub">Belum ada perubahan status tercatat</div>
      </div>`;
    return;
  }

  if(meta) meta.textContent = `${history.length} log`;

  body.innerHTML = history.map(h => {
    const isOnline = h.status === 'online';
    const color = isOnline ? 'var(--accent-ok)' : 'var(--accent-crit)';
    const icon = isOnline ? 'fa-circle-check' : 'fa-power-off';
    const title = isOnline ? 'Online' : 'Offline';
    const reason = statusReasonLabel(h.reason);
    return `
      <div class="status-log-item">
        <span class="status-log-icon" style="background:${color}22;color:${color};">
          <i class="fa-solid ${icon}"></i>
        </span>
        <div class="status-log-body">
          <div class="status-log-title">
            <span style="color:${color};">${title}</span>
            <span class="status-log-reason">${esc(reason)}</span>
          </div>
          <div class="status-log-time" title="${esc(fmtTime(h.created_at))}">${esc(fmtRelative(h.created_at))}</div>
        </div>
      </div>
    `;
  }).join('');
}

async function loadStatusHistory(){
  const body = document.getElementById('statusHistoryBody');
  if(!body) return;

  try{
    const r = await fetch(`/api/v1/devices/${encodeURIComponent(deviceId)}/status-history?limit=30`);
    const d = await r.json();

    if(!d.success){
      body.innerHTML = `
        <div class="empty">
          <i class="fa-solid fa-triangle-exclamation"></i>
          <div class="empty-title">Gagal Memuat</div>
          <div class="empty-sub">${esc(d.error || 'Koneksi gagal')}</div>
        </div>`;
      return;
    }

    renderStatusHistory(d.history || []);
  }catch(e){
    console.error('[DeviceDetail] status-history', e);
    body.innerHTML = `
      <div class="empty">
        <i class="fa-solid fa-triangle-exclamation"></i>
        <div class="empty-title">Koneksi Gagal</div>
      </div>`;
  }
}

/* ---------- Load Detail ---------- */
async function loadDetail(){
  try{
    const r = await fetch(`/api/v1/devices/${encodeURIComponent(deviceId)}`);
    const d = await r.json();

    if(!d.success){
      document.getElementById('statusLabel').textContent = 'Gagal memuat';
      document.getElementById('statusSub').textContent = d.error || 'Perangkat tidak ditemukan';
      return;
    }

    const dev = d.device;
    document.getElementById('deviceName').textContent = dev.device_name || dev.device_id;
    document.getElementById('deviceIdDisplay').textContent = dev.device_id;

    renderStatus(dev);
    renderAlerts(dev.active_alerts);
    renderInfo(dev);
    renderSensors(dev);

  }catch(e){
    console.error('[DeviceDetail]', e);
    document.getElementById('infoBody').innerHTML = `
      <div class="empty">
        <i class="fa-solid fa-triangle-exclamation"></i>
        <div class="empty-title">Koneksi Gagal</div>
        <div class="empty-sub">Tidak dapat memuat data perangkat</div>
      </div>`;
  }
}

/* ---------- Regenerate Key ---------- */
async function regenKey(){
  if(!confirm(`Regenerate API Key untuk "${deviceId}"?\n\nKey lama tidak akan berfungsi lagi.`)) return;
  try{
    const r = await fetch(`/api/v1/devices/${encodeURIComponent(deviceId)}/regenerate-key`, {
      method: 'POST',
      headers: {'Content-Type':'application/json', 'X-CSRFToken': CSRF}
    });
    const d = await r.json();
    if(d.success){
      document.getElementById('keyValue').textContent = d.api_key;
      openModal('m-key');
    } else {
      alert('Gagal: ' + (d.error || ''));
    }
  }catch(e){ alert('Error: ' + e.message); }
}

function copyKey(){
  const key = document.getElementById('keyValue').textContent;
  if(navigator.clipboard){
    navigator.clipboard.writeText(key).then(() => toast('API Key disalin'));
  } else {
    alert('Copy manual:\n' + key);
  }
}

/* ---------- Delete ---------- */
function openDelete(){
  document.getElementById('delDesc').textContent =
    `Perangkat "${document.getElementById('deviceName').textContent}" akan dihapus permanen beserta semua data sensornya. Tindakan ini tidak dapat dibatalkan.`;
  document.getElementById('delLabel').innerHTML =
    `Ketik <code>${esc(deviceId)}</code> untuk konfirmasi`;
  const input = document.getElementById('delInput');
  input.value = '';
  input.placeholder = `Ketik ${deviceId}...`;
  document.getElementById('delBtn').disabled = true;
  openModal('m-del');
  setTimeout(() => input.focus(), 200);
}

document.getElementById('delInput').addEventListener('input', e => {
  document.getElementById('delBtn').disabled = e.target.value.trim() !== deviceId;
});

async function confirmDelete(){
  const input = document.getElementById('delInput').value.trim();
  if(input !== deviceId){ alert('Konfirmasi salah'); return; }

  const btn = document.getElementById('delBtn');
  btn.disabled = true;
  btn.textContent = 'Menghapus...';

  try{
    const r = await fetch(`/api/v1/devices/${encodeURIComponent(deviceId)}`, {
      method: 'DELETE',
      headers: {'X-CSRFToken': CSRF}
    });
    const d = await r.json();
    if(d.success){
      closeModal('m-del');
      try{ sessionStorage.removeItem('aaguard_back_url'); }catch(e){}
      toast('Perangkat dihapus');
      setTimeout(() => window.location.href = '/mobile', 500);
    } else {
      alert('Gagal: ' + (d.error || ''));
      btn.disabled = false;
      btn.textContent = 'Hapus';
    }
  }catch(e){
    alert('Error: ' + e.message);
    btn.disabled = false;
    btn.textContent = 'Hapus';
  }
}

/* ---------- Init ---------- */
loadDetail();
loadStatusHistory();
loadHistoryChart();
bindChartRange();

setInterval(loadDetail, 10000);
setInterval(() => {
  if(!document.hidden) loadStatusHistory();
}, 30000);

document.getElementById('statusHistoryRefreshBtn')?.addEventListener('click', () => {
  loadStatusHistory();
  loadHistoryChart();
  toast('Data di-refresh');
});