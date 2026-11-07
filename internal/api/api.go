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
}

type dashPage struct {
	Rows   []dashRow
	Alerts []store.Alert
	NewKey string // api_key baru dari form/rotate, tampil sekali di banner
	Th     store.Thresholds
	Saved  string
}

// calibrateForm: simpan kalibrasi ambang dari dashboard (Fase 4).
func (a *API) calibrateForm(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		http.Error(w, "form tidak valid", 400)
		return
	}
	if !a.adminOK(r.FormValue("admin_token")) {
		http.Error(w, "admin token salah", 401)
		return
	}
	get := func(k string) (float64, bool) {
		v, err := strconv.ParseFloat(r.FormValue(k), 64)
		return v, err == nil
	}
	tw, ok1 := get("temp_warn")
	td, ok2 := get("temp_danger")
	sw, ok3 := get("smoke_warn")
	sd, ok4 := get("smoke_danger")
	if !ok1 || !ok2 || !ok3 || !ok4 {
		http.Error(w, "semua ambang harus berupa angka", 400)
		return
	}
	if err := a.S.SetThresholds(store.Thresholds{TempWarn: tw, TempDanger: td, SmokeWarn: sw, SmokeDanger: sd}); err != nil {
		http.Error(w, err.Error(), 400)
		return
	}
	http.Redirect(w, r, "/?saved=kalibrasi", http.StatusSeeOther)
}

var dashTpl = template.Must(template.New("dash").Parse(`<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30"><title>iot-go</title>
<style>
:root{--bg:#fff;--fg:#111;--muted:#666;--border:#ddd;--card:#f7f7f7}
[data-theme="dark"]{--bg:#111;--fg:#eee;--muted:#999;--border:#333;--card:#1c1c1c}
*{box-sizing:border-box}body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--fg);max-width:900px;margin:2rem auto;padding:0 1rem}
header{display:flex;justify-content:space-between;align-items:center}
button{background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:.35rem .8rem;cursor:pointer}
table{width:100%;border-collapse:collapse}td,th{border:1px solid var(--border);padding:.4rem .6rem;text-align:left;font-size:.9rem}
code{background:var(--card);padding:.1rem .3rem} .muted{color:var(--muted);font-size:.85rem}
.badge{display:inline-block;padding:.1rem .45rem;border-radius:999px;font-size:.75rem;font-weight:700}
.ok{background:#e6f4ea;color:#137333}.warning{background:#fef7e0;color:#b06000}.danger{background:#fce8e6;color:#a50e0e}
</style></head>
<body><header><h1>iot-go</h1><button id="t" type="button">Tema: <span id="cur">…</span></button></header>
<p class="muted">Refresh otomatis 30 detik.</p>
{{if .NewKey}}<p style="background:var(--card);padding:.6rem;border-radius:6px">API key baru — salin sekarang, tidak bisa dilihat lagi:<br><code>{{.NewKey}}</code></p>{{end}}
<h2>Tambah device</h2>
<form method="post" action="/devices/form" style="display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:1rem">
<input name="device_id" placeholder="device_id (ESP32-001)" required>
<input name="name" placeholder="nama (Ruang Server)" required>
<input name="admin_token" type="password" placeholder="ADMIN_TOKEN" required>
<button type="submit">Tambah</button></form>
{{if .Saved}}<p style="background:var(--card);padding:.6rem;border-radius:6px">Kalibrasi tersimpan.</p>{{end}}
<h2>Kalibrasi sensor</h2>
<p class="muted">Normal = di bawah warning · Warning = warning s.d. danger · Danger = di atas danger.</p>
<form method="post" action="/thresholds/form" style="display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:1rem">
<label>DHT22 suhu (°C) normal &lt; <input name="temp_warn" type="number" step="0.5" value="{{.Th.TempWarn}}" style="width:4.5rem" required> warning s.d. <input name="temp_danger" type="number" step="0.5" value="{{.Th.TempDanger}}" style="width:4.5rem" required> danger</label>
<label>SMOKE (ppm) normal &lt; <input name="smoke_warn" type="number" step="1" value="{{.Th.SmokeWarn}}" style="width:4.5rem" required> warning s.d. <input name="smoke_danger" type="number" step="1" value="{{.Th.SmokeDanger}}" style="width:4.5rem" required> danger</label>
<input name="admin_token" type="password" placeholder="ADMIN_TOKEN" required>
<button type="submit">Simpan kalibrasi</button></form>
{{if not .Rows}}<p>Belum ada device. Isi form di atas atau via <code>POST /devices</code>.</p>{{end}}
{{range .Rows}}<h2>{{.Device.DeviceID}} — {{.Device.Name}}</h2>
<table><tr><th>Status</th><th>Terakhir terlihat</th><th>Sensor</th><th>Data</th><th>Waktu data</th></tr>
<tr><td><span class="badge {{.Status}}">{{.Status}}</span>{{if .StatusMsg}}<div class="muted">{{.StatusMsg}}</div>{{end}}</td><td>{{.Device.LastSeen}}</td>{{with .Latest}}<td>{{.SensorType}}</td><td><code>{{.Data}}</code></td><td>{{.Timestamp}}</td>{{else}}<td colspan="3">belum ada data</td>{{end}}</tr></table>
<h3>Riwayat (10 terakhir)</h3><table><tr><th>Waktu</th><th>Sensor</th><th>Data</th></tr>
{{range .History}}<tr><td>{{.Timestamp}}</td><td>{{.SensorType}}</td><td><code>{{.Data}}</code></td></tr>{{end}}</table>
<form method="post" action="/devices/{{.Device.DeviceID}}/rotate" style="margin:.4rem 0 1rem">
<input name="admin_token" type="password" placeholder="ADMIN_TOKEN" required>
<button type="submit">Generate API key baru</button>
<span class="muted">Key lama langsung mati — pakai ini bila key hilang.</span></form>{{end}}
<h2>Alert terbaru</h2>
{{if not .Alerts}}<p class="muted">Belum ada alert. Ambang: DHT22 suhu ≥30°C warning / ≥35°C danger; SMOKE ≥100 ppm warning / ≥200 ppm danger.</p>{{end}}
<table><tr><th>Waktu</th><th>Device</th><th>Level</th><th>Sensor</th><th>Pesan</th><th>Data</th></tr>
{{range .Alerts}}<tr><td>{{.Timestamp}}</td><td>{{.DeviceID}}</td><td><span class="badge {{.Level}}">{{.Level}}</span></td><td>{{.SensorType}}</td><td>{{.Message}}</td><td><code>{{.Data}}</code></td></tr>{{end}}</table>
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
	for i := range rows {
		if rows[i].Latest != nil {
			rows[i].Status, rows[i].StatusMsg = store.EvaluateWith(rows[i].Latest.SensorType, rows[i].Latest.Data, th)
		}
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	dashTpl.Execute(w, dashPage{Rows: rows, Alerts: alerts, NewKey: r.URL.Query().Get("new_key"), Th: th, Saved: r.URL.Query().Get("saved")})
}
