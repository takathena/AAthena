// Package api: semua HTTP. Tidak ada SQL di sini.
package api

import (
	"encoding/json"
	"errors"
	"html/template"
	"net/http"
	"net/url"
	"strconv"
	"strings"

	"iot-go/internal/store"
)

type API struct {
	S        *store.Store
	AdminTok string // kosong = POST /devices terbuka (dev saja)
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func bad(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}

func (a *API) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /", a.dashboard)
	mux.HandleFunc("POST /devices", a.createDevice)
	mux.HandleFunc("POST /devices/form", a.createDeviceForm)
	mux.HandleFunc("POST /devices/{id}/rotate", a.rotateKey)
	mux.HandleFunc("POST /thresholds/form", a.calibrateForm)
	mux.HandleFunc("POST /devices/{id}/calibrate", a.calibrateDeviceForm)
	mux.HandleFunc("POST /devices/{id}/calibrate/clear", a.calibrateDeviceClear)
	mux.HandleFunc("GET /devices", a.listDevices)
	mux.HandleFunc("POST /data", a.ingest)
	mux.HandleFunc("GET /devices/{id}/history", a.history)
	mux.HandleFunc("GET /alerts", a.alerts)
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]string{"status": "ok"})
	})
	return mux
}

func decodeBody(w http.ResponseWriter, r *http.Request, v any) bool {
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 64<<10)) // 64KB cukup untuk payload sensor.
	if err := dec.Decode(v); err != nil {
		bad(w, 400, "JSON tidak valid")
		return false
	}
	return true
}

func (a *API) adminOK(token string) bool { return a.AdminTok == "" || token == a.AdminTok }

func (a *API) createDevice(w http.ResponseWriter, r *http.Request) {
	if !a.adminOK(r.Header.Get("X-Admin-Token")) {
		bad(w, 401, "admin token salah")
		return
	}
	var in struct {
		DeviceID string `json:"device_id"`
		Name     string `json:"name"`
	}
	if decodeBody(w, r, &in) {
		if in.DeviceID == "" || in.Name == "" {
			bad(w, 400, "device_id dan name wajib")
			return
		}
		if len(in.DeviceID) > 64 || !validID(in.DeviceID) {
			bad(w, 400, "device_id tidak valid (huruf, angka, -_ saja)")
			return
		}
		key, err := a.S.CreateDevice(in.DeviceID, in.Name)
		if err != nil {
			bad(w, 400, err.Error())
			return
		}
		// api_key hanya dikembalikan di sini, sekali saja.
		writeJSON(w, 201, map[string]string{"device_id": in.DeviceID, "api_key": key})
	}
}

// createDeviceForm: tambah device langsung dari dashboard (form HTML, tanpa JS).
func (a *API) createDeviceForm(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		http.Error(w, "form tidak valid", 400)
		return
	}
	if !a.adminOK(r.FormValue("admin_token")) {
		http.Error(w, "admin token salah", 401)
		return
	}
	id, name := r.FormValue("device_id"), r.FormValue("name")
	if id == "" || name == "" || len(id) > 64 || !validID(id) {
		http.Error(w, "device_id/name wajib & valid (huruf, angka, -_ saja)", 400)
		return
	}
	key, err := a.S.CreateDevice(id, name)
	if err != nil {
		http.Error(w, err.Error(), 400)
		return
	}
	http.Redirect(w, r, "/?new_key="+url.QueryEscape(key), http.StatusSeeOther)
}

// rotateKey: generate api_key baru bila key hilang. Support JSON (header) & form dashboard.
func (a *API) rotateKey(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	token := r.Header.Get("X-Admin-Token")
	isForm := strings.Contains(r.Header.Get("Content-Type"), "application/x-www-form-urlencoded")
	if isForm {
		r.ParseForm()
		token = r.FormValue("admin_token")
	}
	if !a.adminOK(token) {
		bad(w, 401, "admin token salah")
		return
	}
	key, err := a.S.RotateKey(id)
	if errors.Is(err, store.ErrNotFound) {
		bad(w, 404, "device tidak ditemukan")
		return
	}
	if err != nil {
		bad(w, 500, "internal error")
		return
	}
	if isForm {
		http.Redirect(w, r, "/?new_key="+url.QueryEscape(key), http.StatusSeeOther)
		return
	}
	writeJSON(w, 200, map[string]string{"device_id": id, "api_key": key})
}

func validID(s string) bool {
	for _, c := range s {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '-' || c == '_') {
			return false
		}
	}
	return true
}

func (a *API) listDevices(w http.ResponseWriter, r *http.Request) {
	devs, err := a.S.ListDevices()
	if err != nil {
		bad(w, 500, "internal error")
		return
	}
	writeJSON(w, 200, devs)
}

func (a *API) ingest(w http.ResponseWriter, r *http.Request) {
	var in struct {
		DeviceID   string          `json:"device_id"`
		APIKey     string          `json:"api_key"`
		SensorType string          `json:"sensor_type"` // contoh: DHT22, SMOKE, GENERIC
		Data       json.RawMessage `json:"data"`
	}
	if decodeBody(w, r, &in) {
		if in.DeviceID == "" || in.APIKey == "" || in.SensorType == "" || len(in.Data) == 0 {
			bad(w, 400, "device_id, api_key, sensor_type, data wajib")
			return
		}
		err := a.S.InsertReading(in.DeviceID, in.APIKey, in.SensorType, string(in.Data))
		if errors.Is(err, store.ErrNotFound) {
			bad(w, 404, "device tidak ditemukan")
			return
		}
		if errors.Is(err, store.ErrBadKey) {
			bad(w, 401, "api_key salah")
			return
		}
		if err != nil {
			bad(w, 500, "internal error")
			return
		}
		writeJSON(w, 200, map[string]string{"status": "saved"})
	}
}

func (a *API) history(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	limit := 100
	if v := r.URL.Query().Get("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 && n <= 1000 {
			limit = n
		} else {
			bad(w, 400, "limit harus 1-1000")
			return
		}
	}
	rows, err := a.S.History(id, limit)
	if err != nil {
		bad(w, 500, "internal error")
		return
	}
	writeJSON(w, 200, rows)
}

func (a *API) alerts(w http.ResponseWriter, r *http.Request) {
	limit := 50
	if v := r.URL.Query().Get("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 && n <= 1000 {
			limit = n
		} else {
			bad(w, 400, "limit harus 1-1000")
			return
		}
	}
	rows, err := a.S.ListAlerts(limit)
	if err != nil {
		bad(w, 500, "internal error")
		return
	}
	writeJSON(w, 200, rows)
}

type dashRow struct {
	Device    store.Device
	Latest    *store.Reading
	History   []store.Reading
	Status    string // ok | warning | danger (dari data terakhir)
	StatusMsg string
	Th        store.Thresholds // ambang efektif device ini
	Custom    bool             // true = kalibrasi sendiri, false = ikut global
}

type dashPage struct {
	Rows                                    []dashRow
	Alerts                                  []store.Alert
	NewKey                                  string // api_key baru dari form/rotate, tampil sekali di banner
	Th                                      store.Thresholds
	Saved                                   string
	Total, Normal, Warn, Danger, AlertCount int
}

// parseThresholdForm membaca 4 angka ambang dari form; ok=false bila bukan angka.
func parseThresholdForm(r *http.Request) (t store.Thresholds, ok bool) {
	get := func(k string) (float64, bool) {
		v, err := strconv.ParseFloat(r.FormValue(k), 64)
		return v, err == nil
	}
	tw, ok1 := get("temp_warn")
	td, ok2 := get("temp_danger")
	sw, ok3 := get("smoke_warn")
	sd, ok4 := get("smoke_danger")
	return store.Thresholds{TempWarn: tw, TempDanger: td, SmokeWarn: sw, SmokeDanger: sd}, ok1 && ok2 && ok3 && ok4
}

// calibrateForm: simpan kalibrasi global dari dashboard (Fase 4).
func (a *API) calibrateForm(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		http.Error(w, "form tidak valid", 400)
		return
	}
	if !a.adminOK(r.FormValue("admin_token")) {
		http.Error(w, "admin token salah", 401)
		return
	}
	t, ok := parseThresholdForm(r)
	if !ok {
		http.Error(w, "semua ambang harus berupa angka", 400)
		return
	}
	if err := a.S.SetThresholds(t); err != nil {
		http.Error(w, err.Error(), 400)
		return
	}
	http.Redirect(w, r, "/?saved=kalibrasi", http.StatusSeeOther)
}

// calibrateDeviceForm: simpan kalibrasi khusus satu device (Fase 5, menimpa global).
func (a *API) calibrateDeviceForm(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := r.ParseForm(); err != nil {
		http.Error(w, "form tidak valid", 400)
		return
	}
	if !a.adminOK(r.FormValue("admin_token")) {
		http.Error(w, "admin token salah", 401)
		return
	}
	t, ok := parseThresholdForm(r)
	if !ok {
		http.Error(w, "semua ambang harus berupa angka", 400)
		return
	}
	if err := a.S.SetDeviceThresholds(id, t); err != nil {
		if errors.Is(err, store.ErrNotFound) {
			http.Error(w, "device tidak ditemukan", 404)
			return
		}
		http.Error(w, err.Error(), 400)
		return
	}
	http.Redirect(w, r, "/?saved=kalibrasi", http.StatusSeeOther)
}

// calibrateDeviceClear: hapus kalibrasi device → kembali ikut global.
func (a *API) calibrateDeviceClear(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := r.ParseForm(); err != nil {
		http.Error(w, "form tidak valid", 400)
		return
	}
	if !a.adminOK(r.FormValue("admin_token")) {
		http.Error(w, "admin token salah", 401)
		return
	}
	if err := a.S.ClearDeviceThresholds(id); err != nil {
		if errors.Is(err, store.ErrNotFound) {
			http.Error(w, "device tidak ditemukan", 404)
			return
		}
		http.Error(w, err.Error(), 400)
		return
	}
	http.Redirect(w, r, "/?saved=kalibrasi", http.StatusSeeOther)
}

var dashTpl = template.Must(template.New("dash").Parse(`<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30"><title>iot-go</title>
<style>
:root{--bg:#f8fafc;--surface:#fff;--fg:#0f172a;--muted:#64748b;--border:#e2e8f0;--card:#f1f5f9;--accent:#2563eb;--hairline:#e2e8f0}
[data-theme="dark"]{--bg:#0b1120;--surface:#111827;--fg:#e5e7eb;--muted:#94a3b8;--border:#1f2937;--card:#1f2937;--hairline:#1f2937}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--fg);font-size:15px;line-height:1.5}
.topbar{position:sticky;top:0;z-index:10;background:var(--surface);border-bottom:1px solid var(--hairline);padding:.6rem 1.2rem;display:flex;justify-content:space-between;align-items:center}
.brand{display:flex;align-items:center;gap:.6rem;font-weight:700;font-size:1.05rem}
.logo{width:32px;height:32px;border-radius:9px;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-size:.85rem}
.wrap{max-width:1080px;margin:0 auto;padding:1.2rem 1rem 3rem}
input,button{min-height:36px}
input{background:var(--surface);color:var(--fg);border:1px solid var(--border);border-radius:8px;padding:.35rem .6rem;font:inherit}
button{background:var(--accent);color:#fff;border:1px solid var(--accent);border-radius:8px;padding:.35rem .9rem;cursor:pointer;font-weight:600}
button:hover{opacity:.9}.ghost{background:var(--surface);color:var(--fg);border-color:var(--border)}
table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid var(--hairline);padding:.45rem .5rem;text-align:left;font-size:.9rem}
th{color:var(--muted);font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.03em}
code{background:var(--card);padding:.1rem .35rem;border-radius:6px;font-size:.85em} .muted{color:var(--muted);font-size:.85rem}
.badge{display:inline-block;padding:.15rem .55rem;border-radius:999px;font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.03em}
.ok{background:#dcfce7;color:#166534}.warning{background:#fef9c3;color:#854d0e}.danger{background:#fee2e2;color:#991b1b}
[data-theme="dark"] .ok{background:#14532d;color:#bbf7d0}[data-theme="dark"] .warning{background:#713f12;color:#fde68a}[data-theme="dark"] .danger{background:#7f1d1d;color:#fecaca}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:.8rem;margin:0 0 1.2rem}
.metric{background:var(--surface);border:1px solid var(--hairline);border-radius:14px;padding:1rem}
.metric .n{font-size:1.7rem;font-weight:800;line-height:1.1}.metric .l{color:var(--muted);font-size:.82rem;margin-top:.2rem}
.section{background:var(--surface);border:1px solid var(--hairline);border-radius:14px;padding:1.1rem;margin-bottom:1.2rem}
.section h2{margin:.1rem 0 .8rem;font-size:1.05rem}
.devices{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:1rem}
.device{background:var(--surface);border:1px solid var(--hairline);border-radius:14px;padding:1rem}
.device header{display:flex;justify-content:space-between;align-items:flex-start;gap:.5rem}
.device h3{margin:0;font-size:1rem}.device .sub{color:var(--muted);font-size:.85rem}
.big{font-size:1.35rem;font-weight:800;margin:.5rem 0 .1rem}
details{border-top:1px solid var(--hairline);margin-top:.6rem;padding-top:.5rem}
summary{cursor:pointer;font-weight:600;font-size:.9rem}
.form{display:flex;gap:.45rem;flex-wrap:wrap;margin:.4rem 0}
.banner{background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;border-radius:10px;padding:.7rem .9rem}
[data-theme="dark"] .banner{background:#172554;color:#bfdbfe;border-color:#1e3a8a}
@media(max-width:760px){.metrics{grid-template-columns:repeat(2,1fr)}.devices{grid-template-columns:1fr}}
</style></head>
<body><div class="topbar"><div class="brand"><span class="logo">◉</span> iot-go <span class="muted">monitoring sensor</span></div><button id="t" type="button" class="ghost">Tema: <span id="cur">…</span></button></div>
<main class="wrap">
<div class="metrics">
<div class="metric"><div class="n">{{.Total}}</div><div class="l">Total device</div></div>
<div class="metric"><div class="n">{{.Normal}}</div><div class="l">Normal</div></div>
<div class="metric"><div class="n">{{.Warn}}</div><div class="l">Warning</div></div>
<div class="metric"><div class="n">{{.Danger}}</div><div class="l">Danger</div></div>
</div>
<p class="muted">Refresh otomatis 30 detik · <a href="/alerts">API alert (JSON)</a></p>
{{if .NewKey}}<p class="banner">🔑 API key baru — salin sekarang, tidak bisa dilihat lagi:<br><code>{{.NewKey}}</code></p>{{end}}
{{if .Saved}}<p class="banner">✅ Kalibrasi tersimpan.</p>{{end}}
<div class="section"><h2>➕ Tambah device</h2>
<form method="post" action="/devices/form" class="form">
<input name="device_id" placeholder="device_id (ESP32-001)" required>
<input name="name" placeholder="nama (Ruang Server)" required>
<input name="admin_token" type="password" placeholder="ADMIN_TOKEN" required>
<button type="submit">Tambah device</button></form></div>
<div class="section"><h2>🌡️ Kalibrasi sensor (global)</h2>
<p class="muted">Normal = di bawah warning · Warning = warning s.d. danger · Danger = di atas danger. Dipakai device yang tidak punya kalibrasi sendiri.</p>
<form method="post" action="/thresholds/form" class="form">
<label>DHT22 suhu (°C) normal &lt; <input name="temp_warn" type="number" step="0.5" value="{{.Th.TempWarn}}" style="width:4.5rem" required> warning s.d. <input name="temp_danger" type="number" step="0.5" value="{{.Th.TempDanger}}" style="width:4.5rem" required> danger</label>
<label>SMOKE (ppm) normal &lt; <input name="smoke_warn" type="number" step="1" value="{{.Th.SmokeWarn}}" style="width:4.5rem" required> warning s.d. <input name="smoke_danger" type="number" step="1" value="{{.Th.SmokeDanger}}" style="width:4.5rem" required> danger</label>
<input name="admin_token" type="password" placeholder="ADMIN_TOKEN" required>
<button type="submit">Simpan kalibrasi</button></form></div>
{{if not .Rows}}<div class="section"><p class="muted">Belum ada device. Isi form Tambah device di atas.</p></div>{{end}}
<div class="devices">
{{range $row := .Rows}}<article class="device">
<header><div><h3>{{$row.Device.Name}}</h3><div class="sub">{{$row.Device.DeviceID}} · terlihat {{$row.Device.LastSeen}}</div></div><span class="badge {{$row.Status}}">{{$row.Status}}</span></header>
{{with $row.Latest}}<div class="big">{{.SensorType}} · <code>{{.Data}}</code></div><div class="muted">{{.Timestamp}}{{if $row.StatusMsg}} · {{$row.StatusMsg}}{{end}}</div>{{else}}<p class="muted">Belum ada data.</p>{{end}}
<details><summary>Riwayat 10 terakhir</summary><table><tr><th>Waktu</th><th>Sensor</th><th>Data</th></tr>
{{range .History}}<tr><td>{{.Timestamp}}</td><td>{{.SensorType}}</td><td><code>{{.Data}}</code></td></tr>{{end}}</table></details>
<details><summary>Kelola device</summary>
<form method="post" action="/devices/{{.Device.DeviceID}}/rotate" style="margin:.4rem 0 1rem">
<input name="admin_token" type="password" placeholder="ADMIN_TOKEN" required>
<button type="submit">Generate API key baru</button>
<span class="muted">Key lama langsung mati — pakai ini bila key hilang.</span></form>
<p class="muted">Kalibrasi device ini: {{if .Custom}}<b>sendiri</b> (global tidak dipakai){{else}}<b>ikut global</b>{{end}} — DHT22 normal &lt; {{.Th.TempWarn}}°C, warning s.d. {{.Th.TempDanger}}°C, danger ≥ {{.Th.TempDanger}}°C · SMOKE normal &lt; {{.Th.SmokeWarn}} ppm, warning s.d. {{.Th.SmokeDanger}} ppm, danger ≥ {{.Th.SmokeDanger}} ppm.</p>
<form method="post" action="/devices/{{.Device.DeviceID}}/calibrate" style="display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:.4rem">
<label>Suhu warning <input name="temp_warn" type="number" step="0.5" value="{{.Th.TempWarn}}" style="width:4rem" required> danger <input name="temp_danger" type="number" step="0.5" value="{{.Th.TempDanger}}" style="width:4rem" required></label>
<label>Asap warning <input name="smoke_warn" type="number" step="1" value="{{.Th.SmokeWarn}}" style="width:4rem" required> danger <input name="smoke_danger" type="number" step="1" value="{{.Th.SmokeDanger}}" style="width:4rem" required></label>
<input name="admin_token" type="password" placeholder="ADMIN_TOKEN" required>
<button type="submit">Set kalibrasi device</button></form>
{{if .Custom}}<form method="post" action="/devices/{{.Device.DeviceID}}/calibrate/clear" style="margin-bottom:1rem">
<input name="admin_token" type="password" placeholder="ADMIN_TOKEN" required>
<button type="submit">Hapus → ikut global lagi</button></form>{{end}}</details>
</article>{{end}}</div>
<div class="section"><h2>🚨 Alert terbaru</h2>
{{if not .Alerts}}<p class="muted">Belum ada alert. Ambang: DHT22 suhu ≥30°C warning / ≥35°C danger; SMOKE ≥100 ppm warning / ≥200 ppm danger.</p>{{end}}
<table><tr><th>Waktu</th><th>Device</th><th>Level</th><th>Sensor</th><th>Pesan</th><th>Data</th></tr>
{{range .Alerts}}<tr><td>{{.Timestamp}}</td><td>{{.DeviceID}}</td><td><span class="badge {{.Level}}">{{.Level}}</span></td><td>{{.SensorType}}</td><td>{{.Message}}</td><td><code>{{.Data}}</code></td></tr>{{end}}</table></div>
</main>
<script>
const root=document.documentElement,cur=document.getElementById('cur');
function apply(t){root.dataset.theme=t;cur.textContent=t;localStorage.setItem('theme',t)}
apply(localStorage.getItem('theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'));
document.getElementById('t').onclick=()=>apply(root.dataset.theme==='dark'?'light':'dark');
</script>
</body></html>`))

func (a *API) dashboard(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	devs, err := a.S.ListDevices()
	if err != nil {
		bad(w, 500, "internal error")
		return
	}
	rows := make([]dashRow, 0, len(devs))
	for _, d := range devs {
		h, _ := a.S.History(d.DeviceID, 10)
		row := dashRow{Device: d, History: h, Status: "ok"}
		if len(h) > 0 {
			row.Latest = &h[0]
			row.Status, row.StatusMsg = store.Evaluate(h[0].SensorType, h[0].Data)
		}
		rows = append(rows, row)
	}
	alerts, _ := a.S.ListAlerts(20)
	th := a.S.Thresholds()
	page := dashPage{Rows: rows, Alerts: alerts, NewKey: r.URL.Query().Get("new_key"), Th: th, Saved: r.URL.Query().Get("saved"), Total: len(rows), AlertCount: len(alerts)}
	for i := range rows {
		rows[i].Th, rows[i].Custom = a.S.DeviceCalibration(rows[i].Device.DeviceID)
		if rows[i].Latest != nil {
			rows[i].Status, rows[i].StatusMsg = store.EvaluateWith(rows[i].Latest.SensorType, rows[i].Latest.Data, rows[i].Th)
		}
		switch rows[i].Status {
		case "warning":
			page.Warn++
		case "danger":
			page.Danger++
		}
	}
	page.Normal = page.Total - page.Warn - page.Danger
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	dashTpl.Execute(w, page)
}
