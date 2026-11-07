// Package store: semua akses SQLite. Tidak ada logika HTTP di sini.
package store

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"time"

	_ "modernc.org/sqlite"
)

var ErrNotFound = errors.New("not found")
var ErrBadKey = errors.New("invalid api_key")

type Store struct{ db *sql.DB }

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
	CREATE INDEX IF NOT EXISTS idx_sd_device_ts ON sensor_data(device_id, timestamp);`)
	if err != nil {
		return nil, err
	}
	return &Store{db}, nil
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
