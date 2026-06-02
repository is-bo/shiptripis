package notification

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"maps"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"shiptrip/pkg/redisbus"
	"shiptrip/pkg/wsproto"
)

// ── stubs ──────────────────────────────────────────────────────────────────────

// stubRouter records every Send and returns a configured socket count per
// user_id, simulating "local on this pod" (>0) vs "elsewhere/offline" (0).
type stubRouter struct {
	mu      sync.Mutex
	sockets map[int64]int
	calls   []routerCall
}

type routerCall struct {
	UserID int64
	Env    wsproto.Envelope
}

func newStubRouter() *stubRouter {
	return &stubRouter{sockets: make(map[int64]int)}
}

func (s *stubRouter) Send(userID int64, env wsproto.Envelope) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls = append(s.calls, routerCall{UserID: userID, Env: env})
	return s.sockets[userID]
}

func (s *stubRouter) callsCopy() []routerCall {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]routerCall, len(s.calls))
	copy(out, s.calls)
	return out
}

// stubReceipts records MarkDelivered calls and can be made to fail.
type stubReceipts struct {
	mu       sync.Mutex
	called   atomic.Int32
	eventIDs []string
	err      error
}

func (s *stubReceipts) MarkDelivered(_ context.Context, eventID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.called.Add(1)
	s.eventIDs = append(s.eventIDs, eventID)
	return s.err
}

func (s *stubReceipts) eventIDsCopy() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]string, len(s.eventIDs))
	copy(out, s.eventIDs)
	return out
}

func newTestDispatcher(hub *stubRouter, receipts *stubReceipts) *Dispatcher {
	return &Dispatcher{
		hub:         hub,
		receipts:    receipts,
		log:         slog.New(slog.NewTextHandler(io.Discard, nil)),
		dispatchSem: make(chan struct{}, dispatchConcurrency),
		receiptSem:  make(chan struct{}, receiptConcurrency),
	}
}

// envelope builds the canonical Django publish: {event_id, targets, ...extra}.
func envelope(t *testing.T, eventID string, targets []int64, extra map[string]any) []byte {
	t.Helper()
	env := map[string]any{"targets": targets}
	if eventID != "" {
		env["event_id"] = eventID
	}
	maps.Copy(env, extra)
	b, err := json.Marshal(env)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	return b
}

func eventuallyTrue(t *testing.T, pred func() bool) bool {
	t.Helper()
	deadline := time.Now().Add(200 * time.Millisecond)
	for time.Now().Before(deadline) {
		if pred() {
			return true
		}
		time.Sleep(2 * time.Millisecond)
	}
	return pred()
}

// ── routing ─────────────────────────────────────────────────────────────────────

func TestDispatch_RoutesRawPayloadToTargets(t *testing.T) {
	hub := newStubRouter()
	hub.sockets[42] = 2
	receipts := &stubReceipts{}
	d := newTestDispatcher(hub, receipts)

	raw := envelope(t, "evt-1", []int64{42}, map[string]any{"match_id": 7, "offer_id": 9})
	d.dispatch(redisbus.Message{Channel: "offer.accepted", Payload: raw})

	calls := hub.callsCopy()
	if len(calls) != 1 {
		t.Fatalf("Send called %d times, want 1", len(calls))
	}
	got := calls[0]
	if got.UserID != 42 {
		t.Errorf("Send userID = %d, want 42", got.UserID)
	}
	if got.Env.EventID != "evt-1" {
		t.Errorf("event_id = %q, want evt-1", got.Env.EventID)
	}
	// Type is the channel; the raw payload is forwarded unchanged (Go does
	// not parse match_id/offer_id — that's mobile's concern).
	if got.Env.Type != "offer.accepted" {
		t.Errorf("type = %q, want offer.accepted", got.Env.Type)
	}
	var rt map[string]any
	if err := json.Unmarshal(got.Env.Payload, &rt); err != nil {
		t.Fatalf("payload unmarshal: %v", err)
	}
	if rt["match_id"] != float64(7) || rt["offer_id"] != float64(9) {
		t.Errorf("payload passthrough mismatch: %+v", rt)
	}

	if !eventuallyTrue(t, func() bool { return receipts.called.Load() == 1 }) {
		t.Fatalf("MarkDelivered called %d times, want 1", receipts.called.Load())
	}
	if ids := receipts.eventIDsCopy(); len(ids) != 1 || ids[0] != "evt-1" {
		t.Errorf("marked %v, want [evt-1]", ids)
	}
}

func TestDispatch_FansToEveryTargetSkippingZero(t *testing.T) {
	hub := newStubRouter()
	hub.sockets[1] = 1
	hub.sockets[2] = 1
	receipts := &stubReceipts{}
	d := newTestDispatcher(hub, receipts)

	// targets=[1,2,0] — uid 0 is a defensive guard and must be skipped.
	raw := envelope(t, "evt-multi", []int64{1, 2, 0}, nil)
	d.dispatch(redisbus.Message{Channel: "match.created", Payload: raw})

	calls := hub.callsCopy()
	if len(calls) != 2 {
		t.Fatalf("Send called %d times, want 2 (uid 0 skipped)", len(calls))
	}
	seen := map[int64]bool{}
	for _, c := range calls {
		seen[c.UserID] = true
	}
	if !seen[1] || !seen[2] || seen[0] {
		t.Errorf("targeted %v, want {1,2} and not 0", seen)
	}
	if !eventuallyTrue(t, func() bool { return receipts.called.Load() == 1 }) {
		t.Errorf("MarkDelivered called %d times, want 1", receipts.called.Load())
	}
}

func TestDispatch_NoLocalSocketsSkipsReceipt(t *testing.T) {
	hub := newStubRouter() // no sockets configured → Send returns 0
	receipts := &stubReceipts{}
	d := newTestDispatcher(hub, receipts)

	raw := envelope(t, "evt-remote", []int64{42}, nil)
	d.dispatch(redisbus.Message{Channel: "trip.updated", Payload: raw})

	if calls := hub.callsCopy(); len(calls) != 1 {
		t.Fatalf("Send should probe once, got %d", len(calls))
	}
	time.Sleep(50 * time.Millisecond)
	if got := receipts.called.Load(); got != 0 {
		t.Errorf("MarkDelivered called %d times, want 0 (another pod owns it)", got)
	}
}

func TestDispatch_DropsBadEnvelopes(t *testing.T) {
	cases := []struct {
		name string
		raw  []byte
	}{
		{"invalid json", []byte("not json")},
		{"missing event_id", envelope(t, "", []int64{42}, nil)},
		{"empty targets", envelope(t, "evt-x", nil, nil)},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			hub := newStubRouter()
			hub.sockets[42] = 1
			receipts := &stubReceipts{}
			d := newTestDispatcher(hub, receipts)

			d.dispatch(redisbus.Message{Channel: "offer.accepted", Payload: tc.raw})

			if calls := hub.callsCopy(); len(calls) != 0 {
				t.Errorf("Send called %d times, want 0", len(calls))
			}
			time.Sleep(20 * time.Millisecond)
			if got := receipts.called.Load(); got != 0 {
				t.Errorf("MarkDelivered called %d times, want 0", got)
			}
		})
	}
}

func TestDispatch_ReceiptErrorIsLoggedNotPropagated(t *testing.T) {
	hub := newStubRouter()
	hub.sockets[42] = 1
	receipts := &stubReceipts{err: errors.New("postgres exploded")}
	d := newTestDispatcher(hub, receipts)

	raw := envelope(t, "evt-receipt-fails", []int64{42}, nil)
	d.dispatch(redisbus.Message{Channel: "payment.captured", Payload: raw}) // must not panic

	if !eventuallyTrue(t, func() bool { return receipts.called.Load() == 1 }) {
		t.Errorf("MarkDelivered should still have been attempted")
	}
}

// ── back-pressure / pool saturation ──────────────────────────────────────────────

func TestScheduleReceipt_DropsWhenPoolSaturated(t *testing.T) {
	hub := newStubRouter()
	receipts := &stubReceipts{}
	d := newTestDispatcher(hub, receipts)

	// Fill the receipt semaphore so the next scheduleReceipt finds no slot
	// and must drop rather than block.
	for range receiptConcurrency {
		d.receiptSem <- struct{}{}
	}

	done := make(chan struct{})
	go func() {
		d.scheduleReceipt("evt-saturated", 1) // must return immediately (drop)
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("scheduleReceipt blocked on a full pool instead of dropping")
	}

	time.Sleep(20 * time.Millisecond)
	if got := receipts.called.Load(); got != 0 {
		t.Errorf("MarkDelivered called %d times, want 0 (dropped on saturation)", got)
	}
}

func TestScheduleDispatch_DropsWhenPoolSaturated(t *testing.T) {
	hub := newStubRouter()
	hub.sockets[42] = 1
	receipts := &stubReceipts{}
	d := newTestDispatcher(hub, receipts)

	// Fill the dispatch semaphore so scheduleDispatch drops the message.
	for range dispatchConcurrency {
		d.dispatchSem <- struct{}{}
	}

	raw := envelope(t, "evt-drop", []int64{42}, nil)
	done := make(chan struct{})
	go func() {
		// ctx not cancelled; the default arm must fire and drop.
		d.scheduleDispatch(context.Background(), redisbus.Message{Channel: "offer.accepted", Payload: raw})
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("scheduleDispatch blocked on a full pool instead of dropping")
	}

	time.Sleep(20 * time.Millisecond)
	if got := hub.callsCopy(); len(got) != 0 {
		t.Errorf("Send called %d times, want 0 (message dropped before dispatch)", len(got))
	}
}

func TestScheduleDispatch_ReturnsOnCancelledCtx(t *testing.T) {
	hub := newStubRouter()
	receipts := &stubReceipts{}
	d := newTestDispatcher(hub, receipts)

	// Saturate so the sem-acquire arm can't win; a cancelled ctx must still
	// let scheduleDispatch return (the <-ctx.Done() arm), not drop-spin.
	for range dispatchConcurrency {
		d.dispatchSem <- struct{}{}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	done := make(chan struct{})
	go func() {
		d.scheduleDispatch(ctx, redisbus.Message{Channel: "x", Payload: envelope(t, "e", []int64{1}, nil)})
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("scheduleDispatch did not return on cancelled ctx")
	}
}
