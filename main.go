// iot-go: API ingest sensor mini. Rebuild ramping dari Nexus IoT.
// Pakai: PORT=8080 DB_PATH=iot.db ADMIN_TOKEN=rahasia go run .  (token kosong = dev terbuka)
package main

import (
	"log"
	"net/http"
	"os"

	"iot-go/internal/api"
	"iot-go/internal/store"
)

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func main() {
	s, err := store.Open(env("DB_PATH", "iot.db"))
	if err != nil {
		log.Fatal(err)
	}
	a := &api.API{S: s, AdminTok: os.Getenv("ADMIN_TOKEN")}
	log.Printf("iot-go di :%s", env("PORT", "8080"))
	log.Fatal(http.ListenAndServe(":"+env("PORT", "8080"), a.Routes()))
}
