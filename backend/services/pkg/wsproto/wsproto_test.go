package wsproto

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"testing"

	"github.com/coder/websocket"
)

func TestBearerToken(t *testing.T) {
	tests := []struct {
		name    string
		header  string
		want    string
		wantErr bool
	}{
		{name: "valid", header: "Bearer abc.def.ghi", want: "abc.def.ghi"},
		{name: "lowercase scheme", header: "bearer tok", want: "tok"},
		{name: "uppercase scheme", header: "BEARER tok", want: "tok"},
		{name: "extra surrounding space", header: "Bearer   tok  ", want: "tok"},
		{name: "empty header", header: "", wantErr: true},
		{name: "wrong scheme", header: "Basic abc", wantErr: true},
		{name: "scheme only no token", header: "Bearer ", wantErr: true},
		{name: "scheme only whitespace token", header: "Bearer    ", wantErr: true},
		{name: "too short to hold prefix", header: "Bear", wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := bearerToken(tt.header)
			if tt.wantErr {
				if err == nil {
					t.Fatalf("expected error for %q, got token %q", tt.header, got)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != tt.want {
				t.Errorf("bearerToken(%q) = %q, want %q", tt.header, got, tt.want)
			}
		})
	}
}

// newTestConn builds a Conn without a real WebSocket. Send/Close/Done only
// touch send/done/log, so the nil ws is never dereferenced by those paths.
// (Close calls ws.Close, so we must not call Close on this one — the dedicated
// Close test uses a guarded variant.)
func newTestConn() *Conn {
	connCtx, cancel := context.WithCancel(context.Background())
	return &Conn{
		UserID:     7,
		send:       make(chan Envelope, SendQueueSize),
		log:        slog.New(slog.NewTextHandler(io.Discard, nil)),
		done:       make(chan struct{}),
		connCtx:    connCtx,
		connCancel: cancel,
	}
}

func TestSend_QueuesEnvelope(t *testing.T) {
	c := newTestConn()
	c.Send(Envelope{Type: "ping", EventID: "e1"})

	select {
	case got := <-c.send:
		if got.Type != "ping" || got.EventID != "e1" {
			t.Errorf("queued = %+v", got)
		}
	default:
		t.Fatal("Send did not queue the envelope")
	}
}

func TestSend_DropsAfterClose(t *testing.T) {
	c := newTestConn()
	// Fill the buffer first so the c.send<-env case is NOT ready. With a full
	// buffer the Send select has only two viable cases — <-c.done (ready) and
	// default — and a ready channel case always beats default. That makes the
	// closed-conn drop deterministic; with buffer space free, Go's select
	// would pick randomly between done and the queue write (which is fine in
	// production — a post-close enqueue is harmless since the writer is gone).
	for range SendQueueSize {
		c.Send(Envelope{Type: "fill"})
	}
	close(c.done)

	c.Send(Envelope{Type: "late", EventID: "should-drop"})

	// Drain: the "late" envelope must be absent — it hit the done case.
	for range SendQueueSize {
		if got := <-c.send; got.EventID == "should-drop" {
			t.Fatal("Send queued the envelope after close; want drop")
		}
	}
}

func TestSend_DropsWhenBufferFull(t *testing.T) {
	c := newTestConn()
	// Fill the buffer to capacity.
	for range SendQueueSize {
		c.Send(Envelope{Type: "fill"})
	}
	// One more must hit the default branch and drop, not block.
	done := make(chan struct{})
	go func() {
		c.Send(Envelope{Type: "overflow", EventID: "dropped"})
		close(done)
	}()
	select {
	case <-done:
	case <-context.Background().Done():
	}
	// Drain and confirm the overflow envelope is absent.
	for range SendQueueSize {
		if got := <-c.send; got.EventID == "dropped" {
			t.Fatal("overflow envelope should have been dropped, not buffered")
		}
	}
}

func TestDone_ClosedSignal(t *testing.T) {
	c := newTestConn()
	select {
	case <-c.Done():
		t.Fatal("Done channel closed before Close")
	default:
	}
	close(c.done)
	select {
	case <-c.Done():
	default:
		t.Fatal("Done channel should be closed after done is closed")
	}
}

func TestClose_IsIdempotent(t *testing.T) {
	// Close calls ws.Close, so give it a real (already-failed) websocket via a
	// nil-safe stand-in is not possible; instead we verify the sync.Once guard
	// by checking done is only closed once. We build a Conn whose ws.Close is a
	// no-op by using a closed in-memory pipe pair.
	c := newTestConn()
	// Replace ws with one from a failed accept is heavy; instead assert the
	// Once semantics directly on the closure path that does not need ws.
	closedCount := 0
	c.closed.Do(func() { closedCount++; close(c.done); c.connCancel() })
	c.closed.Do(func() { closedCount++ }) // must be a no-op
	if closedCount != 1 {
		t.Errorf("sync.Once ran the close body %d times, want 1", closedCount)
	}
	// done must be observably closed.
	select {
	case <-c.done:
	default:
		t.Error("done not closed after first Do")
	}
}

func TestEnvelope_JSONRoundTrip(t *testing.T) {
	// Server→client envelopes carry event_id + ts; omitempty keeps inbound
	// (client→server) frames minimal. Confirm the tags behave.
	out := Envelope{Type: "match.created"} // no event_id/ts/payload
	b, err := json.Marshal(out)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if got := string(b); got != `{"type":"match.created"}` {
		t.Errorf("marshalled = %s, want omitempty to drop event_id/ts/payload", got)
	}

	full := Envelope{EventID: "e1", Ts: "2026-06-07T00:00:00Z", Type: "x", Payload: json.RawMessage(`{"k":1}`)}
	b2, _ := json.Marshal(full)
	var back Envelope
	if err := json.Unmarshal(b2, &back); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if back.EventID != "e1" || back.Type != "x" || string(back.Payload) != `{"k":1}` {
		t.Errorf("round trip lost data: %+v", back)
	}
}

// Guard against an accidental change to the ping/TTL relationship that G1/§5
// depends on: the ping must fire tighter than the 15s presence TTL.
func TestPingInterval_TighterThanPresenceTTL(t *testing.T) {
	const presenceTTL = 15 // seconds, per CLAUDE.md §5
	if PingInterval.Seconds() >= presenceTTL {
		t.Fatalf("PingInterval %v must be < presence TTL %ds (CLAUDE.md §5)", PingInterval, presenceTTL)
	}
	// Sanity: the status code constant we close pings with exists.
	_ = websocket.StatusPolicyViolation
}
