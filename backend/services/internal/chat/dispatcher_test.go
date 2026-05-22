package chat

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
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
	mu       sync.Mutex
	sockets  map[int64]int // user_id → sockets to report on Send
	calls    []routerCall
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

// newTestDispatcher builds a Dispatcher with stub collaborators. The
// real NewDispatcher requires a *pgxpool.Pool which we can't construct
// in a unit test without a live Postgres — testing dispatcher logic in
// isolation requires this seam.
func newTestDispatcher(hub *stubRouter, receipts *stubReceipts) *Dispatcher {
	return &Dispatcher{
		hub:        hub,
		receipts:   receipts,
		log:        slog.New(slog.NewTextHandler(io.Discard, nil)),
		receiptSem: make(chan struct{}, receiptConcurrency),
	}
}

func TestDispatchChatMessageNew_RoutesToRecipient(t *testing.T) {
	hub := newStubRouter()
	hub.sockets[42] = 2 // recipient has two sockets on this pod
	receipts := &stubReceipts{}
	d := newTestDispatcher(hub, receipts)

	payload := mustJSON(t, chatMessageNewPayload{
		EventID:     "evt-1",
		Ts:          "2026-05-22T12:00:00Z",
		MessageID:   100,
		ThreadID:    7,
		SenderID:    99,
		RecipientID: 42,
		Body:        "hello",
	})

	d.dispatchChatMessageNew(payload)

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
	if got.Env.Type != channelChatMessageNew {
		t.Errorf("envelope type = %q, want %q", got.Env.Type, channelChatMessageNew)
	}
	// The full payload should be passed through unchanged so the client
	// can pick out message_id, thread_id, body without a follow-up GET.
	var roundTrip chatMessageNewPayload
	if err := json.Unmarshal(got.Env.Payload, &roundTrip); err != nil {
		t.Fatalf("envelope payload unmarshal: %v", err)
	}
	if roundTrip.MessageID != 100 || roundTrip.ThreadID != 7 || roundTrip.Body != "hello" {
		t.Errorf("envelope payload roundtrip mismatch: %+v", roundTrip)
	}

	// markDelivered is dispatched in a goroutine; poll briefly.
	if !eventuallyTrue(t, func() bool { return receipts.called.Load() == 1 }) {
		t.Fatalf("receipts.MarkDelivered called %d times, want 1", receipts.called.Load())
	}
	if ids := receipts.eventIDsCopy(); len(ids) != 1 || ids[0] != "evt-1" {
		t.Errorf("receipts marked with %v, want [evt-1]", ids)
	}
}

func TestDispatchChatMessageNew_NoLocalSocketsSkipsReceipt(t *testing.T) {
	hub := newStubRouter() // sockets map empty → Send returns 0
	receipts := &stubReceipts{}
	d := newTestDispatcher(hub, receipts)

	payload := mustJSON(t, chatMessageNewPayload{
		EventID:     "evt-no-local",
		RecipientID: 42,
	})

	d.dispatchChatMessageNew(payload)

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
		{"missing event_id", mustJSON(t, chatMessageNewPayload{
			RecipientID: 42, // event_id intentionally absent
		})},
		{"missing recipient_id", mustJSON(t, chatMessageNewPayload{
			EventID: "evt-no-recip",
			// RecipientID = 0
		})},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			hub := newStubRouter()
			hub.sockets[42] = 1 // even if hub would route, dispatcher should bail first
			receipts := &stubReceipts{}
			d := newTestDispatcher(hub, receipts)

			d.dispatchChatMessageNew(tc.payload)

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

	payload := mustJSON(t, chatMessageNewPayload{
		EventID:     "evt-receipt-fails",
		RecipientID: 42,
	})

	// Should not panic. The dispatcher only logs the error — the WS
	// fan-out already succeeded so the user got the message.
	d.dispatchChatMessageNew(payload)

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
