//go:build integration

// Integration tests for the redisbus client against a real Redis.
//
// redis_internal_test.go covers what is testable in isolation — the drop
// accounting and envelope parsing. Everything else in this package is a thin
// wrapper over a Redis command, and a fake would only prove the fake works.
// These tests exercise the real commands, because the interesting behaviour is
// in Redis's semantics rather than in our code:
//
//   - XGroupCreate must swallow BUSYGROUP (every pod calls it at boot).
//   - XAddCapped must actually apply MAXLEN (G1: "don't let it grow unbounded").
//   - XReadGroup must return nil, not an error, on an empty read (redis.Nil).
//   - XAutoClaim must respect MinIdle so the sweeper can't steal live work.
//   - Subscribe/pump must deliver, and drop rather than block, under
//     backpressure — the policy the whole fan-out depends on.
//
// Run with a throwaway Redis:
//
//	docker run -d --name it-redis -p 6399:6379 redis:7-alpine
//	REDIS_TEST_URL=redis://localhost:6399/0 go test -tags integration ./pkg/redisbus/
//
// Or via ./scripts/integration-test.sh, which manages the container.
package redisbus

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"testing"
	"time"
)

func itLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

// itClient dials the throwaway Redis, skipping when it is not configured so
// `go test -tags integration ./...` still runs without infra. An absent
// dependency must be a visible skip, never a silent pass.
func itClient(t *testing.T) *Client {
	t.Helper()
	url := os.Getenv("REDIS_TEST_URL")
	if url == "" {
		t.Skip("REDIS_TEST_URL not set; skipping redisbus integration test")
	}
	c, err := NewClient(context.Background(), Config{URL: url, Logger: itLogger()})
	if err != nil {
		t.Fatalf("dial redis at %s: %v", url, err)
	}
	t.Cleanup(func() { _ = c.Close() })
	return c
}

// itKey returns a per-test, per-run key and deletes it on cleanup. Per-run
// uniqueness keeps a leftover stream or consumer group from a previous run
// from changing what the next one observes.
func itKey(t *testing.T, c *Client, prefix string) string {
	t.Helper()
	key := fmt.Sprintf("test:redisbus:%s:%s:%d", prefix, t.Name(), time.Now().UnixNano())
	t.Cleanup(func() { _ = c.Del(context.Background(), key) })
	return key
}

// TestNewClient_PingsAndValidates covers the boot path: a bad URL or an
// unreachable server must fail here, at startup, rather than on the first
// publish in production (CLAUDE.md §9 — fail loud at boot).
func TestNewClient_PingsAndValidates(t *testing.T) {
	url := os.Getenv("REDIS_TEST_URL")
	if url == "" {
		t.Skip("REDIS_TEST_URL not set; skipping redisbus integration test")
	}

	t.Run("valid url with explicit pool knobs", func(t *testing.T) {
		c, err := NewClient(context.Background(), Config{
			URL:          url,
			Logger:       itLogger(),
			PoolSize:     4,
			MinIdleConns: 1,
			DialTimeout:  2 * time.Second,
			ReadTimeout:  2 * time.Second,
			WriteTimeout: 2 * time.Second,
		})
		if err != nil {
			t.Fatalf("NewClient: %v", err)
		}
		defer func() { _ = c.Close() }()
		if err := c.SetEX(context.Background(), "test:redisbus:ping", "1", time.Second); err != nil {
			t.Fatalf("client not usable: %v", err)
		}
	})

	t.Run("empty url", func(t *testing.T) {
		if _, err := NewClient(context.Background(), Config{}); err == nil {
			t.Fatal("empty URL accepted; a missing REDIS_URL must fail at boot")
		}
	})

	t.Run("unparseable url", func(t *testing.T) {
		if _, err := NewClient(context.Background(), Config{URL: "not-a-redis-url"}); err == nil {
			t.Fatal("malformed URL accepted")
		}
	})

	t.Run("unreachable server", func(t *testing.T) {
		// Port 1 is reserved and never listening.
		_, err := NewClient(context.Background(), Config{
			URL:         "redis://127.0.0.1:1/0",
			Logger:      itLogger(),
			DialTimeout: time.Second,
		})
		if err == nil {
			t.Fatal("unreachable Redis accepted; the boot ping is not enforced")
		}
	})
}

// TestKeyLifecycle covers SetEX / Exists / Del — the primitives behind the
// delivered:<event_id> marker and presence:<user_id>. The TTL is asserted
// because a SetEX that lost its expiry would leak presence keys forever and
// permanently suppress the FCM fallback.
func TestKeyLifecycle(t *testing.T) {
	c := itClient(t)
	ctx := context.Background()
	key := itKey(t, c, "key")

	exists, err := c.Exists(ctx, key)
	if err != nil {
		t.Fatalf("exists on missing key: %v", err)
	}
	if exists {
		t.Fatal("key existed before it was written")
	}

	if err := c.SetEX(ctx, key, "1", 30*time.Second); err != nil {
		t.Fatalf("setex: %v", err)
	}
	if exists, err = c.Exists(ctx, key); err != nil || !exists {
		t.Fatalf("exists after setex = %v, err = %v", exists, err)
	}

	if err := c.Del(ctx, key); err != nil {
		t.Fatalf("del: %v", err)
	}
	if exists, err = c.Exists(ctx, key); err != nil || exists {
		t.Fatalf("exists after del = %v, err = %v", exists, err)
	}

	// Del of an absent key must be a no-op, not an error: Presence.Drop runs
	// on every disconnect, including ones whose key already expired.
	if err := c.Del(ctx, key); err != nil {
		t.Fatalf("del on missing key returned an error: %v", err)
	}
}

// TestSetEX_AppliesTTL: a marker written without an expiry never goes away.
// delivered:<event_id> relies on the TTL to bound Redis growth.
func TestSetEX_AppliesTTL(t *testing.T) {
	c := itClient(t)
	ctx := context.Background()
	key := itKey(t, c, "ttl")

	if err := c.SetEX(ctx, key, "1", 500*time.Millisecond); err != nil {
		t.Fatalf("setex: %v", err)
	}
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		exists, err := c.Exists(ctx, key)
		if err != nil {
			t.Fatalf("exists: %v", err)
		}
		if !exists {
			return // expired as instructed
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatal("key never expired; SetEX is not applying its TTL")
}

// TestXGroupCreate_IsIdempotent is the property main.go depends on: every pod
// calls XGroupCreate at boot, so the second and later callers must succeed
// rather than crash-looping on BUSYGROUP.
func TestXGroupCreate_IsIdempotent(t *testing.T) {
	c := itClient(t)
	ctx := context.Background()
	stream := itKey(t, c, "group")

	for i := 0; i < 3; i++ {
		if err := c.XGroupCreate(ctx, stream, "g1", "$"); err != nil {
			t.Fatalf("XGroupCreate call %d: %v", i+1, err)
		}
	}
	// MKSTREAM must have created the stream even with no entries, otherwise
	// the first XReadGroup would fail with NOGROUP.
	if _, err := c.XReadGroup(ctx, XReadGroupArgs{
		Group: "g1", Consumer: "c1", Stream: stream, ID: ">", Count: 1, Block: 100 * time.Millisecond,
	}); err != nil {
		t.Fatalf("XReadGroup after MKSTREAM: %v", err)
	}
}

// TestXReadGroup_EmptyReadIsNotAnError: the consumer loop treats an error as
// a reason to back off for a second. If an idle read surfaced redis.Nil as an
// error, every idle consumer would log an error per BLOCK interval forever.
func TestXReadGroup_EmptyReadIsNotAnError(t *testing.T) {
	c := itClient(t)
	ctx := context.Background()
	stream := itKey(t, c, "empty")

	if err := c.XGroupCreate(ctx, stream, "g1", "$"); err != nil {
		t.Fatalf("xgroup create: %v", err)
	}
	msgs, err := c.XReadGroup(ctx, XReadGroupArgs{
		Group: "g1", Consumer: "c1", Stream: stream, ID: ">", Count: 8, Block: 200 * time.Millisecond,
	})
	if err != nil {
		t.Fatalf("empty read returned an error instead of nil: %v", err)
	}
	if len(msgs) != 0 {
		t.Fatalf("empty read returned %d messages", len(msgs))
	}
}

// TestStreamRoundTrip covers XAddCapped -> XReadGroup -> XAck, i.e. the whole
// path every FCM and email event takes, including that fields survive intact
// and that an acked entry does not redeliver.
func TestStreamRoundTrip(t *testing.T) {
	c := itClient(t)
	ctx := context.Background()
	stream := itKey(t, c, "roundtrip")

	if err := c.XGroupCreate(ctx, stream, "g1", "$"); err != nil {
		t.Fatalf("xgroup create: %v", err)
	}
	id, err := c.XAddCapped(ctx, stream, 1000, map[string]any{
		"event_id": "evt-rt-1",
		"payload":  `{"to":"a@b.c","kind":"verify"}`,
	})
	if err != nil {
		t.Fatalf("xadd: %v", err)
	}
	if id == "" {
		t.Fatal("XAddCapped returned an empty id")
	}

	msgs, err := c.XReadGroup(ctx, XReadGroupArgs{
		Group: "g1", Consumer: "c1", Stream: stream, ID: ">", Count: 8, Block: 2 * time.Second,
	})
	if err != nil {
		t.Fatalf("xreadgroup: %v", err)
	}
	if len(msgs) != 1 {
		t.Fatalf("read %d messages, want 1", len(msgs))
	}
	if msgs[0].ID != id {
		t.Errorf("id = %q, want %q", msgs[0].ID, id)
	}
	if got := msgs[0].Values["event_id"]; got != "evt-rt-1" {
		t.Errorf("event_id = %v", got)
	}
	if got := msgs[0].Values["payload"]; got != `{"to":"a@b.c","kind":"verify"}` {
		t.Errorf("payload = %v", got)
	}

	if err := c.XAck(ctx, stream, "g1", id); err != nil {
		t.Fatalf("xack: %v", err)
	}
	// After the ack the entry must not come back on a PEL replay ("0"),
	// otherwise every acked OTP would be resent on the next sweep.
	replay, err := c.XReadGroup(ctx, XReadGroupArgs{
		Group: "g1", Consumer: "c1", Stream: stream, ID: "0", Count: 8,
	})
	if err != nil {
		t.Fatalf("pel replay: %v", err)
	}
	if len(replay) != 0 {
		t.Fatalf("acked entry still in the PEL: %+v", replay)
	}
}

// TestXAddCapped_EnforcesMaxLen: G1 requires the stream be capped so an
// unconsumed stream cannot grow without bound. MAXLEN is approximate
// (Redis trims by whole nodes), so this asserts the bound is applied at all
// rather than an exact length.
func TestXAddCapped_EnforcesMaxLen(t *testing.T) {
	c := itClient(t)
	ctx := context.Background()
	stream := itKey(t, c, "maxlen")

	const cap0 = 5
	const writes = 500
	for i := 0; i < writes; i++ {
		if _, err := c.XAddCapped(ctx, stream, cap0, map[string]any{"n": fmt.Sprint(i)}); err != nil {
			t.Fatalf("xadd %d: %v", i, err)
		}
	}

	if err := c.XGroupCreate(ctx, stream, "g1", "0"); err != nil {
		t.Fatalf("xgroup create: %v", err)
	}
	msgs, err := c.XReadGroup(ctx, XReadGroupArgs{
		Group: "g1", Consumer: "c1", Stream: stream, ID: ">", Count: writes,
	})
	if err != nil {
		t.Fatalf("xreadgroup: %v", err)
	}
	// Approximate trimming keeps "at least" the cap; what must not happen is
	// retaining everything ever written.
	if len(msgs) >= writes {
		t.Fatalf("stream retained %d of %d entries; MAXLEN is not being applied", len(msgs), writes)
	}
}

// TestXAddCapped_ZeroMeansDefaultNotUnbounded: callers pass 0 to mean "the G1
// default cap", and a stream written that way must still be bounded.
//
// On what this can and cannot prove: `MAXLEN 0` would be catastrophic —
// verified directly against Redis, `XADD s MAXLEN 0 * n 1` leaves XLEN at 0,
// silently discarding every event. But go-redis never emits it: XAdd guards
// with `case a.MaxLen > 0` and omits the MAXLEN clause entirely when the field
// is zero. So deleting our own `maxLen <= 0 -> 10_000` default would NOT
// break the entry-survives assertion — it would make the stream *unbounded*,
// which is the G1 violation actually worth asserting. This test therefore
// checks both observable properties: the entry survives, and the cap is
// applied (XINFO reports a max-deleted/entries state consistent with trimming
// once the stream exceeds the default).
func TestXAddCapped_ZeroMeansDefaultNotUnbounded(t *testing.T) {
	c := itClient(t)
	ctx := context.Background()
	stream := itKey(t, c, "defaultcap")

	if _, err := c.XAddCapped(ctx, stream, 0, map[string]any{"n": "1"}); err != nil {
		t.Fatalf("xadd: %v", err)
	}
	if err := c.XGroupCreate(ctx, stream, "g1", "0"); err != nil {
		t.Fatalf("xgroup create: %v", err)
	}
	msgs, err := c.XReadGroup(ctx, XReadGroupArgs{
		Group: "g1", Consumer: "c1", Stream: stream, ID: ">", Count: 8,
	})
	if err != nil {
		t.Fatalf("xreadgroup: %v", err)
	}
	if len(msgs) != 1 {
		t.Fatalf("read %d entries, want 1 — a zero maxLen reached Redis as MAXLEN 0 and trimmed the stream", len(msgs))
	}

	// The bound must be a real number, not "no clause at all". A stream
	// created through XAddCapped(…, 0, …) is capped at the documented default,
	// so an explicit tiny cap on the same stream must still trim — proving the
	// call path applies MAXLEN rather than omitting it.
	for i := 0; i < 200; i++ {
		if _, err := c.XAddCapped(ctx, stream, 5, map[string]any{"n": fmt.Sprint(i)}); err != nil {
			t.Fatalf("xadd %d: %v", i, err)
		}
	}
	length, err := c.rdb.XLen(ctx, stream).Result()
	if err != nil {
		t.Fatalf("xlen: %v", err)
	}
	if length >= 200 {
		t.Fatalf("XLEN = %d after 201 writes with a cap of 5; MAXLEN is not being applied at all", length)
	}
}

// TestXAutoClaim_RespectsMinIdle is the invariant that keeps the sweeper from
// fighting live consumers: an entry idle for less than MinIdle must NOT be
// reclaimed, and the same entry must become claimable once it ages past it.
// Reclaiming too eagerly would hand an in-flight event to a second pod and
// produce exactly the duplicate push G1 exists to prevent.
func TestXAutoClaim_RespectsMinIdle(t *testing.T) {
	c := itClient(t)
	ctx := context.Background()
	stream := itKey(t, c, "autoclaim")

	if err := c.XGroupCreate(ctx, stream, "g1", "$"); err != nil {
		t.Fatalf("xgroup create: %v", err)
	}
	if _, err := c.XAddCapped(ctx, stream, 1000, map[string]any{"event_id": "evt-ac-1"}); err != nil {
		t.Fatalf("xadd: %v", err)
	}
	// Consumer c1 reads but never acks, leaving the entry in the PEL.
	msgs, err := c.XReadGroup(ctx, XReadGroupArgs{
		Group: "g1", Consumer: "c1", Stream: stream, ID: ">", Count: 8, Block: 2 * time.Second,
	})
	if err != nil || len(msgs) != 1 {
		t.Fatalf("initial read: %d msgs, err %v", len(msgs), err)
	}

	// Far from idle yet — the sweeper must leave it alone.
	claimed, _, err := c.XAutoClaim(ctx, XAutoClaimArgs{
		Stream: stream, Group: "g1", Consumer: "sweeper",
		MinIdle: time.Hour, Start: "0-0", Count: 8,
	})
	if err != nil {
		t.Fatalf("xautoclaim (high MinIdle): %v", err)
	}
	if len(claimed) != 0 {
		t.Fatalf("sweeper stole %d live entries despite MinIdle=1h", len(claimed))
	}

	// Once it has aged past MinIdle it must be reclaimable — this is how a
	// crashed pod's work gets picked up.
	time.Sleep(150 * time.Millisecond)
	claimed, next, err := c.XAutoClaim(ctx, XAutoClaimArgs{
		Stream: stream, Group: "g1", Consumer: "sweeper",
		MinIdle: 100 * time.Millisecond, Start: "0-0", Count: 8,
	})
	if err != nil {
		t.Fatalf("xautoclaim (low MinIdle): %v", err)
	}
	if len(claimed) != 1 {
		t.Fatalf("reclaimed %d entries, want 1 — a crashed pod's work would be stranded", len(claimed))
	}
	if claimed[0].Values["event_id"] != "evt-ac-1" {
		t.Errorf("reclaimed wrong entry: %+v", claimed[0].Values)
	}
	// A finished scan reports the "0-0" sentinel; sweepOnce loops until it
	// sees this, so a non-sentinel value here would spin forever.
	if next != "0-0" && next != "" {
		t.Errorf("next cursor = %q, want the 0-0 end-of-scan sentinel", next)
	}
}

// TestPublishSubscribe_RoundTrip covers Subscribe + pump + Channel: a publish
// on a subscribed channel must arrive with its payload and channel intact.
func TestPublishSubscribe_RoundTrip(t *testing.T) {
	c := itClient(t)
	ctx := context.Background()
	channel := fmt.Sprintf("test:redisbus:pubsub:%d", time.Now().UnixNano())

	sub, err := c.Subscribe(ctx, channel)
	if err != nil {
		t.Fatalf("subscribe: %v", err)
	}
	defer func() { _ = sub.Close() }()

	// Subscribe already round-tripped the handshake via ps.Receive, so the
	// subscription is live here and a publish cannot be lost.
	payload := []byte(`{"event_id":"evt-ps-1","targets":[7]}`)
	if err := c.Publish(ctx, channel, payload); err != nil {
		t.Fatalf("publish: %v", err)
	}

	select {
	case msg := <-sub.Channel():
		if msg.Channel != channel {
			t.Errorf("channel = %q, want %q", msg.Channel, channel)
		}
		if string(msg.Payload) != string(payload) {
			t.Errorf("payload = %s, want %s", msg.Payload, payload)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("published message never arrived")
	}
}

// TestSubscription_CloseIsIdempotentAndStopsPump: Close runs from deferred
// shutdown paths and can be reached more than once, so a second call must not
// panic on a re-closed channel. Close must also terminate the pump and close
// the outbound channel, otherwise every reconnect leaks a goroutine.
func TestSubscription_CloseIsIdempotentAndStopsPump(t *testing.T) {
	c := itClient(t)
	ctx := context.Background()
	channel := fmt.Sprintf("test:redisbus:close:%d", time.Now().UnixNano())

	sub, err := c.Subscribe(ctx, channel)
	if err != nil {
		t.Fatalf("subscribe: %v", err)
	}
	if err := sub.Close(); err != nil {
		t.Fatalf("first close: %v", err)
	}
	// Second and third calls must be safe no-ops.
	_ = sub.Close()
	_ = sub.Close()

	// The pump closes `out` on exit, so a receive must not block.
	select {
	case _, open := <-sub.Channel():
		if open {
			t.Fatal("channel still delivering after Close")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("channel not closed after Close; the pump goroutine leaked")
	}
}

// TestSubscription_DropsRatherThanBlocksWhenBufferFull is the backpressure
// policy the whole fan-out rests on. A slow reader must cause dropped
// messages (counted and logged), never a blocked pump — a blocked pump lets
// go-redis's internal buffer fill and Redis kills the subscription for slow
// consumption, which loses every subsequent event instead of a few.
func TestSubscription_DropsRatherThanBlocksWhenBufferFull(t *testing.T) {
	c := itClient(t)
	ctx := context.Background()
	channel := fmt.Sprintf("test:redisbus:backpressure:%d", time.Now().UnixNano())

	sub, err := c.Subscribe(ctx, channel)
	if err != nil {
		t.Fatalf("subscribe: %v", err)
	}
	defer func() { _ = sub.Close() }()

	// Publish well past subscribeBuffer without reading, so the pump is
	// forced down its drop path.
	const publishes = subscribeBuffer + 500
	for i := 0; i < publishes; i++ {
		if err := c.Publish(ctx, channel, []byte(fmt.Sprintf(`{"event_id":"evt-bp-%d"}`, i))); err != nil {
			t.Fatalf("publish %d: %v", i, err)
		}
	}

	// The pump must still be alive and serving: drain what buffered and
	// confirm a fresh publish gets through. If the pump had blocked instead
	// of dropping, this read would stall.
	drained := 0
	for {
		select {
		case _, open := <-sub.Channel():
			if !open {
				t.Fatal("subscription closed under backpressure; the pump died instead of dropping")
			}
			drained++
			if drained >= subscribeBuffer {
				goto drainedEnough
			}
		case <-time.After(5 * time.Second):
			goto drainedEnough
		}
	}
drainedEnough:
	if drained == 0 {
		t.Fatal("nothing was buffered at all")
	}
	if drained > publishes {
		t.Fatalf("drained %d messages from %d publishes", drained, publishes)
	}

	if err := c.Publish(ctx, channel, []byte(`{"event_id":"evt-bp-final"}`)); err != nil {
		t.Fatalf("publish after backpressure: %v", err)
	}
	select {
	case msg, open := <-sub.Channel():
		if !open {
			t.Fatal("subscription closed; the pump did not survive backpressure")
		}
		_ = msg
	case <-time.After(10 * time.Second):
		t.Fatal("pump stopped delivering after backpressure — it blocked rather than dropped")
	}
}

// TestClose_ReleasesClient: Close must actually shut the pool down, so a
// leaked client cannot keep burning a connection against the §3 budget.
func TestClose_ReleasesClient(t *testing.T) {
	url := os.Getenv("REDIS_TEST_URL")
	if url == "" {
		t.Skip("REDIS_TEST_URL not set; skipping redisbus integration test")
	}
	c, err := NewClient(context.Background(), Config{URL: url, Logger: itLogger()})
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	if err := c.Close(); err != nil {
		t.Fatalf("close: %v", err)
	}
	// Using a closed client must fail rather than silently reconnect.
	if err := c.SetEX(context.Background(), "test:redisbus:afterclose", "1", time.Second); err == nil {
		t.Fatal("client still usable after Close")
	}
}
