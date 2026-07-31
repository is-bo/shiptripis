package wsproto

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"
	"github.com/golang-jwt/jwt/v5"

	"shiptrip/pkg/auth"
)

// Tests for the parts of Conn that need a real WebSocket: Upgrade (auth +
// handshake), Read, and the writer/pinger goroutines.
//
// wsproto_test.go covers what can be checked without a socket — bearer parsing,
// Send's queue/drop semantics, Close idempotency, envelope JSON. Everything
// here needs a live conn, but only an in-process httptest server, so these stay
// in the default test tier rather than behind the integration build tag: they
// need no Docker and run in milliseconds.
//
// These paths carry the WS framing every notification and chat message rides
// on, and their failure modes are quiet — an upgrade that accepts an
// unsigned token, or a writer that drops a queued message without a trace.

const testSecret = "wsproto-test-secret"

func testLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func testValidator(t *testing.T) *auth.Validator {
	t.Helper()
	v, err := auth.NewValidator(testSecret, testLogger())
	if err != nil {
		t.Fatalf("new validator: %v", err)
	}
	return v
}

// signedToken mints a token shaped like Django SimpleJWT's access token.
// Fields are overridable so a test can express exactly one defect.
func signedToken(t *testing.T, secret string, claims jwt.MapClaims) string {
	t.Helper()
	base := jwt.MapClaims{
		"user_id": float64(42),
		"role":    "sender",
		"typ":     "access",
		"jti":     "test-jti",
		"iat":     time.Now().Unix(),
		"exp":     time.Now().Add(10 * time.Minute).Unix(),
	}
	for k, v := range claims {
		base[k] = v
	}
	signed, err := jwt.NewWithClaims(jwt.SigningMethodHS256, base).SignedString([]byte(secret))
	if err != nil {
		t.Fatalf("sign token: %v", err)
	}
	return signed
}

// upgradeServer mounts Upgrade on an httptest server. Each accepted Conn is
// handed to onConn, which owns it for the rest of the request.
func upgradeServer(t *testing.T, v *auth.Validator, onConn func(*Conn)) *httptest.Server {
	t.Helper()
	var wg sync.WaitGroup
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := Upgrade(w, r, v, testLogger())
		if err != nil {
			return // Upgrade already wrote the HTTP error
		}
		wg.Add(1)
		defer wg.Done()
		onConn(conn)
	}))
	t.Cleanup(func() {
		srv.Close()
		wg.Wait()
	})
	return srv
}

func dial(t *testing.T, srv *httptest.Server, authHeader string) (*websocket.Conn, *http.Response, error) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	opts := &websocket.DialOptions{}
	if authHeader != "" {
		opts.HTTPHeader = http.Header{"Authorization": {authHeader}}
	}
	ws, resp, err := websocket.Dial(ctx, "ws"+strings.TrimPrefix(srv.URL, "http"), opts)
	if err == nil {
		// CloseNow, not Close: coder/websocket's Close performs a close
		// handshake with a hardcoded 5s timeout (close.go waitCloseHandshake),
		// and several tests here deliberately leave the peer not reading. Using
		// Close in cleanup made the package take 40s instead of ~1s.
		t.Cleanup(func() { _ = ws.CloseNow() })
	}
	return ws, resp, err
}

// drainClient reads and discards frames until the socket dies. Without a
// reader the peer's close handshake stalls for the library's full 5s, so any
// test whose *server* side closes should drain the client.
func drainClient(t *testing.T, ws *websocket.Conn) {
	t.Helper()
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			if _, _, err := ws.Read(context.Background()); err != nil {
				return
			}
		}
	}()
	t.Cleanup(func() {
		_ = ws.CloseNow()
		<-done
	})
}

// TestUpgrade_RejectsBadAuth: every rejection path must fail the handshake
// with 401 rather than upgrading. An accepted socket with an unverified token
// would let any caller impersonate any user_id over WS.
func TestUpgrade_RejectsBadAuth(t *testing.T) {
	v := testValidator(t)
	accepted := make(chan int64, 4)
	srv := upgradeServer(t, v, func(c *Conn) {
		accepted <- c.UserID
		c.Close(websocket.StatusNormalClosure, "bye")
	})

	tests := []struct {
		name   string
		header string
	}{
		{name: "no header", header: ""},
		{name: "wrong scheme", header: "Basic " + signedToken(t, testSecret, nil)},
		{
			name:   "signed with the wrong secret",
			header: "Bearer " + signedToken(t, "attacker-secret", nil),
		},
		{
			name:   "expired beyond leeway",
			header: "Bearer " + signedToken(t, testSecret, jwt.MapClaims{"exp": time.Now().Add(-1 * time.Hour).Unix()}),
		},
		{name: "not a jwt at all", header: "Bearer not-a-token"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, resp, err := dial(t, srv, tt.header)
			if err == nil {
				t.Fatal("handshake succeeded with bad auth; expected rejection")
			}
			if resp == nil {
				t.Fatalf("no HTTP response to inspect: %v", err)
			}
			if resp.StatusCode != http.StatusUnauthorized {
				t.Errorf("status = %d, want 401", resp.StatusCode)
			}
		})
	}

	select {
	case uid := <-accepted:
		t.Fatalf("a bad-auth request reached the handler as user %d", uid)
	default:
	}
}

// TestUpgrade_NilValidatorFailsClosed: a misconfigured service must 500 and
// refuse the socket, never upgrade unauthenticated. Fail-closed, not open.
func TestUpgrade_NilValidatorFailsClosed(t *testing.T) {
	reached := make(chan struct{}, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := Upgrade(w, r, nil, testLogger())
		if err == nil {
			reached <- struct{}{}
			conn.Close(websocket.StatusNormalClosure, "bye")
		}
	}))
	defer srv.Close()

	_, resp, err := dial(t, srv, "Bearer "+signedToken(t, testSecret, nil))
	if err == nil {
		t.Fatal("handshake succeeded with a nil validator")
	}
	if resp == nil || resp.StatusCode != http.StatusInternalServerError {
		t.Fatalf("want 500, got resp=%v err=%v", resp, err)
	}
	select {
	case <-reached:
		t.Fatal("Upgrade returned a usable Conn despite a nil validator")
	default:
	}
}

// TestUpgrade_PopulatesClaims: the identity the rest of the service routes on
// (UserID drives Hub fan-out) must come from the verified token.
func TestUpgrade_PopulatesClaims(t *testing.T) {
	v := testValidator(t)
	got := make(chan *Conn, 1)
	srv := upgradeServer(t, v, func(c *Conn) {
		got <- c
		<-c.Done()
	})

	ws, _, err := dial(t, srv, "Bearer "+signedToken(t, testSecret, jwt.MapClaims{
		"user_id": float64(4242), "role": "traveler",
	}))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	drainClient(t, ws)

	select {
	case c := <-got:
		if c.UserID != 4242 {
			t.Errorf("UserID = %d, want 4242", c.UserID)
		}
		if c.Role != "traveler" {
			t.Errorf("Role = %q, want traveler", c.Role)
		}
		c.Close(websocket.StatusNormalClosure, "bye")
	case <-time.After(5 * time.Second):
		t.Fatal("handler never received the conn")
	}
}

// TestConn_SendReachesClient covers the writer goroutine end-to-end: a queued
// Envelope must arrive on the wire with its fields intact. The `payload` is
// raw JSON forwarded from Django, so an encoding regression here would corrupt
// every notification body.
func TestConn_SendReachesClient(t *testing.T) {
	v := testValidator(t)
	// read signals the handler once the client has the message, so the handler
	// can close deterministically. Blocking the handler on <-c.Done() instead
	// would leave nothing to notice the client's EOF (there is no read loop
	// here), so teardown would wait on the pinger failing — two PingInterval
	// cycles, i.e. ~20s for a test that otherwise takes milliseconds.
	read := make(chan struct{})
	srv := upgradeServer(t, v, func(c *Conn) {
		c.Send(Envelope{
			EventID: "evt-1",
			Ts:      "2026-07-30T00:00:00Z",
			Type:    "offer.created",
			Payload: []byte(`{"match_id":77}`),
		})
		<-read
		c.Close(websocket.StatusNormalClosure, "sent")
	})

	ws, _, err := dial(t, srv, "Bearer "+signedToken(t, testSecret, nil))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var env Envelope
	if err := wsjson.Read(ctx, ws, &env); err != nil {
		t.Fatalf("read: %v", err)
	}
	if env.EventID != "evt-1" || env.Type != "offer.created" {
		t.Errorf("envelope = %+v", env)
	}
	if string(env.Payload) != `{"match_id":77}` {
		t.Errorf("payload = %s, want {\"match_id\":77}", env.Payload)
	}
	drainClient(t, ws) // answer the server's close handshake promptly
	close(read)
}

// TestConn_ReadReceivesClientEnvelope covers Read's happy path.
func TestConn_ReadReceivesClientEnvelope(t *testing.T) {
	v := testValidator(t)
	read := make(chan Envelope, 1)
	readErr := make(chan error, 1)
	srv := upgradeServer(t, v, func(c *Conn) {
		defer c.Close(websocket.StatusNormalClosure, "bye")
		env, err := c.Read(context.Background())
		if err != nil {
			readErr <- err
			return
		}
		read <- env
	})

	ws, _, err := dial(t, srv, "Bearer "+signedToken(t, testSecret, nil))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := wsjson.Write(ctx, ws, Envelope{Type: "ping.client", Payload: []byte(`{"n":1}`)}); err != nil {
		t.Fatalf("write: %v", err)
	}

	select {
	case env := <-read:
		if env.Type != "ping.client" {
			t.Errorf("type = %q", env.Type)
		}
		if string(env.Payload) != `{"n":1}` {
			t.Errorf("payload = %s", env.Payload)
		}
	case err := <-readErr:
		t.Fatalf("Read errored: %v", err)
	case <-time.After(5 * time.Second):
		t.Fatal("Read never returned")
	}
}

// TestConn_ReadRejectsEnvelopeWithoutType: `type` is what every dispatcher
// switches on, so an untyped frame must be a terminal error rather than a
// zero-valued Envelope flowing on as if it were valid.
func TestConn_ReadRejectsEnvelopeWithoutType(t *testing.T) {
	v := testValidator(t)
	result := make(chan error, 1)
	srv := upgradeServer(t, v, func(c *Conn) {
		defer c.Close(websocket.StatusNormalClosure, "bye")
		_, err := c.Read(context.Background())
		result <- err
	})

	ws, _, err := dial(t, srv, "Bearer "+signedToken(t, testSecret, nil))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	// Valid JSON, no `type`.
	if err := ws.Write(ctx, websocket.MessageText, []byte(`{"event_id":"x"}`)); err != nil {
		t.Fatalf("write: %v", err)
	}

	select {
	case err := <-result:
		if err == nil {
			t.Fatal("Read accepted an envelope with no type")
		}
		if !strings.Contains(err.Error(), "missing type") {
			t.Errorf("err = %v, want a missing-type error", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Read never returned")
	}
}

// TestConn_ReadReturnsOnCancelledCtx: the handler read loop passes its request
// ctx, so shutdown must unblock a Read parked on an idle socket. Without this
// the connWG drain at shutdown would hang until the client happened to send.
func TestConn_ReadReturnsOnCancelledCtx(t *testing.T) {
	v := testValidator(t)
	result := make(chan error, 1)
	srv := upgradeServer(t, v, func(c *Conn) {
		defer c.Close(websocket.StatusNormalClosure, "bye")
		ctx, cancel := context.WithCancel(context.Background())
		go func() {
			time.Sleep(50 * time.Millisecond)
			cancel()
		}()
		_, err := c.Read(ctx) // client never sends
		result <- err
	})

	ws, _, err := dial(t, srv, "Bearer "+signedToken(t, testSecret, nil))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	drainClient(t, ws)

	select {
	case err := <-result:
		if err == nil {
			t.Fatal("Read returned nil error on a cancelled ctx")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Read did not unblock on ctx cancel — shutdown would hang here")
	}
}

// TestConn_ConnCtxCancelUnblocksInFlightWrite is why connCtx exists.
//
// The writer derives each write deadline from connCtx rather than
// context.Background(), so cancelling it must abort a write already blocked on
// a stalled client instead of waiting out WriteTimeout (10s). Against a client
// that has stopped reading, a regression here would pin a writer goroutine —
// and the shutdown WaitGroup behind it — for the full 10s per socket.
//
// What is timed is deliberately narrow: connCancel -> writer observes the
// cancel. An earlier version of this test wrapped c.Close() in the measured
// window and "passed" at 5.19s — it was really measuring coder/websocket's
// hardcoded 5s close handshake (close.go waitCloseHandshake), which is under
// 10s and so satisfied the assertion no matter what connCtx did.
func TestConn_ConnCtxCancelUnblocksInFlightWrite(t *testing.T) {
	v := testValidator(t)
	unblocked := make(chan time.Duration, 1)
	srv := upgradeServer(t, v, func(c *Conn) {
		// Fill the send queue with frames far larger than the socket buffer so
		// the writer is genuinely blocked in wsjson.Write, not just idle.
		big := make([]byte, 64<<10)
		for i := range big {
			big[i] = 'x'
		}
		payload := []byte(fmt.Sprintf(`{"blob":%q}`, big))
		for i := 0; i < SendQueueSize; i++ {
			c.Send(Envelope{Type: "flood", Payload: payload})
		}
		time.Sleep(200 * time.Millisecond) // let the writer block on the wire

		start := time.Now()
		c.connCancel() // exactly what Close() does to unblock writes
		<-c.Done()     // the writer's exit path calls Close, closing done
		unblocked <- time.Since(start)
	})

	ws, _, err := dial(t, srv, "Bearer "+signedToken(t, testSecret, nil))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	// Deliberately never read, so the server's writes stall.

	select {
	case elapsed := <-unblocked:
		if elapsed >= WriteTimeout {
			t.Fatalf("writer took %v to unblock (>= WriteTimeout %v); connCtx is not cancelling in-flight writes", elapsed, WriteTimeout)
		}
	case <-time.After(WriteTimeout + 5*time.Second):
		t.Fatal("writer never unblocked; an in-flight write is not being cancelled")
	}
	_ = ws.CloseNow()
}

// TestConn_SendAfterCloseIsDroppedNotPanicking: fan-out goroutines can race a
// disconnect, so Send on a closed conn must be a logged no-op. A panic here
// would take down the whole pod on an ordinary disconnect.
func TestConn_SendAfterCloseIsDroppedNotPanicking(t *testing.T) {
	v := testValidator(t)
	survived := make(chan struct{}, 1)
	srv := upgradeServer(t, v, func(c *Conn) {
		c.Close(websocket.StatusNormalClosure, "bye")
		for i := 0; i < 10; i++ {
			c.Send(Envelope{Type: "after.close"})
		}
		survived <- struct{}{}
	})

	ws, _, err := dial(t, srv, "Bearer "+signedToken(t, testSecret, nil))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	// The server Closes straight away; a client that never reads would make
	// that Close block on the library's 5s handshake timeout and time this
	// test out for a reason unrelated to what it asserts.
	drainClient(t, ws)

	select {
	case <-survived:
	case <-time.After(10 * time.Second):
		t.Fatal("handler did not survive Send-after-Close")
	}
}

// TestConn_ClientDisconnectClosesConn: when the client vanishes, the server
// Conn must tear itself down so the handler's Done() fires and the Hub entry
// is released. A conn that lingers leaks a Hub slot and stale presence.
func TestConn_ClientDisconnectClosesConn(t *testing.T) {
	v := testValidator(t)
	closed := make(chan struct{}, 1)
	srv := upgradeServer(t, v, func(c *Conn) {
		// Mirror the production read loop: read until error, then Close.
		for {
			if _, err := c.Read(context.Background()); err != nil {
				c.Close(websocket.StatusNormalClosure, "client gone")
				break
			}
		}
		<-c.Done()
		closed <- struct{}{}
	})

	ws, _, err := dial(t, srv, "Bearer "+signedToken(t, testSecret, nil))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	_ = ws.Close(websocket.StatusNormalClosure, "client leaving")

	select {
	case <-closed:
	case <-time.After(5 * time.Second):
		t.Fatal("server Conn did not tear down after client disconnect")
	}
}

// TestConn_ReadAfterCloseErrors: once closed, Read must not block forever —
// the handler loop relies on a terminal error to exit and release the conn.
func TestConn_ReadAfterCloseErrors(t *testing.T) {
	v := testValidator(t)
	result := make(chan error, 1)
	srv := upgradeServer(t, v, func(c *Conn) {
		c.Close(websocket.StatusNormalClosure, "closing immediately")
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_, err := c.Read(ctx)
		result <- err
	})

	ws, _, err := dial(t, srv, "Bearer "+signedToken(t, testSecret, nil))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	drainClient(t, ws) // otherwise the server's Close blocks 5s on the handshake

	select {
	case err := <-result:
		if err == nil {
			t.Fatal("Read succeeded on a closed conn")
		}
		if errors.Is(err, context.DeadlineExceeded) {
			t.Fatal("Read blocked until its ctx deadline instead of failing fast on a closed conn")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Read never returned on a closed conn")
	}
}

// TestPinger_KeepsIdleConnAlive: the pinger must not tear down a healthy idle
// socket. Presence depends on the conn outliving PingInterval with no traffic;
// a pinger bug here would drop every idle user every 10s.
//
// Uses a hand-built Conn wired to a real socket so PingInterval can be
// shortened — the production constant would make this a 10s test.
func TestPinger_KeepsIdleConnAlive(t *testing.T) {
	serverConn := make(chan *websocket.Conn, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ws, err := websocket.Accept(w, r, &websocket.AcceptOptions{InsecureSkipVerify: true})
		if err != nil {
			return
		}
		serverConn <- ws
		<-r.Context().Done()
	}))
	defer srv.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	client, _, err := websocket.Dial(ctx, "ws"+strings.TrimPrefix(srv.URL, "http"), nil)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer func() { _ = client.Close(websocket.StatusNormalClosure, "done") }()

	ws := <-serverConn
	connCtx, connCancel := context.WithCancel(context.Background())
	c := &Conn{
		UserID:     9,
		ws:         ws,
		send:       make(chan Envelope, SendQueueSize),
		log:        testLogger(),
		done:       make(chan struct{}),
		connCtx:    connCtx,
		connCancel: connCancel,
	}
	// Drive pings far faster than the 10s production interval.
	go func() {
		t := time.NewTicker(20 * time.Millisecond)
		defer t.Stop()
		for {
			select {
			case <-c.done:
				return
			case <-t.C:
				pctx, pcancel := context.WithTimeout(c.connCtx, WriteTimeout)
				err := c.ws.Ping(pctx)
				pcancel()
				if err != nil {
					c.Close(websocket.StatusPolicyViolation, "ping timeout")
					return
				}
			}
		}
	}()

	// The client's read loop answers pings automatically.
	go func() {
		for {
			if _, _, err := client.Read(context.Background()); err != nil {
				return
			}
		}
	}()

	select {
	case <-c.Done():
		t.Fatal("pinger closed a healthy idle conn")
	case <-time.After(300 * time.Millisecond): // ~15 ping cycles
	}
	c.Close(websocket.StatusNormalClosure, "test over")
}
