package notification

import (
	"context"
	"encoding/json"
	"errors"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"shiptrip/pkg/redisbus"
)

// fcmFakeStream is an in-memory streamClient. XReadGroup and XAutoClaim replay
// scripted results in order; once the XReadGroup script is exhausted it blocks
// until ctx is cancelled, like a real BLOCK read on an idle stream.
type fcmFakeStream struct {
	mu          sync.Mutex
	createStart []string
	reads       []fcmFakeRead
	claims      []fcmFakeClaim
	claimStarts []string
	acked       []string
	added       []string
}

type fcmFakeRead struct {
	msgs []redisbus.StreamMessage
	err  error
}

type fcmFakeClaim struct {
	msgs []redisbus.StreamMessage
	next string
}

func (f *fcmFakeStream) XGroupCreate(_ context.Context, _, _, start string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.createStart = append(f.createStart, start)
	return nil
}

func (f *fcmFakeStream) XReadGroup(ctx context.Context, _ redisbus.XReadGroupArgs) ([]redisbus.StreamMessage, error) {
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

func (f *fcmFakeStream) XAutoClaim(_ context.Context, args redisbus.XAutoClaimArgs) ([]redisbus.StreamMessage, string, error) {
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

func (f *fcmFakeStream) XAck(_ context.Context, _, _ string, ids ...string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.acked = append(f.acked, ids...)
	return nil
}

func (f *fcmFakeStream) XAddCapped(_ context.Context, stream string, _ int64, _ map[string]any) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.added = append(f.added, stream)
	return "9-0", nil
}

func (f *fcmFakeStream) Exists(context.Context, string) (bool, error) { return false, nil }

func (f *fcmFakeStream) SetEX(context.Context, string, any, time.Duration) error { return nil }

func (f *fcmFakeStream) snapshot() (creates, claimStarts, acked []string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.createStart...),
		append([]string(nil), f.claimStarts...),
		append([]string(nil), f.acked...)
}

// fcmCountingSender is safe for the consumer's concurrent handlers.
type fcmCountingSender struct {
	mu   sync.Mutex
	sent int
}

func (s *fcmCountingSender) Send(_ context.Context, p FCMPayload) (SendResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.sent++
	return SendResult{SuccessfulDeviceIDs: p.DeviceIDs, SuccessfulTokenFingerprints: p.TokenFingerprints}, nil
}

func (s *fcmCountingSender) count() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.sent
}

func fcmEntry(t *testing.T, id, eventID string) redisbus.StreamMessage {
	t.Helper()
	raw, err := json.Marshal(FCMPayload{
		EventID: eventID, UserID: 7, Tokens: []string{"token"}, DeviceIDs: []int64{1},
		TokenFingerprints: []string{strings.Repeat("a", 64)}, Title: "t", Body: "b",
	})
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	return redisbus.StreamMessage{ID: id, Values: map[string]any{
		"event_id": eventID, "user_id": "7", "payload": string(raw),
	}}
}

func fcmTestConsumer(rdb streamClient, sender FCMSender) *Consumer {
	c := NewConsumer(nil, ConsumerConfig{Sender: sender}, discardLogger())
	c.rdb = rdb
	c.deliverGrace = 0
	return c
}

func fcmWaitUntil(t *testing.T, what string, pred func() bool) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for !pred() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for %s", what)
		}
		time.Sleep(5 * time.Millisecond)
	}
}

func TestFCMRunCreatesGroupWithBoundedLookback(t *testing.T) {
	rdb := &fcmFakeStream{}
	c := fcmTestConsumer(rdb, &fcmCountingSender{})
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	before := time.Now()
	go func() { done <- c.Run(ctx) }()
	fcmWaitUntil(t, "group creation", func() bool { creates, _, _ := rdb.snapshot(); return len(creates) == 1 })
	cancel()
	if err := <-done; err != nil {
		t.Fatalf("Run returned %v", err)
	}

	creates, _, _ := rdb.snapshot()
	ms, err := strconv.ParseInt(strings.TrimSuffix(creates[0], "-0"), 10, 64)
	if err != nil {
		t.Fatalf("group start %q is not a millisecond stream ID: %v", creates[0], err)
	}
	// "$" would skip pushes Django's job loop appended before this worker booted.
	lowest := before.Add(-redisbus.GroupCreateLookback).UnixMilli()
	if ms < lowest || ms > time.Now().UnixMilli() {
		t.Fatalf("group start %d outside lookback window [%d, now]", ms, lowest)
	}
}

func TestFCMRunRecreatesAMissingGroupAndKeepsConsuming(t *testing.T) {
	rdb := &fcmFakeStream{reads: []fcmFakeRead{
		{err: errors.New("NOGROUP No such key 'notif:fcm' or consumer group 'notif-fcm-workers' in XREADGROUP with GROUP option")},
		{msgs: []redisbus.StreamMessage{fcmEntry(t, "1-0", "evt-after-loss")}},
	}}
	sender := &fcmCountingSender{}
	c := fcmTestConsumer(rdb, sender)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- c.Run(ctx) }()
	fcmWaitUntil(t, "post-recovery delivery", func() bool { _, _, acked := rdb.snapshot(); return len(acked) == 1 })
	cancel()
	if err := <-done; err != nil {
		t.Fatalf("Run returned %v; NOGROUP must be recovered, not fatal", err)
	}

	creates, _, acked := rdb.snapshot()
	if len(creates) != 2 {
		t.Fatalf("XGroupCreate calls = %d, want 2 (boot + NOGROUP recovery)", len(creates))
	}
	if sender.count() != 1 || acked[0] != "1-0" {
		t.Fatalf("sent=%d acked=%v, want the push sent and acked once", sender.count(), acked)
	}
}

func TestFCMSweepReclaimsEveryPendingPageUntilTheCursorEnds(t *testing.T) {
	rdb := &fcmFakeStream{claims: []fcmFakeClaim{
		{msgs: []redisbus.StreamMessage{fcmEntry(t, "1-0", "evt-a"), fcmEntry(t, "2-0", "evt-b")}, next: "3-0"},
		{msgs: []redisbus.StreamMessage{fcmEntry(t, "3-0", "evt-c")}, next: "0-0"},
	}}
	sender := &fcmCountingSender{}
	c := fcmTestConsumer(rdb, sender)

	c.sweepOnce(context.Background())
	c.wg.Wait()

	_, starts, acked := rdb.snapshot()
	if strings.Join(starts, ",") != "0-0,3-0" {
		t.Fatalf("XAUTOCLAIM starts = %v, want [0-0 3-0]", starts)
	}
	if sender.count() != 3 || len(acked) != 3 {
		t.Fatalf("sent=%d acked=%v, want every reclaimed push sent and acked", sender.count(), acked)
	}
}
