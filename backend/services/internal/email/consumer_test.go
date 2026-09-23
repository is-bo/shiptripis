package email

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"shiptrip/pkg/redisbus"
)

// fakeStream is an in-memory streamClient. XReadGroup and XAutoClaim replay
// scripted results in order; once the XReadGroup script is exhausted it blocks
// until ctx is cancelled, like a real BLOCK read on an idle stream.
type fakeStream struct {
	mu          sync.Mutex
	createStart []string
	reads       []fakeRead
	claims      []fakeClaim
	claimStarts []string
	acked       []string
}

type fakeRead struct {
	msgs []redisbus.StreamMessage
	err  error
}

type fakeClaim struct {
	msgs []redisbus.StreamMessage
	next string
}

func (f *fakeStream) XGroupCreate(_ context.Context, _, _, start string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.createStart = append(f.createStart, start)
	return nil
}

func (f *fakeStream) XReadGroup(ctx context.Context, _ redisbus.XReadGroupArgs) ([]redisbus.StreamMessage, error) {
	f.mu.Lock()
	if len(f.reads) > 0 {
		r := f.reads[0]
		f.reads = f.reads[1:]
		f.mu.Unlock()
		return r.msgs, r.err
	}
	f.mu.Unlock()
	<-ctx.Done()
	return nil, ctx.Err()
}

func (f *fakeStream) XAutoClaim(_ context.Context, args redisbus.XAutoClaimArgs) ([]redisbus.StreamMessage, string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.claimStarts = append(f.claimStarts, args.Start)
	if len(f.claims) == 0 {
		return nil, "0-0", nil
	}
	c := f.claims[0]
	f.claims = f.claims[1:]
	return c.msgs, c.next, nil
}

func (f *fakeStream) XAck(_ context.Context, _, _ string, ids ...string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.acked = append(f.acked, ids...)
	return nil
}

func (f *fakeStream) Exists(context.Context, string) (bool, error) { return false, nil }

func (f *fakeStream) SetEX(context.Context, string, any, time.Duration) error { return nil }

func (f *fakeStream) snapshot() (creates, claimStarts, acked []string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.createStart...),
		append([]string(nil), f.claimStarts...),
		append([]string(nil), f.acked...)
}

// countingSender is safe for the consumer's concurrent handlers.
type countingSender struct {
	mu   sync.Mutex
	sent []string
}

func (s *countingSender) Send(_ context.Context, p EmailPayload) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.sent = append(s.sent, p.EventID)
	return nil
}

func (s *countingSender) count() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.sent)
}

func entry(t *testing.T, id, eventID string) redisbus.StreamMessage {
	t.Helper()
	raw, err := json.Marshal(EmailPayload{
		EventID: eventID, To: "user@example.invalid", Subject: "s", Body: "b", Kind: "verify",
	})
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	return redisbus.StreamMessage{ID: id, Values: map[string]any{"event_id": eventID, "payload": string(raw)}}
}

func testConsumer(rdb streamClient, sender EmailSender) *Consumer {
	c := NewConsumer(nil, ConsumerConfig{Sender: sender}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	c.rdb = rdb
	return c
}

func waitUntil(t *testing.T, what string, pred func() bool) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for !pred() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for %s", what)
		}
		time.Sleep(5 * time.Millisecond)
	}
}

func TestRunCreatesGroupWithBoundedLookback(t *testing.T) {
	rdb := &fakeStream{}
	c := testConsumer(rdb, &countingSender{})
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	before := time.Now()
	go func() { done <- c.Run(ctx) }()
	waitUntil(t, "group creation", func() bool { creates, _, _ := rdb.snapshot(); return len(creates) == 1 })
	cancel()
	if err := <-done; err != nil {
		t.Fatalf("Run returned %v", err)
	}

	creates, _, _ := rdb.snapshot()
	ms, err := strconv.ParseInt(strings.TrimSuffix(creates[0], "-0"), 10, 64)
	if err != nil {
		t.Fatalf("group start %q is not a millisecond stream ID: %v", creates[0], err)
	}
	// "$" would skip entries Django appended before this worker booted.
	lowest := before.Add(-redisbus.GroupCreateLookback).UnixMilli()
	if ms < lowest || ms > time.Now().UnixMilli() {
		t.Fatalf("group start %d outside lookback window [%d, now]", ms, lowest)
	}
}

func TestRunRecreatesAMissingGroupAndKeepsConsuming(t *testing.T) {
	rdb := &fakeStream{reads: []fakeRead{
		{err: errors.New("NOGROUP No such key 'email:send' or consumer group 'email-send-workers' in XREADGROUP with GROUP option")},
		{msgs: []redisbus.StreamMessage{entry(t, sid(1), "evt-after-loss")}},
	}}
	sender := &countingSender{}
	c := testConsumer(rdb, sender)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- c.Run(ctx) }()
	waitUntil(t, "post-recovery delivery", func() bool { _, _, acked := rdb.snapshot(); return len(acked) == 1 })
	cancel()
	if err := <-done; err != nil {
		t.Fatalf("Run returned %v; NOGROUP must be recovered, not fatal", err)
	}

	creates, _, acked := rdb.snapshot()
	if len(creates) != 2 {
		t.Fatalf("XGroupCreate calls = %d, want 2 (boot + NOGROUP recovery)", len(creates))
	}
	if sender.count() != 1 || acked[0] != sid(1) {
		t.Fatalf("sent=%d acked=%v, want the entry sent and acked once", sender.count(), acked)
	}
}

func TestSweepReclaimsEveryPendingPageUntilTheCursorEnds(t *testing.T) {
	rdb := &fakeStream{claims: []fakeClaim{
		{msgs: []redisbus.StreamMessage{entry(t, sid(1), "evt-a"), entry(t, sid(2), "evt-b")}, next: sid(3)},
		{msgs: []redisbus.StreamMessage{entry(t, sid(3), "evt-c")}, next: "0-0"},
	}}
	sender := &countingSender{}
	c := testConsumer(rdb, sender)

	c.sweepOnce(context.Background())
	c.wg.Wait()

	_, starts, acked := rdb.snapshot()
	if strings.Join(starts, ",") != "0-0,"+sid(3) {
		t.Fatalf("XAUTOCLAIM starts = %v, want [0-0 %s]", starts, sid(3))
	}
	if sender.count() != 3 || len(acked) != 3 {
		t.Fatalf("sent=%d acked=%v, want every reclaimed entry sent and acked", sender.count(), acked)
	}
}

// streamBaseMs anchors fake stream IDs to now: the consumers drop entries whose
// ID timestamp is older than their retry horizon, so epoch-era IDs such as
// "1-0" would be discarded as stale rather than delivered.
var streamBaseMs = time.Now().UnixMilli()

func sid(n int) string { return fmt.Sprintf("%d-%d", streamBaseMs, n) }
