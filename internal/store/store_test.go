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

// Fase 3: rotate key — key lama mati, key baru bisa ingest.
func TestRotateKey(t *testing.T) {
	s, err := Open(filepath.Join(t.TempDir(), "iot.db"))
	if err != nil {
		t.Fatal(err)
	}
	old, err := s.CreateDevice("ESP32-002", "Gudang")
	if err != nil {
		t.Fatal(err)
	}
	fresh, err := s.RotateKey("ESP32-002")
	if err != nil || fresh == old || fresh == "" {
		t.Fatalf("rotate harus hasilkan key baru, got %q err=%v", fresh, err)
	}
	if err := s.InsertReading("ESP32-002", old, "DHT22", `{"temperature":25}`); err == nil {
		t.Fatal("key lama harus sudah mati setelah rotate")
	}
	if err := s.InsertReading("ESP32-002", fresh, "DHT22", `{"temperature":25}`); err != nil {
		t.Fatalf("key baru harus bisa ingest: %v", err)
	}
	if _, err := s.RotateKey("tidak-ada"); err == nil {
		t.Fatal("rotate device tak ada harus error")
	}
}

// Fase 4: kalibrasi ambang dari dashboard dipakai saat ingest + tersimpan.
func TestCalibrateThresholds(t *testing.T) {
	path := filepath.Join(t.TempDir(), "iot.db")
	s, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.SetThresholds(Thresholds{TempWarn: 25, TempDanger: 28, SmokeWarn: 50, SmokeDanger: 80}); err != nil {
		t.Fatal(err)
	}
	if err := s.SetThresholds(Thresholds{TempWarn: 30, TempDanger: 30, SmokeWarn: 50, SmokeDanger: 80}); err == nil {
		t.Fatal("warning >= danger harus ditolak")
	}
	key, _ := s.CreateDevice("ESP32-004", "Kalibrasi")
	if err := s.InsertReading("ESP32-004", key, "DHT22", `{"temperature":26}`); err != nil {
		t.Fatal(err)
	}
	rows, _ := s.ListAlerts(5)
	if len(rows) != 1 || rows[0].Level != "warning" {
		t.Fatalf("26°C dgn ambang 25/28 harus warning, got %+v", rows)
	}
	// Buka ulang: kalibrasi tetap dipakai.
	s2, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	if th := s2.Thresholds(); th.TempWarn != 25 || th.TempDanger != 28 {
		t.Fatalf("kalibrasi harus persisten, got %+v", th)
	}
}
