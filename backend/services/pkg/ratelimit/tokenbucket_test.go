package ratelimit

import (
	"net/http"
	"net/http/httptest"
	"strconv"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// fixedClock lets tests advance time deterministically.
type fixedClock struct {
	mu  sync.Mutex
	now time.Time
}

func newFixedClock(t time.Time) *fixedClock { return &fixedClock{now: t} }

func (c *fixedClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.now
}

func (c *fixedClock) advance(d time.Duration) {
	c.mu.Lock()
	c.now = c.now.Add(d)
	c.mu.Unlock()
}

func TestTokenBucket_AllowsUpToBurst(t *testing.T) {
	clk := newFixedClock(time.Unix(0, 0))
	tb := NewTokenBucket(TokenBucketConfig{
		Rate:  10, // 10 tokens/sec
		Burst: 5,
		Now:   clk.Now,
	})

	for i := 0; i < 5; i++ {
		if !tb.Allow("ip-1") {
			t.Fatalf("Allow %d: want true within burst, got false", i)
		}
	}
	if tb.Allow("ip-1") {
		t.Fatal("Allow over burst: want false, got true")
	}
}

func TestTokenBucket_RefillsAtRate(t *testing.T) {
	clk := newFixedClock(time.Unix(0, 0))
	tb := NewTokenBucket(TokenBucketConfig{
		Rate:  10, // one token per 100ms
		Burst: 1,
		Now:   clk.Now,
	})

	if !tb.Allow("k") {
		t.Fatal("first Allow: want true")
	}
	if tb.Allow("k") {
		t.Fatal("immediate second Allow: want false (burst exhausted)")
	}

	clk.advance(100 * time.Millisecond)
	if !tb.Allow("k") {
		t.Fatal("Allow after 100ms refill: want true")
	}
}

func TestTokenBucket_RefillCappedAtBurst(t *testing.T) {
	clk := newFixedClock(time.Unix(0, 0))
	tb := NewTokenBucket(TokenBucketConfig{
		Rate:  10,
		Burst: 3,
		Now:   clk.Now,
	})

	// Idle for a long time — bucket must NOT exceed Burst.
	clk.advance(1 * time.Hour)

	for i := 0; i < 3; i++ {
		if !tb.Allow("k") {
			t.Fatalf("Allow %d after idle: want true, got false", i)
		}
	}
	if tb.Allow("k") {
		t.Fatal("4th Allow after idle: want false (capped at burst)")
	}
}

func TestTokenBucket_KeysAreIsolated(t *testing.T) {
	clk := newFixedClock(time.Unix(0, 0))
	tb := NewTokenBucket(TokenBucketConfig{Rate: 10, Burst: 1, Now: clk.Now})

	if !tb.Allow("a") {
		t.Fatal("a: first Allow want true")
	}
	if !tb.Allow("b") {
		t.Fatal("b: first Allow want true (independent bucket)")
	}
	if tb.Allow("a") {
		t.Fatal("a: second Allow want false")
	}
}

func TestTokenBucket_EvictsIdleKeys(t *testing.T) {
	clk := newFixedClock(time.Unix(0, 0))
	tb := NewTokenBucket(TokenBucketConfig{
		Rate:        10,
		Burst:       1,
		IdleTimeout: 1 * time.Minute,
		Now:         clk.Now,
	})

	tb.Allow("k1")
	tb.Allow("k2")
	if got := tb.Size(); got != 2 {
		t.Fatalf("Size after two keys: want 2, got %d", got)
	}

	clk.advance(2 * time.Minute)
	tb.SweepIdle()
	if got := tb.Size(); got != 0 {
		t.Fatalf("Size after sweep: want 0, got %d", got)
	}
}

func TestTokenBucket_ConcurrentAllowSafe(t *testing.T) {
	clk := newFixedClock(time.Unix(0, 0))
	tb := NewTokenBucket(TokenBucketConfig{Rate: 1000, Burst: 100, Now: clk.Now})

	var allowed atomic.Int64
	var wg sync.WaitGroup
	for i := 0; i < 500; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if tb.Allow("shared") {
				allowed.Add(1)
			}
		}()
	}
	wg.Wait()

	// With clock frozen at t=0 and burst=100, exactly 100 must pass.
	if got := allowed.Load(); got != 100 {
		t.Fatalf("concurrent Allow: want exactly 100 allowed, got %d", got)
	}
}

func TestTokenBucket_NewPanicsOnInvalidConfig(t *testing.T) {
	cases := []TokenBucketConfig{
		{Rate: 0, Burst: 1},
		{Rate: -1, Burst: 1},
		{Rate: 1, Burst: 0},
		{Rate: 1, Burst: -1},
	}
	for i, c := range cases {
		func() {
			defer func() {
				if r := recover(); r == nil {
					t.Fatalf("case %d: want panic on invalid config %+v", i, c)
				}
			}()
			NewTokenBucket(c)
		}()
	}
}

func TestMiddlewareByIP_AllowsThenRejectsWith429(t *testing.T) {
	clk := newFixedClock(time.Unix(0, 0))
	tb := NewTokenBucket(TokenBucketConfig{Rate: 1, Burst: 1, Now: clk.Now})
	mw := MiddlewareByIP(tb)
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	// First request: allowed.
	req1 := httptest.NewRequest(http.MethodGet, "/x", nil)
	req1.RemoteAddr = "203.0.113.5:12345"
	rec1 := httptest.NewRecorder()
	handler.ServeHTTP(rec1, req1)
	if rec1.Code != http.StatusOK {
		t.Fatalf("first request: want 200, got %d", rec1.Code)
	}

	// Second from same IP: 429 with Retry-After header.
	req2 := httptest.NewRequest(http.MethodGet, "/x", nil)
	req2.RemoteAddr = "203.0.113.5:54321"
	rec2 := httptest.NewRecorder()
	handler.ServeHTTP(rec2, req2)
	if rec2.Code != http.StatusTooManyRequests {
		t.Fatalf("second request: want 429, got %d", rec2.Code)
	}
	ra := rec2.Header().Get("Retry-After")
	if ra == "" {
		t.Fatal("429 response: missing Retry-After header")
	}
	if n, err := strconv.Atoi(ra); err != nil || n < 1 {
		t.Fatalf("Retry-After: want positive integer seconds, got %q", ra)
	}
}

func TestMiddlewareByIP_NormalizesIPv6(t *testing.T) {
	clk := newFixedClock(time.Unix(0, 0))
	tb := NewTokenBucket(TokenBucketConfig{Rate: 1, Burst: 1, Now: clk.Now})
	mw := MiddlewareByIP(tb)
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	// Same IPv6 address in bracketed RemoteAddr form and bare XFF form
	// must collide on a single bucket — otherwise spoofing the format
	// trivially doubles the budget.
	req1 := httptest.NewRequest(http.MethodGet, "/x", nil)
	req1.RemoteAddr = "[2001:db8::1]:443"
	rec1 := httptest.NewRecorder()
	handler.ServeHTTP(rec1, req1)
	if rec1.Code != http.StatusOK {
		t.Fatalf("first IPv6: want 200, got %d", rec1.Code)
	}

	req2 := httptest.NewRequest(http.MethodGet, "/x", nil)
	req2.RemoteAddr = "[10.0.0.1]:443"
	req2.Header.Set("X-Forwarded-For", "2001:db8::1")
	rec2 := httptest.NewRecorder()
	handler.ServeHTTP(rec2, req2)
	if rec2.Code != http.StatusTooManyRequests {
		t.Fatalf("same IPv6 via XFF: want 429, got %d", rec2.Code)
	}
}

func TestMiddlewareByIP_TrustXFFFalseIgnoresHeader(t *testing.T) {
	clk := newFixedClock(time.Unix(0, 0))
	tb := NewTokenBucket(TokenBucketConfig{Rate: 1, Burst: 1, Now: clk.Now})
	mw := MiddlewareByIP(tb, WithTrustXFF(false))
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	// Two requests from the same RemoteAddr but different XFF — with
	// XFF distrusted, both must hit the same bucket and the second
	// must be limited.
	req1 := httptest.NewRequest(http.MethodGet, "/x", nil)
	req1.RemoteAddr = "10.0.0.5:443"
	req1.Header.Set("X-Forwarded-For", "198.51.100.1")
	rec1 := httptest.NewRecorder()
	handler.ServeHTTP(rec1, req1)
	if rec1.Code != http.StatusOK {
		t.Fatalf("first: want 200, got %d", rec1.Code)
	}

	req2 := httptest.NewRequest(http.MethodGet, "/x", nil)
	req2.RemoteAddr = "10.0.0.5:443"
	req2.Header.Set("X-Forwarded-For", "198.51.100.2")
	rec2 := httptest.NewRecorder()
	handler.ServeHTTP(rec2, req2)
	if rec2.Code != http.StatusTooManyRequests {
		t.Fatalf("second (XFF distrusted): want 429, got %d", rec2.Code)
	}
}

func TestMiddlewareByIP_UsesXForwardedForBehindCaddy(t *testing.T) {
	clk := newFixedClock(time.Unix(0, 0))
	tb := NewTokenBucket(TokenBucketConfig{Rate: 1, Burst: 1, Now: clk.Now})
	mw := MiddlewareByIP(tb)
	handler := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	// Two distinct client IPs forwarded by Caddy from the same upstream conn —
	// must be tracked independently, not as one bucket from RemoteAddr.
	req1 := httptest.NewRequest(http.MethodGet, "/x", nil)
	req1.RemoteAddr = "10.0.0.1:443"
	req1.Header.Set("X-Forwarded-For", "198.51.100.1")
	rec1 := httptest.NewRecorder()
	handler.ServeHTTP(rec1, req1)

	req2 := httptest.NewRequest(http.MethodGet, "/x", nil)
	req2.RemoteAddr = "10.0.0.1:443"
	req2.Header.Set("X-Forwarded-For", "198.51.100.2")
	rec2 := httptest.NewRecorder()
	handler.ServeHTTP(rec2, req2)

	if rec1.Code != http.StatusOK || rec2.Code != http.StatusOK {
		t.Fatalf("both distinct XFF IPs should pass: got %d, %d", rec1.Code, rec2.Code)
	}

	// Third request reusing client 1's XFF should be rate-limited.
	req3 := httptest.NewRequest(http.MethodGet, "/x", nil)
	req3.RemoteAddr = "10.0.0.1:443"
	req3.Header.Set("X-Forwarded-For", "198.51.100.1")
	rec3 := httptest.NewRecorder()
	handler.ServeHTTP(rec3, req3)
	if rec3.Code != http.StatusTooManyRequests {
		t.Fatalf("repeat XFF: want 429, got %d", rec3.Code)
	}
}
