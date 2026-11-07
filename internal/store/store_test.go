package store

import "testing"

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
