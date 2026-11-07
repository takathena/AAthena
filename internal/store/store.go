// Package store: semua akses SQLite. Tidak ada logika HTTP di sini.
package store

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	_ "modernc.org/sqlite"
)

var ErrNotFound = errors.New("not found")
var ErrBadKey = errors.New("invalid api_key")

type Store struct {
	db *sql.DB
	mu sync.RWMutex
	th Thresholds
}

type Device struct {
	DeviceID  string `json:"device_id"`
	Name      string `json:"name"`
	LastSeen  string `json:"last_seen,omitempty"`
	CreatedAt string `json:"created_at"`
}

type Reading struct {
	ID         int64  `json:"id"`
	DeviceID   string `json:"device_id"`
	SensorType string `json:"sensor_type"`
	Data       string `json:"data"`
	Timestamp  string `json:"timestamp"`
}

type Alert struct {
	ID         int64  `json:"id"`
	DeviceID   string `json:"device_id"`
	SensorType string `json:"sensor_type"`
	Level      string `json:"level"` // warning | danger
	Message    string `json:"message"`
	Data       string `json:"data"`
	Timestamp  string `json:"timestamp"`
}

// Ambang default (Fase 4: bisa dikalibrasi dari dashboard, disimpan di tabel thresholds).
const (
	TempWarn    = 30.0  // °C DHT22
	TempDanger  = 35.0  // °C DHT22
	SmokeWarn   = 100.0 // ppm SMOKE
	SmokeDanger = 200.0 // ppm SMOKE
)

// Thresholds: batas warning & danger per sensor.
// Range: normal = di bawah warning, warning = [warning, danger), danger = >= danger.
type Thresholds struct {
	TempWarn    float64 `json:"temp_warn"`
	TempDanger  float64 `json:"temp_danger"`
	SmokeWarn   float64 `json:"smoke_warn"`
	SmokeDanger float64 `json:"smoke_danger"`
}

var DefaultThresholds = Thresholds{TempWarn, TempDanger, SmokeWarn, SmokeDanger}

func (s *Store) Thresholds() Thresholds {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.th
}

// SetThresholds menyimpan kalibrasi baru; harus 0 <= warning < danger untuk tiap sensor.
func (s *Store) SetThresholds(t Thresholds) error {
	if t.TempWarn < 0 || t.TempWarn >= t.TempDanger || t.SmokeWarn < 0 || t.SmokeWarn >= t.SmokeDanger {
		return errors.New("harus 0 <= warning < danger untuk tiap sensor")
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, r := range []struct {
		sensor string
		warn   float64
		danger float64
	}{{"DHT22", t.TempWarn, t.TempDanger}, {"SMOKE", t.SmokeWarn, t.SmokeDanger}} {
		if _, err := tx.Exec(`INSERT INTO thresholds(sensor_type,warn,danger) VALUES(?,?,?)
			ON CONFLICT(sensor_type) DO UPDATE SET warn=excluded.warn, danger=excluded.danger`,
			r.sensor, r.warn, r.danger); err != nil {
			return err
		}
	}
	if err := tx.Commit(); err != nil {
		return err
	}
	s.mu.Lock()
	s.th = t
	s.mu.Unlock()
	return nil
}

func (s *Store) loadThresholds() error {
	th := DefaultThresholds
	rows, err := s.db.Query(`SELECT sensor_type,warn,danger FROM thresholds`)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var sensor string
		var warn, danger float64
		if err := rows.Scan(&sensor, &warn, &danger); err != nil {
			return err
		}
		switch strings.ToUpper(sensor) {
		case "DHT22":
			th.TempWarn, th.TempDanger = warn, danger
		case "SMOKE":
			th.SmokeWarn, th.SmokeDanger = warn, danger
		}
	}
	s.th = th
	return rows.Err()
}

// Evaluate memakai ambang default (kompatibel lama).
func Evaluate(sensorType, data string) (level, msg string) {
	return EvaluateWith(sensorType, data, DefaultThresholds)
}

// EvaluateWith mengembalikan level "ok"|"warning"|"danger" untuk payload sensor.
func EvaluateWith(sensorType, data string, th Thresholds) (level, msg string) {
	var v map[string]float64
	if json.Unmarshal([]byte(data), &v) != nil {
		return "ok", ""
	}
	switch strings.ToUpper(sensorType) {
	case "DHT22":
		if t, ok := v["temperature"]; ok {
			switch {
			case t >= th.TempDanger:
				return "danger", fmt.Sprintf("suhu %.1f°C >= %.0f°C", t, th.TempDanger)
			case t >= th.TempWarn:
				return "warning", fmt.Sprintf("suhu %.1f°C >= %.0f°C", t, th.TempWarn)
			}
		}
	case "SMOKE":
		if p, ok := v["ppm"]; ok {
			switch {
			case p >= th.SmokeDanger:
				return "danger", fmt.Sprintf("asap %.0f ppm >= %.0f ppm", p, th.SmokeDanger)
			case p >= th.SmokeWarn:
				return "warning", fmt.Sprintf("asap %.0f ppm >= %.0f ppm", p, th.SmokeWarn)
			}
		}
	}
	return "ok", ""
}

func Open(path string) (*Store, error) {
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}
	// shortcut: satu koneksi, tulis serial — cukup untuk ingest ringan, upgrade ke pool kalau multi-writer berat.
	db.SetMaxOpenConns(1)
	_, err = db.Exec(`CREATE TABLE IF NOT EXISTS devices(
		device_id TEXT PRIMARY KEY, name TEXT NOT NULL,
		api_key_hash TEXT NOT NULL, last_seen TEXT, created_at TEXT NOT NULL);
	CREATE TABLE IF NOT EXISTS sensor_data(
		id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL,
		sensor_type TEXT NOT NULL, data TEXT NOT NULL, timestamp TEXT NOT NULL);
	CREATE INDEX IF NOT EXISTS idx_sd_device_ts ON sensor_data(device_id, timestamp);
	CREATE TABLE IF NOT EXISTS alerts(
		id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL,
		sensor_type TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL,
		data TEXT NOT NULL, timestamp TEXT NOT NULL);
	CREATE TABLE IF NOT EXISTS thresholds(
		sensor_type TEXT PRIMARY KEY, warn REAL NOT NULL, danger REAL NOT NULL);`)
	if err != nil {
		return nil, err
	}
	s := &Store{db: db}
	if err := s.loadThresholds(); err != nil {
		return nil, err
	}
	return s, nil
}

func HashKey(k string) string {
	h := sha256.Sum256([]byte(k))
	return hex.EncodeToString(h[:])
}

func NewKey() string {
	b := make([]byte, 32)
	rand.Read(b)
	return hex.EncodeToString(b)
}

func (s *Store) CreateDevice(id, name string) (string, error) {
	key := NewKey()
	_, err := s.db.Exec(`INSERT INTO devices(device_id,name,api_key_hash,created_at) VALUES(?,?,?,?)`,
		id, name, HashKey(key), time.Now().UTC().Format(time.RFC3339))
	if err != nil {
		return "", fmt.Errorf("device_id sudah ada atau tidak valid: %w", err)
	}
	return key, nil
}

// RotateKey membuat api_key baru (Fase 3: key lama hilang). Key lama langsung mati.
func (s *Store) RotateKey(id string) (string, error) {
	key := NewKey()
	res, err := s.db.Exec(`UPDATE devices SET api_key_hash=? WHERE device_id=?`, HashKey(key), id)
	if err != nil {
		return "", err
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return "", ErrNotFound
	}
	return key, nil
}

func (s *Store) ListDevices() ([]Device, error) {
	rows, err := s.db.Query(`SELECT device_id,name,COALESCE(last_seen,''),created_at FROM devices ORDER BY device_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Device
	for rows.Next() {
		var d Device
		if err := rows.Scan(&d.DeviceID, &d.Name, &d.LastSeen, &d.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

func (s *Store) InsertReading(deviceID, key, sensorType, data string) error {
	var hash string
	err := s.db.QueryRow(`SELECT api_key_hash FROM devices WHERE device_id=?`, deviceID).Scan(&hash)
	if err == sql.ErrNoRows {
		return ErrNotFound
	}
	if err != nil {
		return err
	}
	if subtle.ConstantTimeCompare([]byte(hash), []byte(HashKey(key))) != 1 {
		return ErrBadKey
	}
	now := time.Now().UTC().Format(time.RFC3339)
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err := tx.Exec(`INSERT INTO sensor_data(device_id,sensor_type,data,timestamp) VALUES(?,?,?,?)`,
		deviceID, sensorType, data, now); err != nil {
		return err
	}
	if level, msg := EvaluateWith(sensorType, data, s.Thresholds()); level != "ok" {
		if _, err := tx.Exec(`INSERT INTO alerts(device_id,sensor_type,level,message,data,timestamp) VALUES(?,?,?,?,?,?)`,
			deviceID, sensorType, level, msg, data, now); err != nil {
			return err
		}
	}
	if _, err := tx.Exec(`UPDATE devices SET last_seen=? WHERE device_id=?`, now, deviceID); err != nil {
		return err
	}
	return tx.Commit()
}

func (s *Store) History(deviceID string, limit int) ([]Reading, error) {
	rows, err := s.db.Query(`SELECT id,device_id,sensor_type,data,timestamp FROM sensor_data
		WHERE device_id=? ORDER BY timestamp DESC LIMIT ?`, deviceID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Reading
	for rows.Next() {
		var r Reading
		if err := rows.Scan(&r.ID, &r.DeviceID, &r.SensorType, &r.Data, &r.Timestamp); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func (s *Store) ListAlerts(limit int) ([]Alert, error) {
	rows, err := s.db.Query(`SELECT id,device_id,sensor_type,level,message,data,timestamp FROM alerts
		ORDER BY timestamp DESC, id DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Alert
	for rows.Next() {
		var a Alert
		if err := rows.Scan(&a.ID, &a.DeviceID, &a.SensorType, &a.Level, &a.Message, &a.Data, &a.Timestamp); err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}
