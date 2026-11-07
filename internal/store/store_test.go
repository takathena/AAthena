package store

import (
	"path/filepath"
	"testing"
)

// Self-check: kunci yang sama harus selalu memverifikasi, kunci lain tidak.
func TestHashKeyStable(t *testing.T) {
	if HashKey("abc") != HashKey("abc") {
		t.Fatal("hash tidak stabil")
	}
	if HashKey("abc") == HashKey("abd") {
		t.Fatal("hash tabrakan untuk input beda")
	}
	if len(HashKey("abc")) != 64 {
		t.Fatal("hash sha256 harus 64 hex char")
	}
}

// Fase 2: ambang suhu/asap + alert tersimpan saat ingest.
func TestAlertFase2(t *testing.T) {
	if lvl, _ := Evaluate("DHT22", `{"temperature":36}`); lvl != "danger" {
		t.Fatalf("36°C harus danger, got %s", lvl)
	}
	if lvl, _ := Evaluate("SMOKE", `{"ppm":120}`); lvl != "warning" {
		t.Fatalf("120 ppm harus warning, got %s", lvl)
	}
	if lvl, _ := Evaluate("DHT22", `{"temperature":25}`); lvl != "ok" {
		t.Fatalf("25°C harus ok, got %s", lvl)
	}
	s, err := Open(filepath.Join(t.TempDir(), "iot.db"))
	if err != nil {
		t.Fatal(err)
	}
	key, err := s.CreateDevice("ESP32-001", "Ruang Server")
	if err != nil {
		t.Fatal(err)
	}
	if err := s.InsertReading("ESP32-001", key, "DHT22", `{"temperature":36}`); err != nil {
		t.Fatal(err)
	}
	if err := s.InsertReading("ESP32-001", "salah", "DHT22", `{"temperature":36}`); err == nil {
		t.Fatal("key salah harus ditolak")
	}
	rows, err := s.ListAlerts(10)
	if err != nil || len(rows) != 1 || rows[0].Level != "danger" {
		t.Fatalf("harus 1 alert danger, got %+v err=%v", rows, err)
	}
}
