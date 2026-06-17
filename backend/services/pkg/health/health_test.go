package health

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
)

// silentHandler discards log output so a degraded-readiness test doesn't spam
// the test runner. The health Handler logs warns on state transitions.
func silentHandler() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func decodeBody(t *testing.T, rr *httptest.ResponseRecorder) response {
	t.Helper()
	var got response
	if err := json.Unmarshal(rr.Body.Bytes(), &got); err != nil {
		t.Fatalf("decode body %q: %v", rr.Body.String(), err)
	}
	return got
}

func TestLiveness_AlwaysOK(t *testing.T) {
	h := New(Config{Logger: silentHandler()})
	rr := httptest.NewRecorder()
	h.Liveness().ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/healthz", nil))

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rr.Code)
	}
	if got := rr.Header().Get("Cache-Control"); got != "no-store" {
		t.Errorf("Cache-Control = %q, want no-store", got)
	}
	if rr.Header().Get("Content-Type") != "application/json" {
		t.Errorf("Content-Type = %q", rr.Header().Get("Content-Type"))
	}
}

func TestReadiness_BlockedBeforeMarkReady(t *testing.T) {
	h := New(Config{Logger: silentHandler()})
	// A passing check is registered, but readiness must still be 503 until
	// MarkReady — this is the guard against the LB sending traffic mid-boot.
	h.Register("redis", func(context.Context) error { return nil })

	rr := httptest.NewRecorder()
	h.Readiness().ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/readyz", nil))

	if rr.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503 before MarkReady", rr.Code)
	}
	if got := decodeBody(t, rr); got.Status != "not_ready" {
		t.Errorf("status field = %q, want not_ready", got.Status)
	}
}

func TestReadiness_ReadyWithPassingChecks(t *testing.T) {
	h := New(Config{Logger: silentHandler()})
	h.Register("postgres", func(context.Context) error { return nil })
	h.Register("redis", func(context.Context) error { return nil })
	h.MarkReady()

	rr := httptest.NewRecorder()
	h.Readiness().ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/readyz", nil))

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rr.Code)
	}
	got := decodeBody(t, rr)
	if got.Status != "ready" {
		t.Errorf("status = %q, want ready", got.Status)
	}
	// Passing checks report "" in the map.
	if got.Checks["postgres"] != "" || got.Checks["redis"] != "" {
		t.Errorf("checks = %v, want both empty", got.Checks)
	}
}

func TestReadiness_DegradedWhenCheckFails(t *testing.T) {
	h := New(Config{Logger: silentHandler()})
	h.Register("postgres", func(context.Context) error { return nil })
	h.Register("redis", func(context.Context) error { return errors.New("connection refused") })
	h.MarkReady()

	rr := httptest.NewRecorder()
	h.Readiness().ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/readyz", nil))

	if rr.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503 when a check fails", rr.Code)
	}
	got := decodeBody(t, rr)
	if got.Status != "degraded" {
		t.Errorf("status = %q, want degraded", got.Status)
	}
	if got.Checks["redis"] != "connection refused" {
		t.Errorf("redis check = %q, want the error message", got.Checks["redis"])
	}
	if got.Checks["postgres"] != "" {
		t.Errorf("postgres check = %q, want empty (passing)", got.Checks["postgres"])
	}
}

func TestReadiness_PanicInCheckIsContained(t *testing.T) {
	h := New(Config{Logger: silentHandler()})
	h.Register("boom", func(context.Context) error { panic("kaboom") })
	h.MarkReady()

	rr := httptest.NewRecorder()
	// Must not propagate the panic out of the handler.
	h.Readiness().ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/readyz", nil))

	if rr.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503 for a panicking check", rr.Code)
	}
	got := decodeBody(t, rr)
	if got.Checks["boom"] == "" {
		t.Error("panicking check should surface a non-empty error string")
	}
}

func TestReadiness_ReadyWithNoChecks(t *testing.T) {
	h := New(Config{Logger: silentHandler()})
	h.MarkReady() // ready, but nothing registered → still 200 (and warns once).

	rr := httptest.NewRecorder()
	h.Readiness().ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/readyz", nil))

	if rr.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 with no checks", rr.Code)
	}
	if got := decodeBody(t, rr); got.Status != "ready" {
		t.Errorf("status = %q, want ready", got.Status)
	}
}

func TestRegister_IgnoresEmptyNameOrNilFunc(t *testing.T) {
	h := New(Config{Logger: silentHandler()})
	h.Register("", func(context.Context) error { return nil })
	h.Register("x", nil)
	h.MarkReady()

	rr := httptest.NewRecorder()
	h.Readiness().ServeHTTP(rr, httptest.NewRequest(http.MethodGet, "/readyz", nil))

	got := decodeBody(t, rr)
	if len(got.Checks) != 0 {
		t.Errorf("checks = %v, want none registered", got.Checks)
	}
}

func TestNew_DefaultsTimeout(t *testing.T) {
	h := New(Config{Logger: silentHandler()})
	if h.timeout != defaultCheckTimeout {
		t.Errorf("timeout = %v, want default %v", h.timeout, defaultCheckTimeout)
	}
	// Nil logger should fall back to slog.Default without panicking.
	h2 := New(Config{})
	if h2.log == nil {
		t.Error("logger should fall back to a non-nil default")
	}
}
