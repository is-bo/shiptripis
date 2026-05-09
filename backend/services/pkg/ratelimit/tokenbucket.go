package ratelimit

import (
	"math"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

// TokenBucketConfig configures a keyed token-bucket rate limiter.
//
// Rate is tokens added per second (steady-state allowance). Burst is the
// bucket capacity (max tokens that can accumulate when idle, i.e. the
// largest sudden spike a key can absorb).
//
// IdleTimeout bounds memory: keys with no traffic for IdleTimeout are
// removed by SweepIdle. Default 10 minutes.
type TokenBucketConfig struct {
	Rate        float64
	Burst       float64
	IdleTimeout time.Duration

	// Now is injected for deterministic tests. Defaults to time.Now.
	Now func() time.Time
}

// TokenBucket is an in-process keyed bucket. Buckets are created lazily
// on first Allow and refilled on read (no per-bucket goroutine), so
// memory cost is one entry per active key.
type TokenBucket struct {
	rate        float64
	burst       float64
	idleTimeout time.Duration
	now         func() time.Time

	mu      sync.Mutex
	buckets map[string]*bucket
}

type bucket struct {
	tokens     float64
	lastRefill time.Time
}

const defaultIdleTimeout = 10 * time.Minute

func NewTokenBucket(cfg TokenBucketConfig) *TokenBucket {
	if cfg.Rate <= 0 {
		panic("ratelimit: token bucket Rate must be > 0")
	}
	if cfg.Burst <= 0 {
		panic("ratelimit: token bucket Burst must be > 0")
	}
	idle := cfg.IdleTimeout
	if idle <= 0 {
		idle = defaultIdleTimeout
	}
	now := cfg.Now
	if now == nil {
		now = time.Now
	}
	return &TokenBucket{
		rate:        cfg.Rate,
		burst:       cfg.Burst,
		idleTimeout: idle,
		now:         now,
		buckets:     make(map[string]*bucket),
	}
}

// Allow consumes one token from key's bucket and returns true on success.
// On false, the request should be rejected (429 in HTTP).
func (t *TokenBucket) Allow(key string) bool {
	now := t.now()

	t.mu.Lock()
	defer t.mu.Unlock()

	b, ok := t.buckets[key]
	if !ok {
		// New key: start full so the first burst always passes.
		b = &bucket{tokens: t.burst, lastRefill: now}
		t.buckets[key] = b
	} else {
		elapsed := now.Sub(b.lastRefill).Seconds()
		if elapsed > 0 {
			b.tokens = min(t.burst, b.tokens+elapsed*t.rate)
		}
		b.lastRefill = now
	}

	if b.tokens >= 1 {
		b.tokens--
		return true
	}
	return false
}

// SweepIdle removes keys with no traffic for IdleTimeout. Call from a
// background goroutine (e.g. time.Ticker) in main.go — the bucket
// itself doesn't spawn one.
func (t *TokenBucket) SweepIdle() {
	cutoff := t.now().Add(-t.idleTimeout)
	t.mu.Lock()
	defer t.mu.Unlock()
	for k, b := range t.buckets {
		if b.lastRefill.Before(cutoff) {
			delete(t.buckets, k)
		}
	}
}

// Size returns the number of tracked keys. Useful for metrics and tests.
func (t *TokenBucket) Size() int {
	t.mu.Lock()
	defer t.mu.Unlock()
	return len(t.buckets)
}

// retryAfterSeconds rounds up the wait time for one token to a whole
// second — Retry-After is integer seconds in HTTP/1.1.
func (t *TokenBucket) retryAfterSeconds() int {
	return max(1, int(math.Ceil(1.0/t.rate)))
}

// MiddlewareOption customizes MiddlewareByIP behavior.
type MiddlewareOption func(*middlewareOptions)

type middlewareOptions struct {
	trustXFF bool
}

// WithTrustXFF controls whether the middleware honors X-Forwarded-For
// when resolving the client IP. Defaults to true (Caddy is the only V1
// public ingress and rewrites XFF). Set false on any handler reachable
// without going through Caddy — otherwise clients can spoof their IP
// and trivially defeat the limiter.
func WithTrustXFF(trust bool) MiddlewareOption {
	return func(o *middlewareOptions) { o.trustXFF = trust }
}

// MiddlewareByIP wraps an http.Handler with per-client-IP rate limiting.
//
// Client IP resolution: when XFF is trusted, the first entry of
// X-Forwarded-For wins; otherwise the connection's RemoteAddr is used.
// The resulting IP is normalized through net.ParseIP so that bracketed
// vs. bare and abbreviated vs. expanded IPv6 forms collide on a single
// bucket — otherwise format spoofing trivially doubles the budget.
func MiddlewareByIP(tb *TokenBucket, opts ...MiddlewareOption) func(http.Handler) http.Handler {
	options := middlewareOptions{trustXFF: true}
	for _, opt := range opts {
		opt(&options)
	}
	retryAfter := strconv.Itoa(tb.retryAfterSeconds())
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			ip := clientIP(r, options.trustXFF)
			if !tb.Allow(ip) {
				w.Header().Set("Retry-After", retryAfter)
				http.Error(w, "rate limit exceeded", http.StatusTooManyRequests)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// clientIP resolves the client IP from a request and returns its
// canonical string form. Falls back to the raw input if parsing fails
// — better to limit on a quirky string than to bypass the limiter.
func clientIP(r *http.Request, trustXFF bool) string {
	if trustXFF {
		if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
			first, _, _ := strings.Cut(xff, ",")
			return canonicalIP(strings.TrimSpace(first))
		}
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	return canonicalIP(host)
}

func canonicalIP(s string) string {
	// SplitHostPort already strips brackets, but XFF or odd inputs may
	// carry them — strip defensively before parsing.
	s = strings.TrimPrefix(strings.TrimSuffix(s, "]"), "[")
	if ip := net.ParseIP(s); ip != nil {
		return ip.String()
	}
	return s
}
