// Package api: semua HTTP. Tidak ada SQL di sini.
package api

import (
	"encoding/json"
	"errors"
	"html/template"
	"net/http"
	"strconv"

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
	mux.HandleFunc("GET /devices", a.listDevices)
	mux.HandleFunc("POST /data", a.ingest)
	mux.HandleFunc("GET /devices/{id}/history", a.history)
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

func (a *API) createDevice(w http.ResponseWriter, r *http.Request) {
	if a.AdminTok != "" && r.Header.Get("X-Admin-Token") != a.AdminTok {
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

type dashRow struct {
	Device  store.Device
	Latest  *store.Reading
	History []store.Reading
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
</style></head>
<body><header><h1>iot-go</h1><button id="t" type="button">Tema: <span id="cur">…</span></button></header>
<p class="muted">Refresh otomatis 30 detik.</p>
{{if not .}}<p>Belum ada device. Buat via <code>POST /devices</code>.</p>{{end}}
{{range .}}<h2>{{.Device.DeviceID}} — {{.Device.Name}}</h2>
<table><tr><th>Terakhir terlihat</th><th>Sensor</th><th>Data</th><th>Waktu data</th></tr>
<tr><td>{{.Device.LastSeen}}</td>{{with .Latest}}<td>{{.SensorType}}</td><td><code>{{.Data}}</code></td><td>{{.Timestamp}}</td>{{else}}<td colspan="3">belum ada data</td>{{end}}</tr></table>
<h3>Riwayat (10 terakhir)</h3><table><tr><th>Waktu</th><th>Sensor</th><th>Data</th></tr>
{{range .History}}<tr><td>{{.Timestamp}}</td><td>{{.SensorType}}</td><td><code>{{.Data}}</code></td></tr>{{end}}</table>{{end}}
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
		row := dashRow{Device: d, History: h}
		if len(h) > 0 {
			row.Latest = &h[0]
		}
		rows = append(rows, row)
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	dashTpl.Execute(w, rows)
}
