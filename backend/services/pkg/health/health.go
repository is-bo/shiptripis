// Package health exposes Kubernetes-style /healthz (liveness) and /readyz
// (readiness) endpoints.
//
// Split rationale:
//   - Liveness answers "is the process alive?" — always 200 once boot completes.
//     Failure here triggers a pod restart.
//   - Readiness answers "can this pod serve traffic?" — runs registered
//     checkers (e.g. postgres ping, redis ping). Failure here removes the pod
//     from the load balancer but does NOT restart it. This is what protects
//     against transient dependency blips causing restart loops.
package health

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"maps"
	"net/http"
	"sync"
	"sync/atomic"
	"time"
)

// CheckFunc reports whether a dependency is healthy. Return nil for healthy.
// The provided context carries the per-request timeout — respect it.
type CheckFunc func(ctx context.Context) error

const defaultCheckTimeout = 2 * time.Second

type Handler struct {
	mu      sync.RWMutex
	checks  map[string]CheckFunc
	timeout time.Duration
	log     *slog.Logger
	ready   bool

	// lastDegraded toggles the warn log on state transitions only — keeps the
	// log clean under K8s probe rates (every 5–10s) when a dep is flapping.
	lastDegraded atomic.Bool

	// noChecksWarned ensures we warn at most once if /readyz is hit with no
	// checks registered.
	noChecksWarned atomic.Bool
}

type Config struct {
	// CheckTimeout caps each readiness check. Defaults to 2s.
	CheckTimeout time.Duration
	Logger       *slog.Logger
}

func New(cfg Config) *Handler {
	log := cfg.Logger
	if log == nil {
		log = slog.Default()
	}
	timeout := cfg.CheckTimeout
	if timeout <= 0 {
		timeout = defaultCheckTimeout
	}
	return &Handler{
		checks:  make(map[string]CheckFunc),
		timeout: timeout,
		log:     log,
	}
}

// Register adds a named readiness check. Re-registering with the same name
// overwrites. Calling after MarkReady is allowed but logs a warning — checks
// should normally be wired before traffic flips on.
func (h *Handler) Register(name string, fn CheckFunc) {
	if name == "" || fn == nil {
		return
	}
	h.mu.Lock()
	wasReady := h.ready
	h.checks[name] = fn
	h.mu.Unlock()

	if wasReady {
		h.log.Warn("health check registered after MarkReady",
			"check", name,
		)
	}
}

// MarkReady signals that boot is complete. Until called, /readyz returns 503
// even if all registered checks pass — prevents the load balancer from sending
// traffic before main.go finishes wiring everything.
func (h *Handler) MarkReady() {
	h.mu.Lock()
	h.ready = true
	h.mu.Unlock()
}

// Liveness returns an http.Handler that always responds 200 OK once the
// process is running. Mount on /healthz.
func (h *Handler) Liveness() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
}

// Readiness returns an http.Handler that runs all registered checks
// concurrently and reports the aggregate result. Mount on /readyz.
func (h *Handler) Readiness() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h.mu.RLock()
		ready := h.ready
		checks := make(map[string]CheckFunc, len(h.checks))
		maps.Copy(checks, h.checks)
		timeout := h.timeout
		h.mu.RUnlock()

		if !ready {
			writeJSON(w, http.StatusServiceUnavailable, response{
				Status: "not_ready",
				Error:  "service has not finished booting",
			})
			return
		}

		if len(checks) == 0 && h.noChecksWarned.CompareAndSwap(false, true) {
			h.log.Warn("readiness probe: no checks registered")
		}

		ctx, cancel := context.WithTimeout(r.Context(), timeout)
		defer cancel()

		results := runChecks(ctx, checks)
		degraded := false
		for _, err := range results {
			if err != "" {
				degraded = true
				break
			}
		}

		// Log only on state transitions to avoid probe-rate spam.
		if h.lastDegraded.Swap(degraded) != degraded {
			if degraded {
				h.log.Warn("readiness degraded", "checks", results)
			} else {
				h.log.Info("readiness recovered")
			}
		}

		status := http.StatusOK
		statusText := "ready"
		if degraded {
			status = http.StatusServiceUnavailable
			statusText = "degraded"
		}

		writeJSON(w, status, response{
			Status: statusText,
			Checks: results,
		})
	})
}

type response struct {
	Status string            `json:"status"`
	Checks map[string]string `json:"checks,omitempty"`
	Error  string            `json:"error,omitempty"`
}

// runChecks fans out checks concurrently. An empty string in the result means
// the check passed; a non-empty string is the error message.
func runChecks(ctx context.Context, checks map[string]CheckFunc) map[string]string {
	if len(checks) == 0 {
		return nil
	}

	results := make(map[string]string, len(checks))
	var mu sync.Mutex
	var wg sync.WaitGroup

	for name, fn := range checks {
		wg.Add(1)
		go func(name string, fn CheckFunc) {
			defer wg.Done()
			err := safeRun(ctx, fn)
			mu.Lock()
			if err != nil {
				results[name] = err.Error()
			} else {
				results[name] = ""
			}
			mu.Unlock()
		}(name, fn)
	}
	wg.Wait()
	return results
}

// safeRun shields the readiness handler from a panicking checker and
// preserves the panic value in the returned error for triage.
func safeRun(ctx context.Context, fn CheckFunc) (err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("check panicked: %v", r)
		}
	}()
	return fn(ctx)
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
