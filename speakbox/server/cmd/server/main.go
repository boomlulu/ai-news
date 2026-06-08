package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"speakbox/internal/config"
	"speakbox/internal/handler"
	"speakbox/internal/sse"
	"speakbox/internal/task"
)

func main() {
	cfg := config.Load()

	// Ensure the wav output dir exists up front so the worker upload path can
	// assume it (it also mkdir's defensively per-write).
	wavDir := filepath.Join(cfg.DataDir, "wav")
	if err := os.MkdirAll(wavDir, 0o755); err != nil {
		log.Fatalf("failed to create data dir %s: %v", wavDir, err)
	}

	broker := sse.NewBroker()
	store := task.NewStore(broker)
	mux := handler.NewMux(store, cfg, broker)

	srv := &http.Server{
		Addr:    cfg.Address,
		Handler: mux,
		// WriteTimeout 0: SSE /api/events streams are long-lived. We rely on
		// IdleTimeout and per-handler request-context cancellation instead.
		WriteTimeout:      0,
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	log.Printf("speakbox | addr=%s | datadir=%s", cfg.Address, cfg.DataDir)

	// ── Graceful shutdown ────────────────────────────────────────────────────
	shutdownErr := make(chan error, 1)
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			shutdownErr <- err
		}
	}()

	select {
	case err := <-shutdownErr:
		log.Fatalf("server error: %v", err)
	case sig := <-stop:
		log.Printf("shutdown: received %s, draining...", sig)
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		if err := srv.Shutdown(ctx); err != nil {
			log.Printf("shutdown: http server: %v", err)
		}
		log.Printf("shutdown: complete")
	}
}
