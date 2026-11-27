package notification

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
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

// fcmBoundDevices answers that every device is still its recipient's.
type fcmBoundDevices struct{}

func (fcmBoundDevices) StillBound(_ context.Context, _ int64, ids []int64, _ []string) ([]bool, error) {
	bound := make([]bool, len(ids))
	for i := range bound {
		bound[i] = true
	}
	return bound, nil
}

// fcmScriptedDevices answers from a fixed set of still-bound device ids, or
// with err; it records the users it was asked about.
type fcmScriptedDevices struct {
	mu    sync.Mutex
	bound map[int64]bool
	err   error
	asked []int64
}

func (d *fcmScriptedDevices) StillBound(_ context.Context, userID int64, ids []int64, _ []string) ([]bool, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.asked = append(d.asked, userID)
	if d.err != nil {
		return nil, d.err
	}
	answer := make([]bool, len(ids))
	for i, id := range ids {
		answer[i] = d.bound[id]
	}
	return answer, nil
}

func fcmTestConsumer(rdb streamClient, sender FCMSender) *Consumer {
	return fcmTestConsumerWith(rdb, sender, fcmBoundDevices{})
}

func fcmTestConsumerWith(rdb streamClient, sender FCMSender, devices DeviceRegistry) *Consumer {
	c := NewConsumer(nil, ConsumerConfig{Sender: sender, Devices: devices}, discardLogger())
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
		{msgs: []redisbus.StreamMessage{fcmEntry(t, sid(1), "evt-after-loss")}},
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
	if sender.count() != 1 || acked[0] != sid(1) {
		t.Fatalf("sent=%d acked=%v, want the push sent and acked once", sender.count(), acked)
	}
}

func TestFCMSweepReclaimsEveryPendingPageUntilTheCursorEnds(t *testing.T) {
	rdb := &fcmFakeStream{claims: []fcmFakeClaim{
		{msgs: []redisbus.StreamMessage{fcmEntry(t, sid(1), "evt-a"), fcmEntry(t, sid(2), "evt-b")}, next: sid(3)},
		{msgs: []redisbus.StreamMessage{fcmEntry(t, sid(3), "evt-c")}, next: "0-0"},
	}}
	sender := &fcmCountingSender{}
	c := fcmTestConsumer(rdb, sender)

	c.sweepOnce(context.Background())
	c.wg.Wait()

	_, starts, acked := rdb.snapshot()
	if strings.Join(starts, ",") != "0-0,"+sid(3) {
		t.Fatalf("XAUTOCLAIM starts = %v, want [0-0 %s]", starts, sid(3))
	}
	if sender.count() != 3 || len(acked) != 3 {
		t.Fatalf("sent=%d acked=%v, want every reclaimed push sent and acked", sender.count(), acked)
	}
}

// streamBaseMs anchors fake stream IDs to now: the consumers drop entries whose
// ID timestamp is older than their retry horizon, so epoch-era IDs such as
// "1-0" would be discarded as stale rather than delivered.
var streamBaseMs = time.Now().UnixMilli()

func sid(n int) string { return fmt.Sprintf("%d-%d", streamBaseMs, n) }

// fcmScriptedSender returns a fixed result on every call.
type fcmScriptedSender struct {
	mu     sync.Mutex
	sent   int
	result SendResult
}

func (s *fcmScriptedSender) Send(context.Context, FCMPayload) (SendResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.sent++
	return s.result, nil
}

// An entry that waited for a handler slot long enough that its send could
// still be running when the sweeper's idle threshold passes is left in the
// PEL, not sent: the sweeper would otherwise reclaim it mid-send and push it
// a second time.
func TestFCMDefersAnEntryTheSweeperCouldReclaimMidSend(t *testing.T) {
	rdb := &fcmFakeStream{}
	sender := &fcmCountingSender{}
	c := fcmTestConsumer(rdb, sender)
	m := newTestMetrics("fcm-defer-test")
	c.metrics = m.g
	c.sweepMinIdle = time.Second
	c.sendBudget = 100 * time.Millisecond

	// Read 950ms ago: 950ms + a 100ms send budget reaches the 1s threshold.
	c.handle(context.Background(), fcmEntry(t, sid(1), "evt-late"), time.Now().Add(-950*time.Millisecond))
	if sender.count() != 0 {
		t.Fatalf("sent %d pushes for an entry the sweeper could reclaim mid-send", sender.count())
	}
	if _, _, acked := rdb.snapshot(); len(acked) != 0 {
		t.Fatalf("acked %v; a deferred entry must stay in the PEL for the sweeper", acked)
	}
	if got := m.read(t, "fcm_send_deferred_total"); got != 1 {
		t.Fatalf("fcm_send_deferred_total = %d, want 1", got)
	}

	// The same entry with room to spare is sent and acked.
	c.handle(context.Background(), fcmEntry(t, sid(2), "evt-fresh"), time.Now())
	if _, _, acked := rdb.snapshot(); sender.count() != 1 || len(acked) != 1 {
		t.Fatalf("sent=%d acked=%v, want the fresh entry pushed and acked", sender.count(), acked)
	}
}

// The check runs before the backoff sleep as well, so a doomed entry frees
// its slot at once instead of sleeping first.
func TestFCMDeferralHappensBeforeTheBackoffWait(t *testing.T) {
	rdb := &fcmFakeStream{}
	sender := &fcmCountingSender{}
	c := fcmTestConsumer(rdb, sender)
	c.sweepMinIdle = time.Second
	c.sendBudget = 100 * time.Millisecond
	c.deliverGrace = 5 * time.Second

	start := time.Now()
	c.handle(context.Background(), fcmEntry(t, sid(3), "evt-slow-grace"), time.Now())
	if waited := time.Since(start); waited > time.Second {
		t.Fatalf("handler slept %v before deferring; it should give the slot back at once", waited)
	}
	if sender.count() != 0 {
		t.Fatal("sent a push whose grace wait alone overruns the sweeper window")
	}
}

func TestFCMStaleDropAndExhaustedRetryAreCounted(t *testing.T) {
	rdb := &fcmFakeStream{}
	sender := &fcmScriptedSender{result: SendResult{RetryTokenIndexes: []int{0}}}
	c := fcmTestConsumer(rdb, sender)
	m := newTestMetrics("fcm-drop-counters-test")
	c.metrics = m.g

	stale := fcmEntry(t, "1000-1", "evt-stale")
	c.handle(context.Background(), stale, time.Now())
	if got := m.read(t, "fcm_stale_drops_total"); got != 1 {
		t.Fatalf("fcm_stale_drops_total = %d, want 1", got)
	}

	exhausted := fcmEntry(t, sid(4), "evt-exhausted")
	exhausted.Values["attempt"] = strconv.Itoa(maxPartialRetries)
	c.retryBase, c.retryCeiling = time.Millisecond, time.Millisecond
	c.handle(context.Background(), exhausted, time.Now())
	if got := m.read(t, "fcm_partial_retry_exhausted_total"); got != 1 {
		t.Fatalf("fcm_partial_retry_exhausted_total = %d, want 1", got)
	}
	if _, _, acked := rdb.snapshot(); len(acked) != 2 {
		t.Fatalf("acked %v, want both dropped entries acked", acked)
	}
}
