// Package wsproto handles authenticated WebSocket upgrades and the
// JSON envelope shared between Go services and the Flutter app.
//
// Envelope shape mirrors Django's `apps.core.redis_bus` publishes
// (`{event_id, ts, type, ...}`) so delivery receipts (CLAUDE.md G1)
// work end-to-end without per-service translation.
//
// The Flutter app is the only client. Browser-specific concerns
// (Origin checks, query-param auth fallback, subprotocol negotiation)
// are intentionally absent — add them only if a web client materializes.
package wsproto

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"

	"shiptrip/pkg/auth"
)

const (
	// PingInterval is how often the server sends a control ping.
	// Must be tighter than presence TTL (15s per CLAUDE.md §5) so a
	// missed pong drops the socket before stale presence masks it.
	PingInterval = 10 * time.Second

	// WriteTimeout bounds a single Write. Slow clients get dropped
	// rather than blocking the writer goroutine forever.
	WriteTimeout = 10 * time.Second

	// SendQueueSize is the per-conn outbound buffer. Overflow drops
	// the message and disconnects the slow consumer (see Send).
	SendQueueSize = 64

	// MaxMessageBytes caps inbound frame size. Flutter never sends
	// large WS frames; uploads use HTTP. Keeps a misbehaving client
	// from OOMing the pod.
	MaxMessageBytes = 64 << 10 // 64 KiB
)

// Envelope is the wire format for every message in either direction.
// `EventID` and `Ts` are required on server→client (for G1 receipts);
// optional on client→server (the server stamps its own when relaying).
type Envelope struct {
	EventID string          `json:"event_id,omitempty"`
	Ts      string          `json:"ts,omitempty"`
	Type    string          `json:"type"`
	Payload json.RawMessage `json:"payload,omitempty"`
}

// Conn is an authenticated, concurrency-safe WebSocket wrapper.
// Send is non-blocking; the writer goroutine drains a buffered channel
// so multiple producers can fan messages in without the underlying
// library's "concurrent write" panic.
type Conn struct {
	UserID int64
	Role   string

	ws     *websocket.Conn
	send   chan Envelope
	log    *slog.Logger
	closed sync.Once
	done   chan struct{}

	// connCtx is cancelled inside Close. Per-write/per-ping deadlines
	// derive from it so Close() actually unblocks an in-flight Write
	// instead of waiting up to WriteTimeout.
	connCtx    context.Context
	connCancel context.CancelFunc
}

// Upgrade authenticates the request, performs the WebSocket handshake,
// starts the reader/writer/pinger goroutines, and returns a ready Conn.
// On auth failure it writes the appropriate HTTP status and returns an error.
func Upgrade(
	w http.ResponseWriter,
	r *http.Request,
	v *auth.Validator,
	log *slog.Logger,
) (*Conn, error) {
	if v == nil {
		http.Error(w, "internal error", http.StatusInternalServerError)
		return nil, errors.New("wsproto: nil validator")
	}
	if log == nil {
		log = slog.Default()
	}

	token, err := bearerToken(r.Header.Get("Authorization"))
	if err != nil {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return nil, fmt.Errorf("wsproto: %w", err)
	}
	claims, err := v.Validate(token)
	if err != nil {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return nil, fmt.Errorf("wsproto: token validation: %w", err)
	}

	ws, err := websocket.Accept(w, r, &websocket.AcceptOptions{
		// Flutter is not a browser; Origin is not meaningful here.
		// Any web client must be added explicitly later.
		InsecureSkipVerify: true,
	})
	if err != nil {
		return nil, fmt.Errorf("wsproto: accept: %w", err)
	}
	ws.SetReadLimit(MaxMessageBytes)

	connCtx, cancel := context.WithCancel(context.Background())
	c := &Conn{
		UserID:     claims.UserID,
		Role:       claims.Role,
		ws:         ws,
		send:       make(chan Envelope, SendQueueSize),
		log:        log.With("user_id", claims.UserID),
		done:       make(chan struct{}),
		connCtx:    connCtx,
		connCancel: cancel,
	}

	go c.writer()
	go c.pinger()

	return c, nil
}

// Read blocks until the next inbound envelope or an error. The returned
// error is terminal — callers should Close and exit their read loop.
//
// Liveness is enforced by the pinger goroutine, not a per-Read timeout:
// a per-call deadline would kill healthy idle conns even while pongs
// are flowing. Pass the request/handler context so cancellation
// propagates on shutdown.
func (c *Conn) Read(ctx context.Context) (Envelope, error) {
	var env Envelope
	if err := wsjson.Read(ctx, c.ws, &env); err != nil {
		return Envelope{}, err
	}
	if env.Type == "" {
		return Envelope{}, errors.New("wsproto: envelope missing type")
	}
	return env, nil
}

// Send queues an envelope for delivery and reports whether it was queued.
// Non-blocking — a slow client must never stall a fan-out goroutine.
//
// A full buffer drops the message AND disconnects the consumer. Dropping
// alone lost the event silently: a client slow enough to fill 64 frames
// but never slow enough to trip WriteTimeout kept its socket, so it never
// reconnected and never ran its REST catch-up. Cancelling connCtx fails
// the writer's in-flight write, the writer exits and closes the socket,
// and the client's reconnect re-reads the durable inbox. The false return
// keeps callers from writing a delivery receipt for a message that never
// left, so the FCM fallback still fires.
//
// A cancelled connCtx or a closed conn refuses the envelope up front, even
// when the buffer has room: the writer is already exiting and its drain
// discards whatever is queued, so reporting "queued" would write a receipt
// for a push that never left. The pre-check narrows that window to the
// instant between check and enqueue; it cannot be closed without a lock on
// every Send.
func (c *Conn) Send(env Envelope) bool {
	if c.connCtx.Err() != nil {
		c.log.Debug("ws send after connection teardown; dropping message",
			"event_id", env.EventID,
			"type", env.Type,
		)
		return false
	}
	// A select picks randomly among ready cases, so done gets its own
	// non-blocking check first rather than racing a free buffer slot.
	select {
	case <-c.done:
		c.log.Debug("ws send after close; dropping message",
			"event_id", env.EventID,
			"type", env.Type,
		)
		return false
	default:
	}
	select {
	case <-c.done:
		c.log.Debug("ws send after close; dropping message",
			"event_id", env.EventID,
			"type", env.Type,
		)
		return false
	case c.send <- env:
		return true
	default:
		c.log.Warn("ws send buffer full; dropping message and disconnecting slow consumer",
			"event_id", env.EventID,
			"type", env.Type,
		)
		c.connCancel()
		return false
	}
}

// Close shuts the connection down once. Subsequent calls are no-ops.
func (c *Conn) Close(code websocket.StatusCode, reason string) {
	c.closed.Do(func() {
		close(c.done)
		c.connCancel()
		_ = c.ws.Close(code, reason)
	})
}

// Done returns a channel that is closed when the connection is torn down.
// Useful for goroutines that fan events into Send and need to exit.
func (c *Conn) Done() <-chan struct{} { return c.done }

func (c *Conn) writer() {
	defer func() {
		// Drain whatever is still buffered so an exit on write error
		// doesn't silently swallow queued messages — at least the
		// operator sees the loss in logs. Non-blocking: if nothing is
		// buffered we exit cleanly.
		dropped := 0
		for {
			select {
			case env := <-c.send:
				dropped++
				c.log.Debug("ws writer exit dropping queued message",
					"event_id", env.EventID,
					"type", env.Type,
				)
			default:
				if dropped > 0 {
					c.log.Warn("ws writer exit dropped queued messages", "count", dropped)
				}
				c.Close(websocket.StatusInternalError, "writer exit")
				return
			}
		}
	}()
	for {
		select {
		case <-c.done:
			return
		case env := <-c.send:
			ctx, cancel := context.WithTimeout(c.connCtx, WriteTimeout)
			err := wsjson.Write(ctx, c.ws, env)
			cancel()
			if err != nil {
				c.log.Debug("ws write failed", "err", err)
				return
			}
		}
	}
}

func (c *Conn) pinger() {
	t := time.NewTicker(PingInterval)
	defer t.Stop()
	for {
		select {
		case <-c.done:
			return
		case <-t.C:
			ctx, cancel := context.WithTimeout(c.connCtx, WriteTimeout)
			err := c.ws.Ping(ctx)
			cancel()
			if err != nil {
				c.log.Debug("ws ping failed", "err", err)
				c.Close(websocket.StatusPolicyViolation, "ping timeout")
				return
			}
		}
	}
}

// bearerToken extracts the token from an Authorization header. The
// scheme match is case-insensitive per RFC 7235 §2.1; some clients
// send `bearer` or `BEARER`.
func bearerToken(header string) (string, error) {
	if header == "" {
		return "", errors.New("missing authorization header")
	}
	const prefix = "Bearer "
	if len(header) < len(prefix) || !strings.EqualFold(header[:len(prefix)], prefix) {
		return "", errors.New("authorization header must start with Bearer")
	}
	tok := strings.TrimSpace(header[len(prefix):])
	if tok == "" {
		return "", errors.New("empty bearer token")
	}
	return tok, nil
}
