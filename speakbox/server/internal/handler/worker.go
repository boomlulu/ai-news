package handler

import (
	"crypto/subtle"
	"encoding/json"
	"io"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
)

const maxWavBytes = 64 << 20 // 64 MiB hard cap on uploaded wav payload

// workerAuth wraps a worker handler with X-Worker-Token verification. An empty
// configured token disables all worker endpoints (always 401). Comparison is
// constant-time.
func (h *Handler) workerAuth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		got := r.Header.Get("X-Worker-Token")
		want := h.cfg.WorkerToken
		if want == "" || subtle.ConstantTimeCompare([]byte(got), []byte(want)) != 1 {
			writeErr(w, http.StatusUnauthorized, "unauthorized")
			return
		}
		next(w, r)
	}
}

// workerNext dequeues the head pending task for a worker.
func (h *Handler) workerNext(w http.ResponseWriter, _ *http.Request) {
	claim, ok := h.store.Next()
	if !ok {
		w.WriteHeader(http.StatusNoContent)
		return
	}
	writeJSON(w, http.StatusOK, claim)
}

type progressReq struct {
	Status   string `json:"status"`
	Progress int    `json:"progress"`
	Error    string `json:"error"`
}

// workerProgress applies a worker progress/status report.
func (h *Handler) workerProgress(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil {
		writeErr(w, http.StatusNotFound, "task not found")
		return
	}
	var req progressReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid json")
		return
	}
	if !h.store.UpdateProgress(id, req.Status, req.Progress, req.Error) {
		writeErr(w, http.StatusNotFound, "task not found")
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

// workerWav receives the produced WAV bytes (raw audio/wav body OR multipart
// field "file"), writes <DataDir>/wav/<id>.wav, and marks the task done.
func (h *Handler) workerWav(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil {
		writeErr(w, http.StatusNotFound, "task not found")
		return
	}
	if _, ok := h.store.Get(id); !ok {
		writeErr(w, http.StatusNotFound, "task not found")
		return
	}

	src, cleanup, err := wavReader(r)
	if err != nil {
		writeErr(w, http.StatusBadRequest, err.Error())
		return
	}
	defer cleanup()

	wavDir := filepath.Join(h.cfg.DataDir, "wav")
	if err := os.MkdirAll(wavDir, 0o755); err != nil {
		writeErr(w, http.StatusInternalServerError, "mkdir failed")
		return
	}
	wavPath := filepath.Join(wavDir, strconv.Itoa(id)+".wav")
	dst, err := os.Create(wavPath)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "create failed")
		return
	}
	if _, err := io.Copy(dst, io.LimitReader(src, maxWavBytes)); err != nil {
		_ = dst.Close()
		writeErr(w, http.StatusInternalServerError, "write failed")
		return
	}
	if err := dst.Close(); err != nil {
		writeErr(w, http.StatusInternalServerError, "write failed")
		return
	}

	if !h.store.MarkDone(id, wavPath) {
		writeErr(w, http.StatusNotFound, "task not found")
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

// wavReader returns a reader over the uploaded WAV bytes, handling both raw
// audio/wav bodies and multipart "file" fields. cleanup must always be called.
func wavReader(r *http.Request) (io.Reader, func(), error) {
	ct := r.Header.Get("Content-Type")
	mediaType, _, _ := mime.ParseMediaType(ct)
	if mediaType == "multipart/form-data" {
		f, _, err := r.FormFile("file")
		if err != nil {
			return nil, func() {}, err
		}
		return f, func() { _ = f.Close() }, nil
	}
	// Raw body (audio/wav or unspecified).
	return r.Body, func() {}, nil
}
