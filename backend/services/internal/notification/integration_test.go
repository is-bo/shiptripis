//go:build integration

// Integration tests for the notification service against a real Redis.
//
// These cover CLAUDE.md §2 G1 — the multi-pod presence + delivery-receipt
// protocol whose failure mode is a user receiving the same notification
// twice (once over WebSocket, once over FCM). That guarantee spans two
// components which only meet through Redis:
//
//	dispatcher (pub/sub -> WS send -> SET delivered:<event_id>:<user_id>)
//	consumer   (XReadGroup -> wait grace -> EXISTS delivered:<event_id>:<user_id>)
//
// Neither half can prove it alone. dispatcher_test.go stubs the receipt
// store, so it never writes the key the consumer reads; fcm_firebase_test.go
// stubs the multicaster, so it never reads the key the dispatcher writes.
// The handshake between them is only observable against a real Redis, and
// it is exactly where a duplicate push comes from.
//
// Run with a throwaway Redis:
//
//	docker run -d --name it-redis -p 6399:6379 redis:7-alpine
//	REDIS_TEST_URL=redis://localhost:6399/0 go test -tags integration ./internal/notification/
//
// Or via ./scripts/integration-test.sh, which manages the container.
//
// FCM is faked at the FCMSender seam (a live Firebase project is neither
// available in CI nor desirable — it would send real pushes). Postgres is
// stubbed at the receiptStore seam: the receipt SQL is a single UPDATE
// already covered by unit tests, and the half that matters to G1 is the
// Redis marker, which these tests write for real.
package notification

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

// itChannel is the channel used to drive the dispatcher. Any of the 16 in
// subscribeChannels would do — dispatch is generic over `targets` — so this
// picks a real one rather than inventing a name the service never subscribes
// to (which would silently deliver nothing and make the test vacuous).
const itChannel = "offer.created"

// ── infrastructure helpers ───────────────────────────────────────────────────

// itRedis dials the throwaway Redis, skipping when it is not configured so
// `go test -tags integration ./...` still runs without infra. An absent
// dependency must be a visible skip, never a silent pass.
//
// The raw client is returned alongside for read-only observation (XPENDING,
// PUBSUB NUMSUB, TTL) that redisbus does not expose.
func itRedis(t *testing.T) (*redisbus.Client, *redis.Client) {
	t.Helper()
	url := os.Getenv("REDIS_TEST_URL")
	if url == "" {
		t.Skip("REDIS_TEST_URL not set; skipping notification integration test")
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

// itEventID namespaces an event id per test *and* per run.
//
// This is load-bearing, not cosmetic. The consumer skips an event whose
// a per-user delivered key exists, and that key lives for DeliveredTTL
// (60s). A fixed id would make the second run of a test within a minute
// skip the push it is asserting on — a test that passes for the wrong
// reason, or hangs. itCleanupKeys removes the markers too.
func itEventID(t *testing.T, label string) string {
	t.Helper()
	return fmt.Sprintf("it-%s-%s-%d", t.Name(), label, time.Now().UnixNano())
}

// itStream returns a per-test stream key and removes the stream plus any
// `delivered:`/`presence:` keys this test created when it finishes.
func itStream(t *testing.T, raw *redis.Client) string {
	t.Helper()
	stream := fmt.Sprintf("test:notif:fcm:%s", t.Name())
	del := func() {
		ctx := context.Background()
		raw.Del(ctx, stream, stream+":results")
		if keys, err := raw.Keys(ctx, "delivered:it-"+t.Name()+"-*").Result(); err == nil && len(keys) > 0 {
			raw.Del(ctx, keys...)
		}
	}
	del()
	t.Cleanup(del)
	return stream
}

// itPendingCount reports how many entries sit unacked in the group's PEL.
//
// Deliberately a raw XPENDING rather than redisbus.XAutoClaim: XAUTOCLAIM
// *reassigns* ownership and resets each entry's idle timer, so polling with
// it would hold idle below the sweeper's MinIdle and starve the very reclaim
// path TestFCMSweeperRedeliversAfterSendFailure asserts. XPENDING is
// read-only — observing does not perturb what is observed.
func itPendingCount(t *testing.T, raw *redis.Client, stream, group string) int {
	t.Helper()
	n, err := raw.XPendingExt(context.Background(), &redis.XPendingExtArgs{
		Stream: stream,
		Group:  group,
		Start:  "-",
		End:    "+",
		Count:  100,
	}).Result()
	if err != nil {
		// Run creates the group asynchronously, so a probe can land before
		// the stream/group exists. That is "nothing pending yet", not a
		// failure — pollers see the real count once it appears.
		if strings.Contains(err.Error(), "NOGROUP") {
			return 0
		}
		t.Fatalf("xpending: %v", err)
	}
	return len(n)
}

// itEntriesRead reports how many entries the group has ever been delivered.
//
// This exists because "the PEL is empty" is ambiguous, and trusting it cost me
// a vacuous test. XPENDING counts only entries delivered-but-not-acked, so it
// reads 0 both *before* the consumer has read an entry and *after* it acks
// one. An assertion of "pending == 0, therefore no push happened" passed even
// with the delivered-marker write deliberately sabotaged, because it ran
// before the consumer had touched the stream at all.
//
// EntriesRead advances on delivery and never rewinds, so `EntriesRead >= n` is
// a genuine "the consumer has processed n entries" edge. Returns 0 while the
// group does not exist yet (Run creates it asynchronously).
func itEntriesRead(t *testing.T, raw *redis.Client, stream, group string) int64 {
	t.Helper()
	groups, err := raw.XInfoGroups(context.Background(), stream).Result()
	if err != nil {
		if strings.Contains(err.Error(), "no such key") || strings.Contains(err.Error(), "NOGROUP") {
			return 0
		}
		t.Fatalf("xinfo groups: %v", err)
	}
	for _, g := range groups {
		if g.Name == group {
			return g.EntriesRead
		}
	}
	return 0
}

// itWaitProcessed waits until the group has read at least n entries AND the
// PEL is empty — the consumer has genuinely handled and acked them. Both
// halves are needed: the first rules out "hasn't looked yet", the second
// rules out "read it but left it pending".
func itWaitProcessed(t *testing.T, raw *redis.Client, stream, group string, n int64, timeout time.Duration) {
	t.Helper()
	itWaitFor(t, fmt.Sprintf("the consumer to process and ack %d entr(y/ies)", n), timeout, func() bool {
		return itEntriesRead(t, raw, stream, group) >= n &&
			itPendingCount(t, raw, stream, group) == 0
	})
}

func itWaitFor(t *testing.T, what string, timeout time.Duration, pred func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if pred() {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("timed out after %s waiting for %s", timeout, what)
}

// ── WebSocket + dispatcher harness ───────────────────────────────────────────

// itToken mints an access token shaped like the one Django's SimpleJWT
// issues, so the upgrade exercises the real validator rather than a bypass.
func itToken(t *testing.T, userID int64) string {
	t.Helper()
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"user_id": userID,
		"role":    "sender",
		"typ":     "access",
		"jti":     fmt.Sprintf("it-jti-%d-%d", userID, time.Now().UnixNano()),
		"iat":     time.Now().Unix(),
		"exp":     time.Now().Add(10 * time.Minute).Unix(),
	})
	signed, err := tok.SignedString([]byte(itJWTSecret))
	if err != nil {
		t.Fatalf("sign token: %v", err)
	}
	return signed
}

// itServer starts a real HTTP server mounting the production WSHandler,
// including the real Presence writer so presence:<uid> lands in Redis.
func itServer(t *testing.T, hub *Hub, presence *Presence) *httptest.Server {
	t.Helper()
	validator, err := auth.NewValidator(itJWTSecret, discardLogger())
	if err != nil {
		t.Fatalf("new validator: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	var connWG sync.WaitGroup

	mux := http.NewServeMux()
	// nil metrics: every use in handler.go is nil-guarded, and
	// metrics.Register publishes into the process-global expvar registry,
	// which panics on a duplicate name under -count>1.
	mux.HandleFunc("/ws/notifications", WSHandler(ctx, validator, hub, presence, discardLogger(), nil, &connWG))
	srv := httptest.NewServer(mux)

	t.Cleanup(func() {
		srv.Close() // close sockets first so handlers observe EOF
		cancel()
		connWG.Wait()
	})
	return srv
}

func itDial(t *testing.T, srv *httptest.Server, userID int64) *websocket.Conn {
	t.Helper()
	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws/notifications"
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

// itReceipts stands in for Postgres while performing the half of the receipt
// that G1 actually depends on: writing a per-user delivered key to Redis. That
// key is what the FCM consumer reads to suppress a duplicate push, so it is
// written for real here; the core_published_event UPDATE is recorded only.
type itReceipts struct {
	mu  sync.Mutex
	ids []string
	rdb *redisbus.Client
}

func (r *itReceipts) MarkDelivered(ctx context.Context, eventID string, userID int64) error {
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

// itRunDispatcher wires a Dispatcher onto the real Redis subscription and the
// real Hub, then waits until Redis reports a subscriber on itChannel.
//
// The wait is what keeps this from flaking: Redis pub/sub has no backlog, so
// a PUBLISH issued before SUBSCRIBE lands is dropped silently and the test
// would hang waiting for a message that was never queued anywhere.
func itRunDispatcher(t *testing.T, rdb *redisbus.Client, raw *redis.Client, hub *Hub, receipts receiptStore) func() {
	t.Helper()
	d := &Dispatcher{
		rdb:         rdb,
		hub:         hub,
		receipts:    receipts,
		log:         discardLogger(),
		metrics:     nil, // see itServer for why
		dispatchSem: make(chan struct{}, dispatchConcurrency),
		receiptSem:  make(chan struct{}, receiptConcurrency),
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { defer close(done); _ = d.Run(ctx) }()
	stop := func() { cancel(); <-done }

	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		counts, err := raw.PubSubNumSub(context.Background(), itChannel).Result()
		if err != nil {
			stop()
			t.Fatalf("pubsub numsub: %v", err)
		}
		if counts[itChannel] >= 1 {
			return stop
		}
		time.Sleep(20 * time.Millisecond)
	}
	stop()
	t.Fatalf("dispatcher never subscribed to %s", itChannel)
	return nil
}

// itPublish sends the envelope shape redis_bus.publish_after_commit produces:
// a flat JSON object carrying event_id, ts, targets and the payload fields.
func itPublish(t *testing.T, rdb *redisbus.Client, eventID string, targets []int64, extra map[string]any) {
	t.Helper()
	env := map[string]any{
		"event_id": eventID,
		"ts":       time.Now().UTC().Format(time.RFC3339),
		"targets":  targets,
	}
	for k, v := range extra {
		env[k] = v
	}
	body, err := json.Marshal(env)
	if err != nil {
		t.Fatalf("marshal envelope: %v", err)
	}
	if err := rdb.Publish(context.Background(), itChannel, body); err != nil {
		t.Fatalf("publish: %v", err)
	}
}

// ── FCM consumer harness ─────────────────────────────────────────────────────

// itSender records pushes and can be told to fail, so a test can simulate an
// FCM outage and then a recovery.
type itSender struct {
	mu   sync.Mutex
	sent []FCMPayload
	fail bool
}

func (s *itSender) Send(_ context.Context, p FCMPayload) (SendResult, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.fail {
		return SendResult{}, fmt.Errorf("simulated fcm outage for %s", p.EventID)
	}
	s.sent = append(s.sent, p)
	return SendResult{
		SuccessfulDeviceIDs:         append([]int64(nil), p.DeviceIDs...),
		SuccessfulTokenFingerprints: append([]string(nil), p.TokenFingerprints...),
	}, nil
}

func (s *itSender) setFail(v bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.fail = v
}

func (s *itSender) count() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.sent)
}

func (s *itSender) last() (FCMPayload, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.sent) == 0 {
		return FCMPayload{}, false
	}
	return s.sent[len(s.sent)-1], true
}

// itRunConsumer starts Run (and optionally Sweep) and returns a stop func.
//
// The group is created here, before Run starts, rather than relying on Run's
// own XGroupCreate. Run creates it at "$" (new entries only), so a test that
// XADDs while that call is still in flight would enqueue *behind* the group's
// start position and hang forever. Creating it up front makes Run's call a
// no-op (idempotent via BUSYGROUP) and removes the race.
func itRunConsumer(t *testing.T, c *Consumer, withSweep bool) func() {
	t.Helper()
	if err := c.rdb.XGroupCreate(context.Background(), c.stream, c.group, "$"); err != nil {
		t.Fatalf("pre-create consumer group: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	var wg sync.WaitGroup
	wg.Add(1)
	go func() { defer wg.Done(); _ = c.Run(ctx) }()
	if withSweep {
		wg.Add(1)
		go func() { defer wg.Done(); _ = c.Sweep(ctx) }()
	}
	return func() { cancel(); wg.Wait() }
}

// itNewConsumer builds a Consumer with the grace period shortened. Production
// waits 2s (G1); the code path is identical at 300ms, and every test that
// depends on the grace window still has room to write the marker inside it.
func itNewConsumer(rdb *redisbus.Client, stream string, sender FCMSender) *Consumer {
	c := NewConsumer(rdb, ConsumerConfig{
		Stream:         stream,
		ConsumerGroup:  "it-workers",
		ConsumerName:   "it-1",
		FeedbackStream: stream + ":results",
		Sender:         sender,
	}, discardLogger())
	c.deliverGrace = 300 * time.Millisecond
	return c
}

// itFCMEntry builds the stream entry Django will XADD to notif:fcm: an
// `event_id` field for cheap filtering plus a compact-JSON `payload`.
func itFCMEntry(t *testing.T, eventID string, userID int64, tokens []string) map[string]any {
	t.Helper()
	payload, err := json.Marshal(FCMPayload{
		EventID: eventID,
		UserID:  userID,
		Tokens:  tokens,
		TokenFingerprints: func() []string {
			fingerprints := make([]string, len(tokens))
			for i := range tokens {
				fingerprints[i] = fmt.Sprintf("fingerprint-%d", i+1)
			}
			return fingerprints
		}(),
		DeviceIDs: func() []int64 {
			ids := make([]int64, len(tokens))
			for i := range tokens {
				ids[i] = int64(i + 1)
			}
			return ids
		}(),
		Title: "New offer",
		Body:  "A traveler made you an offer",
		Data:  map[string]string{"match_id": "77"},
	})
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	return map[string]any{"event_id": eventID, "user_id": userID, "payload": string(payload)}
}

// ── tests ────────────────────────────────────────────────────────────────────

// TestG1WSDeliverySuppressesFCMPush is the anti-duplicate-push guarantee, and
// the reason this file exists.
//
// The full loop runs for real: Django-shaped publish -> dispatcher -> live WS
// socket -> per-user delivered key in Redis, while the FCM consumer independently
// reads the same event from the stream, waits out its grace period, sees the
// marker and declines to push. If this breaks, every notification to an online
// user arrives twice.
func TestG1WSDeliverySuppressesFCMPush(t *testing.T) {
	rdb, raw := itRedis(t)
	stream := itStream(t, raw)
	const userID int64 = 4101

	hub := NewHub()
	presence := NewPresence(rdb, discardLogger())
	srv := itServer(t, hub, presence)
	ws := itDial(t, srv, userID)

	receipts := &itReceipts{rdb: rdb}
	stopDispatch := itRunDispatcher(t, rdb, raw, hub, receipts)
	defer stopDispatch()

	// The handler registers the socket with the Hub just after upgrade;
	// publishing before that would fan out to zero sockets.
	itWaitFor(t, "the socket to register with the hub", 5*time.Second, func() bool {
		return hub.Send(userID, wsproto.Envelope{Type: "it.probe"}) == 1
	})
	// Drain the probe so the assertion below reads the real event.
	readEnvelope(t, ws, 5*time.Second)

	sender := &itSender{}
	consumer := itNewConsumer(rdb, stream, sender)
	stopConsumer := itRunConsumer(t, consumer, false)
	defer stopConsumer()

	eventID := itEventID(t, "suppress")

	// Both halves of G1 see the same event, as they would in production:
	// Django publishes for WS fan-out and XADDs for the FCM fallback.
	itPublish(t, rdb, eventID, []int64{userID}, map[string]any{"match_id": 77})
	if _, err := rdb.XAddCapped(context.Background(), stream, 1000,
		itFCMEntry(t, eventID, userID, []string{"tok-online"}),
	); err != nil {
		t.Fatalf("xadd: %v", err)
	}

	// The WS delivery must land.
	got := readEnvelope(t, ws, 10*time.Second)
	if got["event_id"] != eventID {
		t.Fatalf("ws envelope event_id = %v, want %s", got["event_id"], eventID)
	}
	itWaitFor(t, "the delivered marker to be written", 10*time.Second, func() bool {
		return receipts.seen(eventID)
	})

	// The consumer must have read the entry, waited out its grace period,
	// found the marker, and acked — all before "0 pushes" means anything.
	// itWaitProcessed (not a bare PEL check) is what makes this assertion
	// real; see itEntriesRead for the vacuous version this replaced.
	itWaitProcessed(t, raw, stream, "it-workers", 1, 15*time.Second)
	if n := sender.count(); n != 0 {
		t.Fatalf("FCM pushed %d times despite WS delivery — this is the duplicate-notification bug G1 exists to prevent", n)
	}
}

// TestG1FCMPushesWhenNoWSSocket is the other half of the guarantee: when the
// user has no live socket, nothing writes a per-user delivered key and the push
// MUST happen. A test that only asserted suppression would pass against a
// consumer that never pushes at all.
func TestG1FCMPushesWhenNoWSSocket(t *testing.T) {
	rdb, raw := itRedis(t)
	stream := itStream(t, raw)
	const userID int64 = 4102

	sender := &itSender{}
	consumer := itNewConsumer(rdb, stream, sender)
	stopConsumer := itRunConsumer(t, consumer, false)
	defer stopConsumer()

	eventID := itEventID(t, "offline")
	if _, err := rdb.XAddCapped(context.Background(), stream, 1000,
		itFCMEntry(t, eventID, userID, []string{"tok-offline-a", "tok-offline-b"}),
	); err != nil {
		t.Fatalf("xadd: %v", err)
	}

	itWaitFor(t, "the fcm push to be sent", 10*time.Second, func() bool {
		return sender.count() == 1
	})
	got, _ := sender.last()
	if got.EventID != eventID || got.UserID != userID {
		t.Fatalf("pushed wrong event: %+v", got)
	}
	if len(got.Tokens) != 2 || got.Title != "New offer" {
		t.Fatalf("payload not carried through: %+v", got)
	}
	if got.Data["match_id"] != "77" {
		t.Fatalf("data payload lost: %+v", got.Data)
	}

	itWaitProcessed(t, raw, stream, "it-workers", 1, 10*time.Second)
}

// TestG1SweeperRedeliversAfterSendFailure covers the durability half of G1:
// a failed push must stay in the PEL and be reclaimed by XAUTOCLAIM, not
// acked away. Acking a failed send would silently swallow the notification.
func TestG1SweeperRedeliversAfterSendFailure(t *testing.T) {
	rdb, raw := itRedis(t)
	stream := itStream(t, raw)
	const userID int64 = 4103

	sender := &itSender{}
	sender.setFail(true) // FCM is down

	consumer := itNewConsumer(rdb, stream, sender)
	// Production sweeps every 30s over entries idle >60s (G1). Shrink both so
	// the reclaim path runs in milliseconds; the code under test is identical.
	consumer.sweepMinIdle = 50 * time.Millisecond
	consumer.sweepInterval = 100 * time.Millisecond

	stopConsumer := itRunConsumer(t, consumer, true)
	defer stopConsumer()

	eventID := itEventID(t, "retry")
	if _, err := rdb.XAddCapped(context.Background(), stream, 1000,
		itFCMEntry(t, eventID, userID, []string{"tok-retry"}),
	); err != nil {
		t.Fatalf("xadd: %v", err)
	}

	itWaitFor(t, "the failed entry to sit in the PEL", 10*time.Second, func() bool {
		return itPendingCount(t, raw, stream, "it-workers") == 1
	})
	if n := sender.count(); n != 0 {
		t.Fatalf("sender recorded %d successful pushes during the outage, want 0", n)
	}

	sender.setFail(false) // FCM recovers
	itWaitFor(t, "the sweeper to redeliver after recovery", 20*time.Second, func() bool {
		return sender.count() >= 1
	})
	itWaitProcessed(t, raw, stream, "it-workers", 1, 10*time.Second)

	got, _ := sender.last()
	if got.EventID != eventID {
		t.Fatalf("redelivered wrong entry: %+v", got)
	}
}

// TestG1ConsumerDropsUndeliverablePayloads: a permanently-bad entry must be
// acked away rather than retried forever. Left in the PEL it would be swept
// in a loop until the stream trimmed it, burning a slot on every pass.
func TestG1ConsumerDropsUndeliverablePayloads(t *testing.T) {
	rdb, raw := itRedis(t)
	stream := itStream(t, raw)

	sender := &itSender{}
	consumer := itNewConsumer(rdb, stream, sender)
	stopConsumer := itRunConsumer(t, consumer, false)
	defer stopConsumer()

	ctx := context.Background()
	// Malformed JSON; a valid envelope with no tokens (nobody to push to);
	// and an entry with no event_id at all.
	if _, err := rdb.XAddCapped(ctx, stream, 1000, map[string]any{
		"event_id": itEventID(t, "badjson"), "payload": "{not json",
	}); err != nil {
		t.Fatalf("xadd bad json: %v", err)
	}
	noTokens, _ := json.Marshal(FCMPayload{EventID: itEventID(t, "notokens"), UserID: 1, Title: "x"})
	if _, err := rdb.XAddCapped(ctx, stream, 1000, map[string]any{
		"event_id": itEventID(t, "notokens"), "payload": string(noTokens),
	}); err != nil {
		t.Fatalf("xadd no-tokens: %v", err)
	}
	if _, err := rdb.XAddCapped(ctx, stream, 1000, map[string]any{
		"payload": `{"title":"orphan"}`,
	}); err != nil {
		t.Fatalf("xadd no-event-id: %v", err)
	}

	itWaitProcessed(t, raw, stream, "it-workers", 3, 15*time.Second)
	if n := sender.count(); n != 0 {
		t.Fatalf("sender was called %d times for undeliverable payloads, want 0", n)
	}
}

// TestPresenceLifecycleOnRealRedis checks the presence half of G1 end-to-end:
// upgrading a socket writes presence:<uid> with a bounded TTL, the refresh
// loop keeps it alive, and closing the socket removes it.
//
// The TTL is read back from Redis rather than compared against the constant,
// because the bug this guards against is a SetEX passing the wrong duration —
// which an assertion on PresenceTTL itself could never catch.
//
// On which invariant to assert: presence.go's own doc comment claims the TTL
// "must be tighter than wsproto.PingInterval (10s)" while defining it as 15s,
// and CLAUDE.md carries the same contradiction (§G1 "TTL must be < WS ping
// interval" vs §5 "It's 15s"). Both cannot hold. The relationship that is
// actually load-bearing — and true — is refresh interval (5s) < TTL (15s):
// that is what stops a live socket's key from gapping and causing a spurious
// FCM push. This test asserts that, plus an upper bound so a crashed pod's
// stale presence still expires promptly. The doc contradiction is flagged for
// the humans rather than "fixed" by changing a load-bearing constant.
func TestPresenceLifecycleOnRealRedis(t *testing.T) {
	rdb, raw := itRedis(t)
	const userID int64 = 4104
	key := fmt.Sprintf("presence:%d", userID)
	t.Cleanup(func() { raw.Del(context.Background(), key) })

	hub := NewHub()
	presence := NewPresence(rdb, discardLogger())
	srv := itServer(t, hub, presence)
	ws := itDial(t, srv, userID)

	itWaitFor(t, "presence to be written on upgrade", 10*time.Second, func() bool {
		n, err := raw.Exists(context.Background(), key).Result()
		return err == nil && n == 1
	})

	ttl, err := raw.TTL(context.Background(), key).Result()
	if err != nil {
		t.Fatalf("ttl: %v", err)
	}
	if ttl <= 0 {
		t.Fatalf("presence key has no TTL (%v) — a leaked key masks a dropped socket forever, permanently suppressing the FCM fallback", ttl)
	}
	if ttl > PresenceTTL {
		t.Fatalf("presence TTL %v exceeds PresenceTTL %v — SetEX was passed the wrong duration", ttl, PresenceTTL)
	}
	if presenceRefreshInterval >= ttl {
		t.Fatalf("refresh interval %v >= presence TTL %v: a live socket's key would gap between refreshes and trigger a spurious FCM push",
			presenceRefreshInterval, ttl)
	}

	// The refresh loop must actually hold the key open. Watching it survive
	// past one refresh tick is the only way to catch a loop that never fires
	// (a broken ticker would still pass the TTL checks above).
	time.Sleep(presenceRefreshInterval + 500*time.Millisecond)
	refreshed, err := raw.TTL(context.Background(), key).Result()
	if err != nil {
		t.Fatalf("ttl after refresh: %v", err)
	}
	if refreshed <= 0 {
		t.Fatalf("presence key expired despite a live socket (ttl=%v) — the refresh loop is not running", refreshed)
	}

	// Closing the socket must drop presence, so the FCM fallback resumes.
	_ = ws.Close(websocket.StatusNormalClosure, "done")
	itWaitFor(t, "presence to be dropped on disconnect", 10*time.Second, func() bool {
		n, err := raw.Exists(context.Background(), key).Result()
		return err == nil && n == 0
	})
}

// readEnvelope reads one JSON message off the client socket.
func readEnvelope(t *testing.T, ws *websocket.Conn, timeout time.Duration) map[string]any {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	var got map[string]any
	if err := wsjson.Read(ctx, ws, &got); err != nil {
		t.Fatalf("read ws message: %v", err)
	}
	return got
}
