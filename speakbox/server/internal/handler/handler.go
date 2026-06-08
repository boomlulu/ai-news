// Package handler wires the speakbox HTTP API onto a stdlib ServeMux using
// go1.22 method+wildcard patterns — no web framework.
package handler

import (
	"encoding/json"
	"net/http"

	"speakbox/internal/config"
	"speakbox/internal/sse"
	"speakbox/internal/task"
)

// Handler bundles the dependencies shared by every endpoint.
type Handler struct {
	store  *task.Store
	cfg    *config.Config
	broker *sse.Broker
}

// NewMux constructs the router with all routes registered.
func NewMux(store *task.Store, cfg *config.Config, broker *sse.Broker) *http.ServeMux {
	h := &Handler{store: store, cfg: cfg, broker: broker}
	mux := http.NewServeMux()

	// Public — static + health
	mux.HandleFunc("GET /", h.index)
	mux.HandleFunc("GET /style.css", h.staticFile)
	mux.HandleFunc("GET /js/app.js", h.staticFile)
	mux.HandleFunc("GET /health", h.health)

	// Public — API
	mux.HandleFunc("GET /api/voices", h.listVoices)
	mux.HandleFunc("POST /api/tasks", h.createTask)
	mux.HandleFunc("GET /api/tasks", h.listTasks)
	mux.HandleFunc("GET /api/tasks/{id}/wav", h.downloadWav)
	mux.HandleFunc("GET /api/events", h.events)

	// Worker — token-gated
	mux.HandleFunc("GET /api/worker/next", h.workerAuth(h.workerNext))
	mux.HandleFunc("POST /api/worker/tasks/{id}/progress", h.workerAuth(h.workerProgress))
	mux.HandleFunc("POST /api/worker/tasks/{id}/wav", h.workerAuth(h.workerWav))

	return mux
}

func (h *Handler) health(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("ok"))
}

// writeJSON marshals v and writes it with the given status code.
func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

// writeErr emits {"error": msg} with the given status code.
func writeErr(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}
