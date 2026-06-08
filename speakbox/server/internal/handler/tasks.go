package handler

import (
	"encoding/json"
	"net/http"
	"os"
	"strconv"
	"strings"
	"unicode/utf8"

	"speakbox/internal/task"
)

const maxRunes = 100

// validVoices is the static allowlist; mirror it in listVoices.
var validVoices = map[string]bool{
	"my_voice_zh": true,
}

type voiceOption struct {
	ID    string `json:"id"`
	Label string `json:"label"`
}

// listVoices returns the static voice catalog.
func (h *Handler) listVoices(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, []voiceOption{
		{ID: "my_voice_zh", Label: "我的克隆音色"},
	})
}

type createTaskReq struct {
	Text     string `json:"text"`
	Voice    string `json:"voice"`
	Instruct string `json:"instruct"`
}

// createTask validates the request and enqueues a pending task.
func (h *Handler) createTask(w http.ResponseWriter, r *http.Request) {
	var req createTaskReq
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid json")
		return
	}

	text := strings.TrimSpace(req.Text)
	if text == "" {
		writeErr(w, http.StatusBadRequest, "text is required")
		return
	}
	if utf8.RuneCountInString(text) > maxRunes {
		writeErr(w, http.StatusBadRequest, "text exceeds 100 characters")
		return
	}
	if !validVoices[req.Voice] {
		writeErr(w, http.StatusBadRequest, "invalid voice")
		return
	}
	instruct := strings.TrimSpace(req.Instruct)
	if utf8.RuneCountInString(instruct) > 200 {
		writeErr(w, http.StatusBadRequest, "instruct too long")
		return
	}

	id := h.store.Create(text, req.Voice, instruct)
	writeJSON(w, http.StatusCreated, map[string]int{"id": id})
}

// listTasks returns all tasks, created_at DESC.
func (h *Handler) listTasks(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, h.store.List())
}

// downloadWav streams a finished task's wav file as an attachment.
func (h *Handler) downloadWav(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil {
		http.NotFound(w, r)
		return
	}
	t, ok := h.store.Get(id)
	if !ok || t.Status != task.StatusDone || t.WavPath == "" {
		http.NotFound(w, r)
		return
	}
	f, err := os.Open(t.WavPath)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	defer f.Close()
	fi, err := f.Stat()
	if err != nil || fi.IsDir() {
		http.NotFound(w, r)
		return
	}

	w.Header().Set("Content-Type", "audio/wav")
	w.Header().Set("Content-Disposition", "attachment; filename=\"speak_"+strconv.Itoa(id)+".wav\"")
	http.ServeContent(w, r, "", fi.ModTime(), f)
}
