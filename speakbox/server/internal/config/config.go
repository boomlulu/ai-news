// Package config loads speakbox server configuration from environment
// variables. Zero external dependencies — stdlib only.
package config

import "os"

// Config holds all server configuration. Inject a different Config in tests.
type Config struct {
	Address     string // listen address, e.g. ":8200"
	DataDir     string // base data dir; wav files go to <DataDir>/wav/<id>.wav
	WorkerToken string // shared secret for /api/worker/* ; empty => all worker endpoints 401
}

// Load reads configuration from the environment, applying defaults.
func Load() *Config {
	return &Config{
		Address:     getEnv("ADDRESS", ":8200"),
		DataDir:     getEnv("DATA_DIR", "/data/speakbox"),
		WorkerToken: getEnv("WORKER_TOKEN", ""),
	}
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
