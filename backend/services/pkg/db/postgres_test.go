package db

import (
	"context"
	"testing"
	"time"
)

// NewPool's happy path needs a live Postgres, so it stays integration-only.
// These tests lock the fail-fast validation that must reject bad config
// *before* any network dial — a half-built deploy should error at boot.

func TestNewPool_EmptyURL(t *testing.T) {
	_, err := NewPool(context.Background(), Config{URL: "", MaxConns: 5})
	if err == nil {
		t.Fatal("expected error for empty URL")
	}
}

func TestNewPool_NonPositiveMaxConns(t *testing.T) {
	_, err := NewPool(context.Background(), Config{URL: "postgres://u:p@h:5432/d", MaxConns: 0})
	if err == nil {
		t.Fatal("expected error for MaxConns <= 0")
	}
}

func TestNewPool_UnparseableURL(t *testing.T) {
	_, err := NewPool(context.Background(), Config{URL: "::not a dsn::", MaxConns: 5})
	if err == nil {
		t.Fatal("expected parse error for malformed URL")
	}
}

func TestOrDefault(t *testing.T) {
	if got := orDefault(int32(0), int32(2)); got != 2 {
		t.Errorf("orDefault(0,2) = %d, want 2 (zero falls back)", got)
	}
	if got := orDefault(int32(7), int32(2)); got != 7 {
		t.Errorf("orDefault(7,2) = %d, want 7 (non-zero kept)", got)
	}
	if got := orDefault(time.Duration(0), time.Hour); got != time.Hour {
		t.Errorf("orDefault(0,1h) = %v, want 1h", got)
	}
	if got := orDefault(30*time.Minute, time.Hour); got != 30*time.Minute {
		t.Errorf("orDefault(30m,1h) = %v, want 30m", got)
	}
}
