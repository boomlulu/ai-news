package task

import (
	"sync"
	"testing"

	"speakbox/internal/sse"
)

// TestStoreConcurrent hammers the store from many goroutines while real SSE
// subscribers drain the broker. It exists primarily to trip the race detector
// (`go test -race`): the pre-fix publish read *t outside the lock, so a Create
// racing a concurrent MarkDone/UpdateProgress/Next on the same task was a data
// race. The invariant assertions are intentionally loose; the race detector is
// the real oracle.
func TestStoreConcurrent(t *testing.T) {
	broker := sse.NewBroker()

	// Two real subscribers, each draining until the broker channel closes, so a
	// slow/full channel never masks the publish path under test.
	var drains sync.WaitGroup
	unsubs := make([]func(), 0, 2)
	for i := 0; i < 2; i++ {
		ch, unsub := broker.Subscribe()
		unsubs = append(unsubs, unsub)
		drains.Add(1)
		go func() {
			defer drains.Done()
			for range ch {
				// discard; just keep the channel from filling
			}
		}()
	}

	s := NewStore(broker)

	const workers = 16
	const perWorker = 25

	var wg sync.WaitGroup
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for n := 0; n < perWorker; n++ {
				id := s.Create("hello world", "qikou", "")

				// Mutate the freshly-created task concurrently with other
				// workers' Creates/Next/reads on shared *Task pointers.
				s.UpdateProgress(id, StatusGenerating, 42, "")
				s.MarkDone(id, "/tmp/out.wav")

				// Readers + the dequeue path also touch shared tasks.
				_ = s.List()
				_, _ = s.Get(id)
				_, _ = s.Next()
			}
		}()
	}
	wg.Wait()

	// Loose invariants. Every Create inserts exactly one task and none are
	// removed, so the store must hold workers*perWorker tasks.
	want := workers * perWorker
	got := s.List()
	if len(got) != want {
		t.Fatalf("List len = %d, want %d", len(got), want)
	}

	// Each created id was MarkDone'd; spot-check a couple are terminal-ish.
	// (Next may have flipped some back to generating after MarkDone depending
	// on interleaving, so only assert the task exists and progress is sane.)
	for _, tk := range got[:min(5, len(got))] {
		cp, ok := s.Get(tk.ID)
		if !ok {
			t.Fatalf("Get(%d) missing after creation", tk.ID)
		}
		if cp.Progress < 0 || cp.Progress > 100 {
			t.Fatalf("task %d progress out of range: %d", cp.ID, cp.Progress)
		}
	}

	// Tear down subscribers and ensure drains exit cleanly (no goroutine leak,
	// no panic on closed channel).
	for _, u := range unsubs {
		u()
	}
	drains.Wait()
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
