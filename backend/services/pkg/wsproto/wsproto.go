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
	// the message with a warn — same pattern as pkg/redisbus.
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

// Send queues an envelope for delivery. Non-blocking: if the per-conn
// buffer is full the message is dropped and a warn is logged. This is
// the same back-pressure policy as pkg/redisbus — a slow client must
// never stall a fan-out goroutine.
func (c *Conn) Send(env Envelope) {
	select {
	case <-c.done:
		c.log.Debug("ws send after close; dropping message",
			"event_id", env.EventID,
			"type", env.Type,
		)
		return
	case c.send <- env:
	default:
		c.log.Warn("ws send buffer full; dropping message",
			"event_id", env.EventID,
			"type", env.Type,
		)
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
	defer c.Close(websocket.StatusInternalError, "writer exit")
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
