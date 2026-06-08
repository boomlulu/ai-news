package handler

import (
	"io/fs"
	"net/http"

	"speakbox/web"
)

// staticFS serves the embedded web assets (style.css, js/app.js) over http.FS.
var staticFS = http.FileServer(http.FS(web.Files))

// index serves the embedded index.html at GET /.
func (h *Handler) index(w http.ResponseWriter, _ *http.Request) {
	b, err := fs.ReadFile(web.Files, "index.html")
	if err != nil {
		http.Error(w, "index not found", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(b)
}

// staticFile serves a single embedded asset by request path. Routes are
// registered for exact paths (GET /style.css, GET /js/app.js), so the path
// maps 1:1 onto a file inside the embed.FS.
func (h *Handler) staticFile(w http.ResponseWriter, r *http.Request) {
	staticFS.ServeHTTP(w, r)
}
