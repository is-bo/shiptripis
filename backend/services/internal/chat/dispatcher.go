package chat

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"shiptrip/pkg/metrics"
	"shiptrip/pkg/redisbus"
	"shiptrip/pkg/wsproto"
)

// DeliveredTTL is the lifetime of the delivered:<event_id>:<user_id> marker that
// the WS-owning pod writes once a chat message has been queued to a
// socket. The FCM consumer reads this to decide whether to skip the push
// fallback. 60s per CLAUDE.md §2 G1 — matches notification's value so a
// user receiving via either service has the same FCM skip semantics.
const DeliveredTTL = 60 * time.Second

// markDeliveredTimeout caps the detached write that closes a delivery
// receipt. Detached so shutdown mid-fanout doesn't abandon the receipt
// write — the G6b sweep would otherwise flag an event that was actually
// delivered.
const markDeliveredTimeout = 5 * time.Second

// receiptConcurrency bounds in-flight markDelivered goroutines per pod.
// Chat fan-out is rare in V1 but burst-prone (a group chat reaction-storm
// would publish dozens per second); 64 keeps the goroutine count flat
// while leaving Postgres headroom inside the §3 pool budget.
const receiptConcurrency = 64

// dispatchConcurrency bounds in-flight dispatch goroutines. Same
// rationale as notification: the pump's 1024 buffer covers transient
// bursts, the pool covers sustained load. 128 is enough for any plausible
// chat burst (group reactions, mass message-send after reconnect) on a
// per-pod basis.
const dispatchConcurrency = 128

// setEXRetryDelay matches notification's retry — one brief retry before
// giving up so a Redis blip doesn't cause an FCM duplicate.
const setEXRetryDelay = 100 * time.Millisecond

// Channels this service subscribes to. Kept narrow on purpose — chat is a
// stateless relay for chat.message.new only (Django owns persistence).
const (
	channelChatMessageNew = "chat.message.new"
)

// targetsEnvelope is the shared shape every Django publish carries via
// redis_bus.publish_after_commit. The dispatcher unmarshals only this
// minimal envelope and fans the raw payload to each target's local
// sockets — payload semantics (message_id, thread_id, body) are the
// mobile client's concern, not Go's. Mirrors notification's routing so
// both services read the one canonical contract (CLAUDE.md §0a).
type targetsEnvelope struct {
	EventID string  `json:"event_id"`
	Ts      string  `json:"ts"`
	Targets []int64 `json:"targets"`
}

// router is the minimal surface the dispatcher needs from the Hub, so
// tests can pass a stub without spinning real WS sockets. Production
// callers pass *Hub; tests pass a recorder.
type router interface {
	Send(userID int64, env wsproto.Envelope) int
}

// receiptStore is the minimal surface the dispatcher needs to close a
// delivery receipt. Production callers pass a real receiptStore backed
// by Redis + Postgres; tests pass a recorder.
type receiptStore interface {
	MarkDelivered(ctx context.Context, eventID string, userID int64) error
}

// Dispatcher consumes Redis pub/sub events, fans them to local WS
// sockets via the Hub, and writes G1 delivery receipts.
type Dispatcher struct {
	rdb      *redisbus.Client
	hub      router
	receipts receiptStore
	log      *slog.Logger
	metrics  *metrics.Group

	// dispatchSem + dispatchWG bound and track per-message goroutines so
	// the pump never blocks on a slow hub.Send or receipt schedule.
	dispatchSem chan struct{}
	dispatchWG  sync.WaitGroup

	// receiptSem bounds in-flight markDelivered goroutines; receiptWG
	// tracks them so Run waits at shutdown — a half-finished UPDATE on
	// core_published_event would look like a missed delivery to G6b.
	receiptSem chan struct{}
	receiptWG  sync.WaitGroup
}

// NewDispatcher wires the production dispatcher against the real Hub
// and the Redis+Postgres receipt store. Tests construct a Dispatcher
// directly via the unexported newDispatcher to inject stubs.
func NewDispatcher(rdb *redisbus.Client, pool *pgxpool.Pool, hub *Hub, log *slog.Logger, m *metrics.Group) *Dispatcher {
	if log == nil {
		log = slog.Default()
	}
	return &Dispatcher{
		rdb:         rdb,
		hub:         hub,
		receipts:    newDBReceiptStore(rdb, pool, log, m),
		log:         log,
		metrics:     m,
		dispatchSem: make(chan struct{}, dispatchConcurrency),
		receiptSem:  make(chan struct{}, receiptConcurrency),
	}
}

// Run subscribes and pumps messages until ctx is cancelled. Blocks.
// Caller (main.go) should run this in its own goroutine and Close the
// returned subscription on shutdown.
func (d *Dispatcher) Run(ctx context.Context) error {
	channels := []string{channelChatMessageNew}
	sub, err := d.rdb.Subscribe(ctx, channels...)
	if err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}
	defer func() { _ = sub.Close() }()
	// dispatchWG must drain before receiptWG — a still-running dispatch
	// goroutine could schedule another receipt after we'd already waited
	// on the receipt pool.
	defer d.receiptWG.Wait()
	defer d.dispatchWG.Wait()

	d.log.Info("chat dispatcher subscribed", "channels", channels)

	for {
		select {
		case <-ctx.Done():
			return nil
		case msg, ok := <-sub.Channel():
			if !ok {
				return errors.New("subscription closed unexpectedly")
			}
			d.scheduleDispatch(ctx, msg)
		}
	}
}

// scheduleDispatch fans a single message through the dispatch worker
// pool. Saturation drops the message and logs the event_id so G6b can
// attribute the loss — pub/sub is best-effort and the next pod (also
// subscribed) will deliver if it has a free slot.
func (d *Dispatcher) scheduleDispatch(ctx context.Context, msg redisbus.Message) {
	select {
	case d.dispatchSem <- struct{}{}:
	case <-ctx.Done():
		return
	default:
		if d.metrics != nil {
			d.metrics.Counter("dispatch_drops_total", 1)
		}
		// Extract event_id only on the drop path so the steady-state
		// dispatch doesn't pay the unmarshal twice.
		var env struct {
			EventID string `json:"event_id"`
		}
		_ = json.Unmarshal(msg.Payload, &env)
		d.log.Warn("chat dispatcher: pool saturated; dropping",
			"channel", msg.Channel, "event_id", env.EventID,
			"capacity", dispatchConcurrency)
		return
	}
	d.dispatchWG.Go(func() {
		defer func() { <-d.dispatchSem }()
		d.dispatch(msg)
	})
}

func (d *Dispatcher) dispatch(msg redisbus.Message) {
	switch msg.Channel {
	case channelChatMessageNew:
		d.dispatchChatMessageNew(msg.Channel, msg.Payload)
	default:
		// Unreachable: we control the subscribe list. Logged just in case
		// go-redis ever surfaces a misrouted message.
		d.log.Warn("chat dispatcher: unknown channel", "channel", msg.Channel)
	}
}

// dispatchChatMessageNew fans the raw chat.message.new payload to every
// target's local sockets, identically to notification's generic path. The
// recipient is whoever Django listed in targets:[uid,...] — for a 1:1
// thread J1 includes sender and recipient; the relay never inspects message_id /
// thread_id / body (the client does).
func (d *Dispatcher) dispatchChatMessageNew(channel string, raw []byte) {
	var env targetsEnvelope
	if err := json.Unmarshal(raw, &env); err != nil {
		d.log.Error("chat.message.new: bad payload", "err", err)
		return
	}
	if env.EventID == "" {
		d.log.Error("chat.message.new: missing event_id")
		return
	}
	if len(env.Targets) == 0 {
		// Django built the publish without targets — every
		// publish_after_commit call passes targets=[...], so an empty set
		// is a publisher bug. Log so the miss is visible (mirrors notification).
		d.log.Warn("chat.message.new: no targets", "event_id", env.EventID)
		return
	}

	wsEnv := wsproto.Envelope{
		EventID: env.EventID,
		Ts:      env.Ts,
		Type:    channel,
		Payload: raw,
	}

	var sockets int
	for _, uid := range env.Targets {
		if uid == 0 {
			continue
		}
		userSockets := d.hub.Send(uid, wsEnv)
		sockets += userSockets
		if userSockets > 0 {
			d.scheduleReceipt(env.EventID, uid, userSockets)
		}
	}
	if sockets == 0 {
		d.log.Debug("chat.message.new: no local recipient",
			"event_id", env.EventID,
			"targets", len(env.Targets),
		)
		return
	}

}

// scheduleReceipt fires markDelivered through the bounded worker pool.
// Dropping the receipt on a full pool is preferable to growing goroutines
// without bound — G6b will flag the event next sweep and the WS fan-out
// has already happened.
func (d *Dispatcher) scheduleReceipt(eventID string, userID int64, sockets int) {
	select {
	case d.receiptSem <- struct{}{}:
	default:
		if d.metrics != nil {
			d.metrics.Counter("receipt_drops_total", 1)
		}
		d.log.Warn("chat dispatcher: receipt pool saturated; dropping",
			"event_id", eventID, "user_id", userID, "sockets", sockets,
			"capacity", receiptConcurrency)
		return
	}
	d.receiptWG.Go(func() {
		defer func() { <-d.receiptSem }()
		d.markDelivered(eventID, userID, sockets)
	})
}

func (d *Dispatcher) markDelivered(eventID string, userID int64, sockets int) {
	ctx, cancel := context.WithTimeout(context.Background(), markDeliveredTimeout)
	defer cancel()
	if err := d.receipts.MarkDelivered(ctx, eventID, userID); err != nil {
		d.log.Warn("chat: mark delivered failed", "event_id", eventID, "user_id", userID, "err", err)
		return
	}
	if d.metrics != nil {
		d.metrics.Counter("events_delivered_total", 1)
	}
	d.log.Debug("chat.message.new delivered", "event_id", eventID, "user_id", userID, "sockets", sockets)
}

// dbReceiptStore is the production receiptStore: SET delivered:<id>:<user_id> EX
// 60 + UPDATE core_published_event. Mirrors notification's path so the
// G6b sweep treats either service's delivery identically.
//
// keyExpirer + receiptExecer are micro-seams over the Redis SETEX and the
// Postgres UPDATE so a test can fail the first SETEX and assert the retry
// + its counters (same pattern as notification's dbReceiptStore).
type dbReceiptStore struct {
	rdb     keyExpirer
	exec    receiptExecer
	log     *slog.Logger
	metrics *metrics.Group
}

// keyExpirer is the SETEX surface (satisfied by *redisbus.Client).
type keyExpirer interface {
	SetEX(ctx context.Context, key string, value any, ttl time.Duration) error
}

// receiptExecer runs the delivered_at UPDATE (returns only error; 0
// rows-affected is a valid second-pod case, not acted on).
type receiptExecer interface {
	exec(ctx context.Context, eventID string) error
}

type poolExecer struct{ pool *pgxpool.Pool }

func (p poolExecer) exec(ctx context.Context, eventID string) error {
	_, err := p.pool.Exec(ctx,
		`UPDATE core_published_event
		    SET delivered_at = now()
		  WHERE event_id = $1
		    AND delivered_at IS NULL`,
		eventID,
	)
	return err
}

func newDBReceiptStore(rdb *redisbus.Client, pool *pgxpool.Pool, log *slog.Logger, m *metrics.Group) *dbReceiptStore {
	return &dbReceiptStore{rdb: rdb, exec: poolExecer{pool: pool}, log: log, metrics: m}
}

func (s *dbReceiptStore) MarkDelivered(ctx context.Context, eventID string, userID int64) error {
	key := fmt.Sprintf("delivered:%s:%d", eventID, userID)
	if err := s.rdb.SetEX(ctx, key, "1", DeliveredTTL); err != nil {
		if s.metrics != nil {
			s.metrics.Counter("delivered_setex_failures_total", 1)
		}
		s.log.Warn("delivered key set failed (retrying)",
			"event_id", eventID, "user_id", userID, "err", err)
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(setEXRetryDelay):
		}
		if err := s.rdb.SetEX(ctx, key, "1", DeliveredTTL); err != nil {
			if s.metrics != nil {
				s.metrics.Counter("delivered_setex_failures_final_total", 1)
			}
			s.log.Error("delivered key set failed after retry; FCM may duplicate",
				"event_id", eventID, "user_id", userID, "err", err)
		}
	}
	err := s.exec.exec(ctx, eventID)
	if err != nil && s.metrics != nil {
		s.metrics.Counter("receipt_update_failures_total", 1)
	}
	return err
}
