// Package task holds the Task type plus an in-memory store/queue. Every
// create/update broadcasts the affected task (as JSON) on an *sse.Broker so
// SSE clients observe every state transition. No DB — map + FIFO slice +
// mutex, with an atomic auto-increment id.
package task

import (
	"encoding/json"
	"sort"
	"sync"
	"sync/atomic"
	"time"

	"speakbox/internal/sse"
)

// Status values for a task's lifecycle.
const (
	StatusPending    = "pending"
	StatusGenerating = "generating"
	StatusUploading  = "uploading"
	StatusDone       = "done"
	StatusFailed     = "failed"
)

// Task is the unit of work. JSON keys are part of the wire contract shared by
// the browser client and the external worker — do NOT rename.
type Task struct {
	ID        int    `json:"id"`
	Text      string `json:"text"`
	Voice     string `json:"voice"`
	Instruct  string `json:"instruct"`
	Status    string `json:"status"`
	Progress  int    `json:"progress"`
	Error     string `json:"error"`
	CreatedAt string `json:"created_at"` // RFC3339 UTC
	WavPath   string `json:"wav_path"`
}

// Store is an in-memory task store with a FIFO pending queue. Safe for
// concurrent use. Every mutation publishes the affected task to the broker.
type Store struct {
	mu      sync.Mutex
	tasks   map[int]*Task
	pending []int // FIFO of pending ids awaiting a worker
	nextID  atomic.Int64
	broker  *sse.Broker
}

// NewStore returns a ready store wired to broker.
func NewStore(broker *sse.Broker) *Store {
	return &Store{
		tasks:  make(map[int]*Task),
		broker: broker,
	}
}

// marshalLocked serializes t to JSON. It MUST be called while holding s.mu so
// the read of *t is race-free; the returned bytes are then safe to publish
// after unlocking. Returns nil on marshal error (caller must skip publishing).
func marshalLocked(t *Task) []byte {
	b, err := json.Marshal(t)
	if err != nil {
		return nil
	}
	return b
}

// publishBytes broadcasts already-marshalled bytes. Call AFTER unlocking. nil
// (a marshal failure) is skipped so the broker never emits a bad data frame.
func (s *Store) publishBytes(b []byte) {
	if b != nil {
		s.broker.Publish(b)
	}
}

// Create makes a new pending task, enqueues it, broadcasts it, and returns the
// new id.
func (s *Store) Create(text, voice, instruct string) int {
	id := int(s.nextID.Add(1))
	t := &Task{
		ID:        id,
		Text:      text,
		Voice:     voice,
		Instruct:  instruct,
		Status:    StatusPending,
		Progress:  0,
		Error:     "",
		CreatedAt: time.Now().UTC().Format(time.RFC3339),
		WavPath:   "",
	}

	s.mu.Lock()
	s.tasks[id] = t
	s.pending = append(s.pending, id)
	b := marshalLocked(t)
	s.mu.Unlock()

	s.publishBytes(b)
	return id
}

// List returns a snapshot of all tasks ordered by created_at DESC (ties broken
// by id DESC so newest-first is stable).
func (s *Store) List() []*Task {
	s.mu.Lock()
	out := make([]*Task, 0, len(s.tasks))
	for _, t := range s.tasks {
		cp := *t
		out = append(out, &cp)
	}
	s.mu.Unlock()

	sort.Slice(out, func(i, j int) bool {
		if out[i].CreatedAt != out[j].CreatedAt {
			return out[i].CreatedAt > out[j].CreatedAt
		}
		return out[i].ID > out[j].ID
	})
	return out
}

// Get returns a copy of the task with id, or (nil, false).
func (s *Store) Get(id int) (*Task, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	t, ok := s.tasks[id]
	if !ok {
		return nil, false
	}
	cp := *t
	return &cp, true
}

// Claimed is the payload returned to a worker that dequeues a task.
type Claimed struct {
	ID       int    `json:"id"`
	Text     string `json:"text"`
	Voice    string `json:"voice"`
	Instruct string `json:"instruct"`
}

// Next atomically dequeues the head pending task, flips it to generating with
// progress 0, broadcasts the change, and returns it. Returns (nil, false) when
// the queue is empty.
func (s *Store) Next() (*Claimed, bool) {
	s.mu.Lock()
	for len(s.pending) > 0 {
		id := s.pending[0]
		s.pending = s.pending[1:]
		t, ok := s.tasks[id]
		if !ok {
			continue // task vanished (shouldn't happen); skip
		}
		t.Status = StatusGenerating
		t.Progress = 0
		claim := &Claimed{ID: t.ID, Text: t.Text, Voice: t.Voice, Instruct: t.Instruct}
		b := marshalLocked(t)
		s.mu.Unlock()
		s.publishBytes(b)
		return claim, true
	}
	s.mu.Unlock()
	return nil, false
}

// UpdateProgress applies a worker progress report. status is required; when it
// is StatusGenerating the supplied progress is applied; failed carries an
// error string. Returns false if the id is unknown.
func (s *Store) UpdateProgress(id int, status string, progress int, errMsg string) bool {
	s.mu.Lock()
	t, ok := s.tasks[id]
	if !ok {
		s.mu.Unlock()
		return false
	}
	t.Status = status
	switch status {
	case StatusGenerating:
		t.Progress = progress
	case StatusFailed:
		t.Error = errMsg
	}
	b := marshalLocked(t)
	s.mu.Unlock()

	s.publishBytes(b)
	return true
}

// MarkDone records the produced wav path, flips the task to done/progress 100,
// clears any error, and broadcasts. Returns false if the id is unknown.
func (s *Store) MarkDone(id int, wavPath string) bool {
	s.mu.Lock()
	t, ok := s.tasks[id]
	if !ok {
		s.mu.Unlock()
		return false
	}
	t.WavPath = wavPath
	t.Status = StatusDone
	t.Progress = 100
	t.Error = ""
	b := marshalLocked(t)
	s.mu.Unlock()

	s.publishBytes(b)
	return true
}
