//go:build integration

// Integration tests for the email consumer against a real Redis.
//
// These reproduce, as automated regression tests, the manual end-to-end
// verification done on 2026-07-27: a Django-shaped `email:send` entry is
// consumed, sent over the EmailSender, and XAcked; a send failure is left
// in the PEL; and the XAUTOCLAIM sweeper reclaims and redelivers it.
//
// Run with a throwaway Redis:
//
//	docker run -d --name it-redis -p 6399:6379 redis:7-alpine
//	REDIS_TEST_URL=redis://localhost:6399/0 go test -tags integration ./internal/email/
//
// SMTP is faked at the EmailSender seam rather than driven through a real
// MailHog: the SMTP transport itself is covered by smtp_sender.go's unit
// tests, while what these tests protect is the *stream* contract — read,
// dedup, ack, and PEL/sweep durability, which is where an OTP could be lost.
package email

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/redis/go-redis/v9"

	"shiptrip/pkg/redisbus"
)

func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

// pendingCount reports how many entries sit unacked in the group's PEL.
//
// This deliberately uses a raw go-redis client rather than redisbus: the only
// PEL-reading method redisbus exposes is XAutoClaim, which *reassigns*
// ownership and resets each entry's idle timer. Polling with it would keep
// resetting idle below the sweeper's MinIdle threshold and starve the very
// reclaim path TestSweeperRedeliversAfterSendFailure asserts. XPENDING is
// read-only, so observing never perturbs what is being observed.
func pendingCount(t *testing.T, raw *redis.Client, stream, group string) int {
	t.Helper()
	n, err := raw.XPendingExt(context.Background(), &redis.XPendingExtArgs{
		Stream: stream,
		Group:  group,
		Start:  "-",
		End:    "+",
		Count:  100,
	}).Result()
	if err != nil {
		// Run creates the group asynchronously, so a probe can land before
		// the stream/group exists. That is "nothing pending yet", not a
		// failure — polling callers will see the real count once it appears.
		if strings.Contains(err.Error(), "NOGROUP") {
			return 0
		}
		t.Fatalf("xpending: %v", err)
	}
	return len(n)
}

// recordingSender captures sends and can be told to fail, so a test can
// simulate an SMTP outage and then a recovery.
type recordingSender struct {
	mu   sync.Mutex
	sent []EmailPayload
	fail bool
}

func (r *recordingSender) Send(_ context.Context, p EmailPayload) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.fail {
		return fmt.Errorf("simulated smtp outage for %s", p.EventID)
	}
	r.sent = append(r.sent, p)
	return nil
}

func (r *recordingSender) setFail(v bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.fail = v
}

func (r *recordingSender) count() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.sent)
}

func (r *recordingSender) last() (EmailPayload, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.sent) == 0 {
		return EmailPayload{}, false
	}
	return r.sent[len(r.sent)-1], true
}

// newTestClient dials the throwaway Redis, skipping the test when the env
// var is absent so `go test -tags integration ./...` stays usable without
// infra (an unavailable dependency is a skip, never a silent pass). It also
// returns a raw client for the read-only XPENDING probe.
func newTestClient(t *testing.T) (*redisbus.Client, *redis.Client) {
	t.Helper()
	url := os.Getenv("REDIS_TEST_URL")
	if url == "" {
		t.Skip("REDIS_TEST_URL not set; skipping email integration test")
	}
	c, err := redisbus.NewClient(context.Background(), redisbus.Config{
		URL:    url,
		Logger: discardLogger(),
	})
	if err != nil {
		t.Fatalf("dial redis at %s: %v", url, err)
	}
	t.Cleanup(func() { _ = c.Close() })

	opts, err := redis.ParseURL(url)
	if err != nil {
		t.Fatalf("parse redis url: %v", err)
	}
	raw := redis.NewClient(opts)
	t.Cleanup(func() { _ = raw.Close() })
	return c, raw
}

// uniqueStream returns a per-test stream key and deletes it (plus any
// leftover dedup markers) when the test ends.
//
// Both halves matter for repeat runs. A stream left behind accumulates
// entries, and — more subtly — a surviving `email:sent:<event_id>` marker
// makes the consumer correctly skip the "new" entry as an already-sent
// duplicate, so the test would hang waiting for a send that must never
// happen. Event IDs are therefore also unique per run (see uniqueEventID).
func uniqueStream(t *testing.T, raw *redis.Client) string {
	t.Helper()
	stream := fmt.Sprintf("test:email:send:%s", t.Name())
	del := func() {
		ctx := context.Background()
		raw.Del(ctx, stream)
		if keys, err := raw.Keys(ctx, "email:sent:it-"+t.Name()+"-*").Result(); err == nil && len(keys) > 0 {
			raw.Del(ctx, keys...)
		}
	}
	del()
	t.Cleanup(del)
	return stream
}

// uniqueEventID namespaces an event id per test *and* per run. The consumer
// dedupes on `email:sent:<event_id>`, so a fixed id would make the second run
// of a test a no-op skip rather than a send.
func uniqueEventID(t *testing.T, label string) string {
	t.Helper()
	return fmt.Sprintf("it-%s-%s-%d", t.Name(), label, time.Now().UnixNano())
}

// djangoEntry mirrors exactly what apps/core/redis_bus.enqueue_email_after_commit
// XADDs: an `event_id` field plus a compact-JSON `payload` field. If Django's
// shape ever drifts from this, these tests fail — which is the point.
func djangoEntry(t *testing.T, eventID, to, subject, body, kind string) map[string]any {
	t.Helper()
	payload, err := json.Marshal(map[string]string{
		"event_id": eventID,
		"to":       to,
		"subject":  subject,
		"body":     body,
		"kind":     kind,
	})
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	return map[string]any{"event_id": eventID, "payload": string(payload)}
}

// runConsumer starts Run (and optionally Sweep) and returns a stop func.
//
// The group is created here, before Run starts, rather than relying on Run's
// own XGroupCreate. Run creates it at "$" (new entries only), so a test that
// XADDs while that call is still in flight would enqueue *behind* the group's
// start position and hang forever. Creating it up front makes Run's call a
// no-op (it is idempotent via BUSYGROUP) and removes the race.
func runConsumer(t *testing.T, c *Consumer, withSweep bool) func() {
	t.Helper()
	if err := c.rdb.XGroupCreate(context.Background(), c.stream, c.group, "$"); err != nil {
		t.Fatalf("pre-create consumer group: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	var wg sync.WaitGroup
	wg.Add(1)
	go func() { defer wg.Done(); _ = c.Run(ctx) }()
	if withSweep {
		wg.Add(1)
		go func() { defer wg.Done(); _ = c.Sweep(ctx) }()
	}
	return func() { cancel(); wg.Wait() }
}

func waitFor(t *testing.T, what string, timeout time.Duration, pred func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if pred() {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("timed out after %s waiting for %s", timeout, what)
}

// TestConsumerDeliversDjangoShapedEntry is the happy path: the exact wire
// shape Django writes is consumed, handed to the sender with every field
// intact, and acked so it never redelivers.
func TestConsumerDeliversDjangoShapedEntry(t *testing.T) {
	rdb, raw := newTestClient(t)
	stream := uniqueStream(t, raw)
	sender := &recordingSender{}

	consumer := NewConsumer(rdb, ConsumerConfig{
		Stream:        stream,
		ConsumerGroup: "it-workers",
		ConsumerName:  "it-1",
		Sender:        sender,
	}, discardLogger())

	stop := runConsumer(t, consumer, false)
	defer stop()

	eventID := uniqueEventID(t, "happy")
	if _, err := rdb.XAddCapped(context.Background(), stream, 1000,
		djangoEntry(t, eventID, "user@example.com", "ShipTrip verification code", "Your code is 428913", "verify"),
	); err != nil {
		t.Fatalf("xadd: %v", err)
	}

	waitFor(t, "the email to be sent", 10*time.Second, func() bool { return sender.count() == 1 })

	got, _ := sender.last()
	if got.To != "user@example.com" || got.Subject != "ShipTrip verification code" {
		t.Fatalf("payload not carried through: %+v", got)
	}
	if got.Body != "Your code is 428913" {
		t.Fatalf("body = %q", got.Body)
	}
	if got.Kind != "verify" || got.EventID != eventID {
		t.Fatalf("kind/event_id = %q/%q", got.Kind, got.EventID)
	}

	// Acked: nothing left pending, so no duplicate OTP on the next read.
	waitFor(t, "the entry to be acked", 5*time.Second, func() bool {
		return pendingCount(t, raw, stream, "it-workers") == 0
	})

	// The dedup marker guards against a re-send if the entry reappears.
	exists, err := rdb.Exists(context.Background(), "email:sent:"+eventID)
	if err != nil {
		t.Fatalf("exists: %v", err)
	}
	if !exists {
		t.Fatal("email:sent marker was not written")
	}
}

// TestConsumerDropsUndeliverablePayloads: a malformed entry must be acked
// away, not retried forever. A permanently-bad payload left in the PEL
// would be swept in a loop until the stream trimmed it.
func TestConsumerDropsUndeliverablePayloads(t *testing.T) {
	rdb, raw := newTestClient(t)
	stream := uniqueStream(t, raw)
	sender := &recordingSender{}

	consumer := NewConsumer(rdb, ConsumerConfig{
		Stream:        stream,
		ConsumerGroup: "it-workers",
		ConsumerName:  "it-1",
		Sender:        sender,
	}, discardLogger())

	stop := runConsumer(t, consumer, false)
	defer stop()

	ctx := context.Background()
	// Malformed JSON, and a structurally valid entry missing `subject`.
	if _, err := rdb.XAddCapped(ctx, stream, 1000, map[string]any{
		"event_id": uniqueEventID(t, "badjson"), "payload": "{not json",
	}); err != nil {
		t.Fatalf("xadd bad json: %v", err)
	}
	noSubject, _ := json.Marshal(map[string]string{
		"event_id": uniqueEventID(t, "nosubject"), "to": "a@b.c", "body": "no subject", "kind": "verify",
	})
	if _, err := rdb.XAddCapped(ctx, stream, 1000, map[string]any{
		"event_id": uniqueEventID(t, "nosubject"), "payload": string(noSubject),
	}); err != nil {
		t.Fatalf("xadd no-subject: %v", err)
	}

	waitFor(t, "both bad entries to be acked away", 10*time.Second, func() bool {
		return pendingCount(t, raw, stream, "it-workers") == 0
	})
	if n := sender.count(); n != 0 {
		t.Fatalf("sender was called %d times for undeliverable payloads, want 0", n)
	}
}

// TestSweeperRedeliversAfterSendFailure is the durability guarantee that
// justifies using a Redis Stream instead of pub/sub: an SMTP outage must
// not lose the OTP. The failed entry stays in the PEL and the XAUTOCLAIM
// sweeper redelivers it once SMTP recovers.
func TestSweeperRedeliversAfterSendFailure(t *testing.T) {
	rdb, raw := newTestClient(t)
	stream := uniqueStream(t, raw)
	sender := &recordingSender{}
	sender.setFail(true) // SMTP is down

	consumer := NewConsumer(rdb, ConsumerConfig{
		Stream:        stream,
		ConsumerGroup: "it-workers",
		ConsumerName:  "it-1",
		Sender:        sender,
	}, discardLogger())
	// Production waits 60s idle and sweeps every 30s (CLAUDE.md G1). Shrink
	// both so the reclaim path is exercised in milliseconds; the code path
	// under test is identical.
	consumer.sweepMinIdle = 50 * time.Millisecond
	consumer.sweepInterval = 100 * time.Millisecond

	stop := runConsumer(t, consumer, true)
	defer stop()

	eventID := uniqueEventID(t, "retry")
	if _, err := rdb.XAddCapped(context.Background(), stream, 1000,
		djangoEntry(t, eventID, "retry@example.com", "ShipTrip reset code", "Your reset code is 771122", "reset"),
	); err != nil {
		t.Fatalf("xadd: %v", err)
	}

	// While SMTP is down the entry must remain pending — dropping it here
	// would silently lose a user's OTP.
	waitFor(t, "the failed entry to sit in the PEL", 10*time.Second, func() bool {
		return pendingCount(t, raw, stream, "it-workers") == 1
	})
	if n := sender.count(); n != 0 {
		t.Fatalf("sender recorded %d successful sends during the outage, want 0", n)
	}

	// SMTP recovers; the sweeper should reclaim and redeliver.
	sender.setFail(false)
	waitFor(t, "the sweeper to redeliver after recovery", 20*time.Second, func() bool {
		return sender.count() == 1
	})
	waitFor(t, "the redelivered entry to be acked", 10*time.Second, func() bool {
		return pendingCount(t, raw, stream, "it-workers") == 0
	})

	got, _ := sender.last()
	if got.EventID != eventID || got.Body != "Your reset code is 771122" {
		t.Fatalf("redelivered wrong entry: %+v", got)
	}
}
