//go:build integration

// Integration test for the chat relay against a real Redis and a real
// WebSocket connection.
//
// This reproduces, as an automated regression test, the manual end-to-end
// verification done on 2026-07-27: a Django-shaped `chat.message.new`
// publish reaches the targeted user's live socket, is not delivered to a
// user who was not targeted, and writes the per-user delivered marker
// that suppresses the duplicate FCM push (CLAUDE.md G1).
//
// Run with a throwaway Redis:
//
//	docker run -d --name it-redis -p 6399:6379 redis:7-alpine
//	REDIS_TEST_URL=redis://localhost:6399/0 go test -tags integration ./internal/chat/
//
// dispatcher_test.go already covers the routing/receipt *logic* with stubs.
// What is only testable here is the wiring those stubs replace: the Redis
// pub/sub subscription, the JWT-authenticated WS upgrade, and the real Hub
// fan-out. Postgres is stubbed at the receiptStore seam — the SQL is one
// UPDATE covered by the unit tests, and requiring a database would make
// this test far harder to run for no extra signal.
package chat

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"
	"github.com/golang-jwt/jwt/v5"
	"github.com/redis/go-redis/v9"

	"shiptrip/pkg/auth"
	"shiptrip/pkg/redisbus"
	"shiptrip/pkg/wsproto"
)

const itJWTSecret = "integration-test-secret"

// itRedis dials the throwaway Redis, skipping when it is not configured so
// `go test -tags integration ./...` still runs without infra (an absent
// dependency is a skip, never a silent pass).
func itRedis(t *testing.T) (*redisbus.Client, *redis.Client) {
	t.Helper()
	url := os.Getenv("REDIS_TEST_URL")
	if url == "" {
		t.Skip("REDIS_TEST_URL not set; skipping chat integration test")
	}
	c, err := redisbus.NewClient(context.Background(), redisbus.Config{
		URL:    url,
		Logger: discardLogger(),
	})
	if err != nil {
		t.Fatalf("dial redis at %s: %v", url, err)
	}
	t.Cleanup(func() { _ = c.Close() })

	opts, err := redis.ParseURL(url)
	if err != nil {
		t.Fatalf("parse redis url: %v", err)
	}
	raw := redis.NewClient(opts)
	t.Cleanup(func() { _ = raw.Close() })
	return c, raw
}

// itToken mints an access token shaped like the one Django's SimpleJWT
// issues, so the WS upgrade exercises the real validator.
func itToken(t *testing.T, userID int64) string {
	t.Helper()
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"user_id": userID,
		"role":    "sender",
		"typ":     "access",
		"jti":     fmt.Sprintf("it-jti-%d", userID),
		"iat":     time.Now().Unix(),
		"exp":     time.Now().Add(10 * time.Minute).Unix(),
	})
	signed, err := tok.SignedString([]byte(itJWTSecret))
	if err != nil {
		t.Fatalf("sign token: %v", err)
	}
	return signed
}

// itServer starts a real HTTP server mounting the production WSHandler.
func itServer(t *testing.T, hub *Hub) *httptest.Server {
	t.Helper()
	validator, err := auth.NewValidator(itJWTSecret, discardLogger())
	if err != nil {
		t.Fatalf("new validator: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	var connWG sync.WaitGroup

	mux := http.NewServeMux()
	mux.HandleFunc("/ws/chat", WSHandler(ctx, validator, hub, discardLogger(), &connWG))
	srv := httptest.NewServer(mux)

	t.Cleanup(func() {
		srv.Close() // close sockets first so handlers observe EOF
		cancel()
		connWG.Wait()
	})
	return srv
}

// itDial connects as userID and returns the client conn.
func itDial(t *testing.T, srv *httptest.Server, userID int64) *websocket.Conn {
	t.Helper()
	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws/chat"
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	ws, _, err := websocket.Dial(ctx, url, &websocket.DialOptions{
		HTTPHeader: http.Header{"Authorization": {"Bearer " + itToken(t, userID)}},
	})
	if err != nil {
		t.Fatalf("dial ws as user %d: %v", userID, err)
	}
	t.Cleanup(func() { _ = ws.Close(websocket.StatusNormalClosure, "test over") })
	return ws
}

// itReceipts records MarkDelivered calls and stands in for Postgres.
type itReceipts struct {
	mu   sync.Mutex
	ids  []string
	rdb  *redisbus.Client
	fail error
}

// MarkDelivered mirrors the production receipt: write the Redis
// delivered:<event_id>:<user_id> marker (the half that gates FCM fallback) and
// record the call in place of the Postgres UPDATE.
func (r *itReceipts) MarkDelivered(ctx context.Context, eventID string, userID int64) error {
	if r.fail != nil {
		return r.fail
	}
	if err := r.rdb.SetEX(ctx, fmt.Sprintf("delivered:%s:%d", eventID, userID), "1", DeliveredTTL); err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.ids = append(r.ids, eventID)
	return nil
}

func (r *itReceipts) seen(eventID string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	for _, id := range r.ids {
		if id == eventID {
			return true
		}
	}
	return false
}

// runDispatcher wires a Dispatcher onto the real Redis subscription and the
// real Hub, then waits until Redis actually reports a subscriber on the
// channel. Redis pub/sub has no backlog, so publishing before SUBSCRIBE
// lands drops the message silently — this wait is what keeps the test from
// being flaky.
func runDispatcher(t *testing.T, rdb *redisbus.Client, raw *redis.Client, hub *Hub, receipts receiptStore) func() {
	t.Helper()
	d := &Dispatcher{
		rdb:      rdb,
		hub:      hub,
		receipts: receipts,
		log:      discardLogger(),
		// nil metrics: the Dispatcher treats the group as optional, and
		// metrics.Register publishes into the process-global expvar registry,
		// which would panic on a duplicate name under -count>1.
		metrics:     nil,
		dispatchSem: make(chan struct{}, dispatchConcurrency),
		receiptSem:  make(chan struct{}, receiptConcurrency),
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { defer close(done); _ = d.Run(ctx) }()
	stop := func() { cancel(); <-done }

	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		counts, err := raw.PubSubNumSub(context.Background(), channelChatMessageNew).Result()
		if err != nil {
			stop()
			t.Fatalf("pubsub numsub: %v", err)
		}
		if counts[channelChatMessageNew] >= 1 {
			return stop
		}
		time.Sleep(20 * time.Millisecond)
	}
	stop()
	t.Fatal("dispatcher did not subscribe to chat.message.new within 10s")
	return func() {}
}

// djangoChatPublish builds the exact envelope publish_after_commit emits:
// {event_id, ts, targets, **payload} as compact JSON.
func djangoChatPublish(t *testing.T, eventID string, targets []int64, body string) []byte {
	t.Helper()
	raw, err := json.Marshal(map[string]any{
		"event_id":   eventID,
		"ts":         time.Now().UTC().Format(time.RFC3339Nano),
		"targets":    targets,
		"message_id": 501,
		"match_id":   77,
		"sender_id":  1,
		"body":       body,
	})
	if err != nil {
		t.Fatalf("marshal publish: %v", err)
	}
	return raw
}

// readEnvelope reads one envelope, returning false on timeout so a test can
// assert that nothing arrives.
func readEnvelope(t *testing.T, ws *websocket.Conn, timeout time.Duration) (wsproto.Envelope, bool) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	var env wsproto.Envelope
	if err := wsjson.Read(ctx, ws, &env); err != nil {
		return wsproto.Envelope{}, false
	}
	return env, true
}

// TestChatRelayDeliversToTargetedSocket is the end-to-end path: Django
// publishes, the dispatcher fans out over the real Hub, and the targeted
// user's real WebSocket receives the payload intact. It also asserts the
// per-user delivered marker, which is what stops a duplicate FCM push.
func TestChatRelayDeliversToTargetedSocket(t *testing.T) {
	rdb, raw := itRedis(t)
	hub := NewHub()
	srv := itServer(t, hub)

	const recipient = int64(2)
	ws := itDial(t, srv, recipient)

	// The handler registers the conn with the Hub asynchronously after the
	// upgrade; wait for it so the publish cannot race registration.
	waitUntil(t, "the recipient's socket to register with the hub", func() bool {
		return hub.Send(recipient, wsproto.Envelope{Type: "it.probe", EventID: "probe"}) == 1
	})
	// Drain the probe so it is not mistaken for the message under test.
	if _, ok := readEnvelope(t, ws, 5*time.Second); !ok {
		t.Fatal("did not receive the hub registration probe")
	}

	receipts := &itReceipts{rdb: rdb}
	stop := runDispatcher(t, rdb, raw, hub, receipts)
	defer stop()

	eventID := fmt.Sprintf("it-chat-%d", time.Now().UnixNano())
	const body = "hey, is my parcel on the way?"
	if err := rdb.Publish(context.Background(), channelChatMessageNew,
		djangoChatPublish(t, eventID, []int64{recipient}, body)); err != nil {
		t.Fatalf("publish: %v", err)
	}

	env, ok := readEnvelope(t, ws, 15*time.Second)
	if !ok {
		t.Fatal("targeted socket never received chat.message.new")
	}
	if env.Type != channelChatMessageNew {
		t.Fatalf("envelope type = %q, want %q", env.Type, channelChatMessageNew)
	}
	if env.EventID != eventID {
		t.Fatalf("envelope event_id = %q, want %q", env.EventID, eventID)
	}

	// The raw Django payload must reach the client untouched — mobile parses
	// match_id/sender_id/body out of it.
	var payload map[string]any
	if err := json.Unmarshal(env.Payload, &payload); err != nil {
		t.Fatalf("payload is not valid json: %v", err)
	}
	if payload["body"] != body {
		t.Fatalf("payload body = %v, want %q", payload["body"], body)
	}
	if fmt.Sprint(payload["match_id"]) != "77" {
		t.Fatalf("payload match_id = %v, want 77", payload["match_id"])
	}

	// G1: the marker the FCM consumer checks before falling back to push.
	waitUntil(t, "the delivered marker to be written", func() bool {
		return receipts.seen(eventID)
	})
	exists, err := rdb.Exists(context.Background(), fmt.Sprintf("delivered:%s:%d", eventID, recipient))
	if err != nil {
		t.Fatalf("exists: %v", err)
	}
	if !exists {
		t.Fatal("per-user delivered marker was not set; FCM would send a duplicate push")
	}
}

// TestChatRelayDoesNotLeakToUntargetedSocket guards the routing rule that
// actually matters for privacy: a message addressed to someone else must
// never reach this user's socket.
func TestChatRelayDoesNotLeakToUntargetedSocket(t *testing.T) {
	rdb, raw := itRedis(t)
	hub := NewHub()
	srv := itServer(t, hub)

	const listener = int64(2)
	const otherUser = int64(999)
	ws := itDial(t, srv, listener)

	waitUntil(t, "the listener's socket to register with the hub", func() bool {
		return hub.Send(listener, wsproto.Envelope{Type: "it.probe", EventID: "probe"}) == 1
	})
	if _, ok := readEnvelope(t, ws, 5*time.Second); !ok {
		t.Fatal("did not receive the hub registration probe")
	}

	receipts := &itReceipts{rdb: rdb}
	stop := runDispatcher(t, rdb, raw, hub, receipts)
	defer stop()

	eventID := fmt.Sprintf("it-chat-leak-%d", time.Now().UnixNano())
	if err := rdb.Publish(context.Background(), channelChatMessageNew,
		djangoChatPublish(t, eventID, []int64{otherUser}, "should not be readable")); err != nil {
		t.Fatalf("publish: %v", err)
	}

	if env, ok := readEnvelope(t, ws, 3*time.Second); ok {
		t.Fatalf("listener received a message targeted at user %d: %+v", otherUser, env)
	}
	// With no local socket for the target there is no delivery, so there must
	// be no receipt either — otherwise the FCM fallback would be suppressed
	// for a message that was never actually delivered.
	if receipts.seen(eventID) {
		t.Fatal("receipt written for an undelivered message; FCM fallback would be wrongly suppressed")
	}
}

func waitUntil(t *testing.T, what string, pred func() bool) {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		if pred() {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("timed out after 10s waiting for %s", what)
}
