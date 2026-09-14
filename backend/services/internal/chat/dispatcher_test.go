package chat

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

// stubRouter is a test double for the Hub. Records every Send call and
// returns whatever socket count was configured per user_id — lets us
// simulate "user is local on this pod" (count > 0) and "user is on
// another pod or offline" (count == 0) without touching real conns.
type stubRouter struct {
	mu      sync.Mutex
	sockets map[int64]int // user_id → sockets to report on Send
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

// stubReceipts is a test double for the receiptStore. Records every
// MarkDelivered call and can be made to fail on demand.
type stubReceipts struct {
	mu       sync.Mutex
	called   atomic.Int32
	eventIDs []string
	userIDs  []int64
	err      error
}

func (s *stubReceipts) MarkDelivered(_ context.Context, eventID string, userID int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.called.Add(1)
	s.eventIDs = append(s.eventIDs, eventID)
	s.userIDs = append(s.userIDs, userID)
	return s.err
}

func (s *stubReceipts) eventIDsCopy() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]string, len(s.eventIDs))
	copy(out, s.eventIDs)
	return out
}

// newTestDispatcher builds a Dispatcher with stub collaborators. The
// real NewDispatcher requires a *pgxpool.Pool which we can't construct
// in a unit test without a live Postgres — testing dispatcher logic in
// isolation requires this seam.
func newTestDispatcher(hub *stubRouter, receipts *stubReceipts) *Dispatcher {
	return &Dispatcher{
		hub:         hub,
		receipts:    receipts,
		log:         slog.New(slog.NewTextHandler(io.Discard, nil)),
		dispatchSem: make(chan struct{}, dispatchConcurrency),
		receiptSem:  make(chan struct{}, receiptConcurrency),
	}
}

func TestDispatchChatMessageNew_RoutesToTargets(t *testing.T) {
	hub := newStubRouter()
	hub.sockets[42] = 2 // recipient has two sockets on this pod
	receipts := &stubReceipts{}
	d := newTestDispatcher(hub, receipts)

	// Canonical envelope: event_id + ts + targets + the raw chat payload
	// Django publishes via redis_bus.publish_after_commit.
	payload := chatEnvelope(t, "evt-1", []int64{42}, map[string]any{
		"ts":                "2026-05-22T12:00:00Z",
		"message_id":        100,
		"thread_id":         7,
		"sender_id":         99,
		"body":              "hello",
		"client_message_id": "bc8b7d87-3a8c-4a93-9396-c70807302ed9",
	})

	d.dispatchChatMessageNew(channelChatMessageNew, payload)

	calls := hub.callsCopy()
	if len(calls) != 1 {
		t.Fatalf("hub.Send called %d times, want 1", len(calls))
	}
	got := calls[0]
	if got.UserID != 42 {
		t.Errorf("Send userID = %d, want 42", got.UserID)
	}
	if got.Env.EventID != "evt-1" {
		t.Errorf("envelope event_id = %q, want %q", got.Env.EventID, "evt-1")
	}
	if got.Env.Ts != "2026-05-22T12:00:00Z" {
		t.Errorf("envelope ts = %q, want passthrough", got.Env.Ts)
	}
	if got.Env.Type != channelChatMessageNew {
		t.Errorf("envelope type = %q, want %q", got.Env.Type, channelChatMessageNew)
	}
	// The full payload is passed through unchanged so the client can pick
	// out message_id, thread_id, body without a follow-up GET.
	var roundTrip map[string]any
	if err := json.Unmarshal(got.Env.Payload, &roundTrip); err != nil {
		t.Fatalf("envelope payload unmarshal: %v", err)
	}
	if roundTrip["message_id"] != float64(100) || roundTrip["thread_id"] != float64(7) || roundTrip["body"] != "hello" {
		t.Errorf("envelope payload roundtrip mismatch: %+v", roundTrip)
	}
	if roundTrip["client_message_id"] != "bc8b7d87-3a8c-4a93-9396-c70807302ed9" {
		t.Fatal("client retry identity was lost in the websocket envelope")
	}

	// markDelivered is dispatched in a goroutine; poll briefly.
	if !eventuallyTrue(t, func() bool { return receipts.called.Load() == 1 }) {
		t.Fatalf("receipts.MarkDelivered called %d times, want 1", receipts.called.Load())
	}
	if ids := receipts.eventIDsCopy(); len(ids) != 1 || ids[0] != "evt-1" {
		t.Errorf("receipts marked with %v, want [evt-1]", ids)
	}
}

func TestDispatchChatMessageNew_FansToEveryTarget(t *testing.T) {
	hub := newStubRouter()
	hub.sockets[42] = 1
	hub.sockets[99] = 1
	receipts := &stubReceipts{}
	d := newTestDispatcher(hub, receipts)

	// A multi-member thread publishes targets=[42,99,0]; the 0 is a
	// defensive guard (skipped) and must not produce a Send.
	payload := chatEnvelope(t, "evt-multi", []int64{42, 99, 0}, nil)
	d.dispatchChatMessageNew(channelChatMessageNew, payload)

	calls := hub.callsCopy()
	if len(calls) != 2 {
		t.Fatalf("hub.Send called %d times, want 2 (uid 0 skipped)", len(calls))
	}
	seen := map[int64]bool{}
	for _, c := range calls {
		seen[c.UserID] = true
	}
	if !seen[42] || !seen[99] || seen[0] {
		t.Errorf("Send targeted %v, want {42,99} and not 0", seen)
	}
	if !eventuallyTrue(t, func() bool { return receipts.called.Load() == 2 }) {
		t.Errorf("receipts.MarkDelivered called %d times, want 2", receipts.called.Load())
	}
}

func TestDispatchChatMessageNew_NoLocalSocketsSkipsReceipt(t *testing.T) {
	hub := newStubRouter() // sockets map empty → Send returns 0
	receipts := &stubReceipts{}
	d := newTestDispatcher(hub, receipts)

	payload := chatEnvelope(t, "evt-no-local", []int64{42}, nil)

	d.dispatchChatMessageNew(channelChatMessageNew, payload)

	if calls := hub.callsCopy(); len(calls) != 1 {
		t.Fatalf("hub.Send should still be called once to probe, got %d", len(calls))
	}

	// markDelivered must NOT fire when sockets == 0 — the other pod (or
	// the FCM consumer) will own this delivery. Give the goroutine a
	// chance to run if it had been spawned in error.
	time.Sleep(50 * time.Millisecond)
	if got := receipts.called.Load(); got != 0 {
		t.Errorf("receipts.MarkDelivered called %d times, want 0", got)
	}
}

func TestDispatchChatMessageNew_DropsBadPayloads(t *testing.T) {
	cases := []struct {
		name    string
		payload []byte
	}{
		{"invalid json", []byte("not json")},
		{"missing event_id", chatEnvelope(t, "", []int64{42}, nil)},
		{"empty targets", chatEnvelope(t, "evt-no-targets", nil, nil)},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			hub := newStubRouter()
			hub.sockets[42] = 1 // even if hub would route, dispatcher should bail first
			receipts := &stubReceipts{}
			d := newTestDispatcher(hub, receipts)

			d.dispatchChatMessageNew(channelChatMessageNew, tc.payload)

			if calls := hub.callsCopy(); len(calls) != 0 {
				t.Errorf("hub.Send called %d times for %s, want 0",
					len(calls), tc.name)
			}
			time.Sleep(20 * time.Millisecond)
			if got := receipts.called.Load(); got != 0 {
				t.Errorf("receipts.MarkDelivered called %d times for %s, want 0",
					got, tc.name)
			}
		})
	}
}

func TestDispatchChatMessageNew_ReceiptErrorIsLoggedNotPropagated(t *testing.T) {
	hub := newStubRouter()
	hub.sockets[42] = 1
	receipts := &stubReceipts{err: errors.New("postgres exploded")}
	d := newTestDispatcher(hub, receipts)

	payload := chatEnvelope(t, "evt-receipt-fails", []int64{42}, nil)

	// Should not panic. The dispatcher only logs the error — the WS
	// fan-out already succeeded so the user got the message.
	d.dispatchChatMessageNew(channelChatMessageNew, payload)

	if !eventuallyTrue(t, func() bool { return receipts.called.Load() == 1 }) {
		t.Errorf("receipts.MarkDelivered should still have been attempted")
	}
}

func TestDispatch_UnknownChannel(t *testing.T) {
	hub := newStubRouter()
	receipts := &stubReceipts{}
	d := newTestDispatcher(hub, receipts)

	// The Run loop should never deliver this — we control the subscribe
	// list — but the default arm of dispatch() exists as defense-in-depth
	// and must not panic or fan out.
	d.dispatch(redisbus.Message{Channel: "trip.created", Payload: []byte(`{}`)})

	if calls := hub.callsCopy(); len(calls) != 0 {
		t.Errorf("hub.Send called %d times for unknown channel, want 0", len(calls))
	}
	if got := receipts.called.Load(); got != 0 {
		t.Errorf("receipts.MarkDelivered called %d times for unknown channel, want 0", got)
	}
}

// ── helpers ──────────────────────────────────────────────────────────────────

// chatEnvelope builds the canonical Django publish shape:
// {event_id, ts, targets, ...extra}. Mirrors redis_bus.publish_after_commit
// so the test exercises exactly what the dispatcher receives in prod.
func chatEnvelope(t *testing.T, eventID string, targets []int64, extra map[string]any) []byte {
	t.Helper()
	env := map[string]any{"targets": targets}
	if eventID != "" {
		env["event_id"] = eventID
	}
	maps.Copy(env, extra)
	return mustJSON(t, env)
}

func mustJSON(t *testing.T, v any) []byte {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	return b
}

// eventuallyTrue polls the predicate up to ~200ms. Goroutines (markDelivered)
// don't expose completion channels in production so the test waits.
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
