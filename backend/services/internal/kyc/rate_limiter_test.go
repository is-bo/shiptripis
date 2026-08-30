package kyc

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"shiptrip/pkg/redisbus"
)

type memoryWindow struct {
	count     int64
	expiresAt time.Time
}

// memoryFixedWindowStore is a deterministic shared-cache substitute. Its one
// mutex models the all-keys atomicity Redis supplies with Lua; separate limiter
// instances share it to simulate requests landing on different service pods.
type memoryFixedWindowStore struct {
	mu      sync.Mutex
	now     time.Time
	buckets map[string]memoryWindow
	seen    []string
	err     error
}

func newMemoryFixedWindowStore() *memoryFixedWindowStore {
	return &memoryFixedWindowStore{
		now:     time.Date(2026, 8, 30, 0, 0, 0, 0, time.UTC),
		buckets: make(map[string]memoryWindow),
	}
}

func (s *memoryFixedWindowStore) ConsumeFixedWindow(
	_ context.Context,
	buckets ...redisbus.FixedWindowBucket,
) (redisbus.FixedWindowDecision, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.err != nil {
		return redisbus.FixedWindowDecision{}, s.err
	}
	var retryAfter time.Duration
	for _, bucket := range buckets {
		s.seen = append(s.seen, bucket.Key)
		current, ok := s.buckets[bucket.Key]
		if ok && !s.now.Before(current.expiresAt) {
			delete(s.buckets, bucket.Key)
			ok = false
		}
		if ok && current.count >= bucket.Limit {
			remaining := current.expiresAt.Sub(s.now)
			if remaining > retryAfter {
				retryAfter = remaining
			}
		}
	}
	if retryAfter > 0 {
		return redisbus.FixedWindowDecision{Allowed: false, RetryAfter: retryAfter}, nil
	}
	for _, bucket := range buckets {
		current, ok := s.buckets[bucket.Key]
		if !ok {
			current.expiresAt = s.now.Add(bucket.Window)
		}
		current.count++
		s.buckets[bucket.Key] = current
	}
	return redisbus.FixedWindowDecision{Allowed: true}, nil
}

func (s *memoryFixedWindowStore) advance(d time.Duration) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.now = s.now.Add(d)
}

func (s *memoryFixedWindowStore) setError(err error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.err = err
}

func (s *memoryFixedWindowStore) seenKeys() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string(nil), s.seen...)
}

func testRateLimitConfig(userLimit int64, window time.Duration) UploadRateLimitConfig {
	return UploadRateLimitConfig{UserLimit: userLimit, UserWindow: window}
}

func mustLimiter(t *testing.T, store fixedWindowStore, cfg UploadRateLimitConfig) *RedisUploadRateLimiter {
	t.Helper()
	limiter, err := NewRedisUploadRateLimiter(store, cfg)
	if err != nil {
		t.Fatalf("NewRedisUploadRateLimiter: %v", err)
	}
	return limiter
}

func TestRedisUploadRateLimiterSharedAcrossInstancesAndUsersIsolated(t *testing.T) {
	store := newMemoryFixedWindowStore()
	first := mustLimiter(t, store, testRateLimitConfig(2, time.Hour))
	second := mustLimiter(t, store, testRateLimitConfig(2, time.Hour))

	for attempt, limiter := range []*RedisUploadRateLimiter{first, second} {
		decision, err := limiter.Allow(context.Background(), 42, "")
		if err != nil || !decision.Allowed {
			t.Fatalf("instance attempt %d allowed=%v err=%v", attempt+1, decision.Allowed, err)
		}
	}
	denied, err := first.Allow(context.Background(), 42, "")
	if err != nil || denied.Allowed || denied.RetryAfter != time.Hour {
		t.Fatalf("shared third attempt = %+v, err=%v; want denied for 1h", denied, err)
	}

	otherUser, err := second.Allow(context.Background(), 43, "")
	if err != nil || !otherUser.Allowed {
		t.Fatalf("different user was not isolated: %+v err=%v", otherUser, err)
	}
}

func TestRedisUploadRateLimiterConcurrencyCannotBypassBudget(t *testing.T) {
	store := newMemoryFixedWindowStore()
	first := mustLimiter(t, store, testRateLimitConfig(7, time.Hour))
	second := mustLimiter(t, store, testRateLimitConfig(7, time.Hour))

	var allowed atomic.Int64
	errs := make(chan error, 64)
	var wg sync.WaitGroup
	for i := range 64 {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			limiter := first
			if n%2 == 1 {
				limiter = second
			}
			decision, err := limiter.Allow(context.Background(), 42, "")
			if err != nil {
				errs <- err
				return
			}
			if decision.Allowed {
				allowed.Add(1)
			}
		}(i)
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Errorf("concurrent Allow: %v", err)
	}
	if got := allowed.Load(); got != 7 {
		t.Fatalf("allowed %d concurrent requests, want exactly 7", got)
	}
}

func TestRedisUploadRateLimiterExpiredWindowRecovers(t *testing.T) {
	store := newMemoryFixedWindowStore()
	limiter := mustLimiter(t, store, testRateLimitConfig(1, time.Minute))

	first, err := limiter.Allow(context.Background(), 42, "")
	if err != nil || !first.Allowed {
		t.Fatalf("first attempt = %+v, err=%v", first, err)
	}
	denied, err := limiter.Allow(context.Background(), 42, "")
	if err != nil || denied.Allowed || denied.RetryAfter != time.Minute {
		t.Fatalf("second attempt = %+v, err=%v", denied, err)
	}
	store.advance(time.Minute + time.Millisecond)
	recovered, err := limiter.Allow(context.Background(), 42, "")
	if err != nil || !recovered.Allowed {
		t.Fatalf("post-expiry attempt = %+v, err=%v", recovered, err)
	}
}

func TestRedisUploadRateLimiterIPIsSecondaryAndHashed(t *testing.T) {
	store := newMemoryFixedWindowStore()
	limiter := mustLimiter(t, store, UploadRateLimitConfig{
		UserLimit:  10,
		UserWindow: time.Hour,
		IPLimit:    2,
		IPWindow:   time.Hour,
	})

	for _, userID := range []int64{41, 42} {
		decision, err := limiter.Allow(context.Background(), userID, "203.0.113.9")
		if err != nil || !decision.Allowed {
			t.Fatalf("user %d from shared ip = %+v, err=%v", userID, decision, err)
		}
	}
	denied, err := limiter.Allow(context.Background(), 43, "203.0.113.9")
	if err != nil || denied.Allowed {
		t.Fatalf("third account on exhausted ip = %+v, err=%v", denied, err)
	}
	differentIP, err := limiter.Allow(context.Background(), 43, "203.0.113.10")
	if err != nil || !differentIP.Allowed {
		t.Fatalf("same user from isolated ip = %+v, err=%v", differentIP, err)
	}

	for _, key := range store.seenKeys() {
		if strings.Contains(key, "203.0.113") {
			t.Fatalf("rate-limit key exposes raw client ip: %s", key)
		}
	}
}

func TestRedisUploadRateLimiterFailsClosedAndRecoversWithSharedStore(t *testing.T) {
	store := newMemoryFixedWindowStore()
	store.setError(errors.New("shared cache unavailable"))
	limiter := mustLimiter(t, store, testRateLimitConfig(2, time.Hour))
	decision, err := limiter.Allow(context.Background(), 42, "")
	if err == nil || decision.Allowed {
		t.Fatalf("store failure = %+v, err=%v; want error", decision, err)
	}
	store.setError(nil)
	recovered, err := limiter.Allow(context.Background(), 42, "")
	if err != nil || !recovered.Allowed {
		t.Fatalf("store recovery = %+v, err=%v; want allowed", recovered, err)
	}
}

func TestNewRedisUploadRateLimiterRejectsInvalidPolicies(t *testing.T) {
	store := newMemoryFixedWindowStore()
	for name, cfg := range map[string]UploadRateLimitConfig{
		"zero user limit":    {UserLimit: 0, UserWindow: time.Hour},
		"zero user window":   {UserLimit: 1},
		"negative ip limit":  {UserLimit: 1, UserWindow: time.Hour, IPLimit: -1},
		"half enabled ip":    {UserLimit: 1, UserWindow: time.Hour, IPLimit: 1},
		"orphaned ip window": {UserLimit: 1, UserWindow: time.Hour, IPWindow: time.Hour},
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := NewRedisUploadRateLimiter(store, cfg); err == nil {
				t.Fatalf("invalid config accepted: %+v", cfg)
			}
		})
	}
}

func TestRequestClientIPUsesOnlyExplicitSource(t *testing.T) {
	for _, tc := range []struct {
		name, remote, forwarded, realIP, want string
		source                                ClientIPSource
	}{
		{
			name: "disabled ignores every address", source: ClientIPDisabled,
			remote: "10.0.0.4:1234", forwarded: "198.51.100.1", realIP: "203.0.113.9", want: "",
		},
		{
			name: "remote ignores headers", source: ClientIPRemote,
			remote: "198.51.100.8:1234", forwarded: "203.0.113.9", want: "198.51.100.8",
		},
		{
			name: "x real ip ignores remote and forwarded", source: ClientIPXRealIP,
			remote: "127.0.0.1:1234", forwarded: "198.51.100.1", realIP: "203.0.113.10", want: "203.0.113.10",
		},
		{
			name: "forwarded uses strict original entry", source: ClientIPXForwardedFor,
			forwarded: "198.51.100.1, 203.0.113.9", want: "198.51.100.1",
		},
		{
			name: "invalid original does not scan chain", source: ClientIPXForwardedFor,
			forwarded: "invalid, 203.0.113.9", want: "",
		},
		{name: "missing remote disables secondary dimension", source: ClientIPRemote, remote: "not-an-address", want: ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			req, err := http.NewRequest(http.MethodPost, "http://kyc/submit", nil)
			if err != nil {
				t.Fatal(err)
			}
			req.RemoteAddr = tc.remote
			req.Header.Set("X-Forwarded-For", tc.forwarded)
			req.Header.Set("X-Real-IP", tc.realIP)
			if got := requestClientIP(req, tc.source); got != tc.want {
				t.Fatalf("requestClientIP = %q, want %q", got, tc.want)
			}
		})
	}
}

func TestRateLimitKeyIsVersionedByDimensionAndWindow(t *testing.T) {
	key := rateLimitKey("user", "42", time.Hour)
	for _, part := range []string{"shiptrip:rate-limit:{kyc-upload}:v1", "user", "42", fmt.Sprint(time.Hour.Milliseconds())} {
		if !strings.Contains(key, part) {
			t.Fatalf("key %q missing %q", key, part)
		}
	}
}
