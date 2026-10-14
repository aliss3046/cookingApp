// Command server — HTTP API /v1. Пока только проверка живости; маршруты
// появятся вместе с логикой (см. docs/openapi.yaml).
package main

import (
	"log"
	"net/http"
	"os"
)

func main() {
	addr := os.Getenv("API_ADDR")
	if addr == "" {
		addr = ":8080"
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/v1/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})

	log.Printf("api listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}
