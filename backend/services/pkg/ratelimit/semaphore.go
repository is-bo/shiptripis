// Package ratelimit provides in-process rate-limiting primitives used to
// blunt thundering-herd reconnects from Algerian mobile networks
// (ARCHITECTURE.md §10).
//
// Two primitives:
//   - Semaphore: pod-wide concurrency cap (e.g. ≤25 concurrent Postgres
//     catch-up queries). Bounds work, not request rate.
//   - TokenBucket: keyed request-rate limit (per-IP, per-user, per-route).
//     Lossy by design — over-budget requests are rejected, not queued.
//
// Both are in-process per pod. With the V1 pod count this is accurate
// enough; cluster-wide accuracy would require Redis and isn't worth the
// hot-path round-trip yet.
//
// Known V1 trade-offs (revisit only when measurements demand):
//   - TokenBucket uses a single mutex over the whole key map. If pprof
//     ever shows lock contention here, shard the map (fnv32(key) % N).
//   - SweepIdle holds that lock for the full pass; with O(10k) keys
//     that's milliseconds. Chunk-and-yield if SLOs ever demand.
//   - Retry-After is computed from rate alone, not bucket depth.
//   - MiddlewareByIP trusts X-Forwarded-For by default. Caddy is the
//     only public ingress (ARCHITECTURE.md §3); pass WithTrustXFF(false)
//     for any handler reachable without going through it.
package ratelimit

import "context"

// Semaphore caps concurrent holders to a fixed capacity.
//
// Backed by a buffered channel so Acquire integrates cleanly with
// context cancellation — important for HTTP handlers where a client
// disconnect should release the goroutine immediately rather than
// wait for a free slot it no longer needs.
type Semaphore struct {
	slots chan struct{}
}

// NewSemaphore returns a Semaphore with the given capacity. Capacity must
// be > 0; zero or negative would silently disable the limit, which is
// almost never what the caller wants.
func NewSemaphore(capacity int) *Semaphore {
	if capacity <= 0 {
		panic("ratelimit: semaphore capacity must be > 0")
	}
	return &Semaphore{slots: make(chan struct{}, capacity)}
}

// Acquire blocks until a slot is free or ctx is done. Returns ctx.Err()
// on cancel/deadline so callers can propagate it directly.
func (s *Semaphore) Acquire(ctx context.Context) error {
	select {
	case s.slots <- struct{}{}:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// TryAcquire grabs a slot without blocking. Returns false if full.
func (s *Semaphore) TryAcquire() bool {
	select {
	case s.slots <- struct{}{}:
		return true
	default:
		return false
	}
}

// Release frees one slot. Panics if the channel is empty at the moment
// of the call — a best-effort guard against double-Release / unmatched
// Release. Detection isn't airtight under benign races (a concurrent
// Acquire can hide the bug), but it's enough to catch most leaks in
// the caller's defer wiring.
func (s *Semaphore) Release() {
	select {
	case <-s.slots:
	default:
		panic("ratelimit: Release called without matching Acquire")
	}
}
