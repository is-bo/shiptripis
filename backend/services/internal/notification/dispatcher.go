package notification

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

// DeliveredTTL is the lifetime of the delivered:<event_id> marker that
// the WS-owning pod writes once a message has actually been queued to a
// socket. The FCM consumer reads this to decide whether to skip the
// push fallback. 60s per CLAUDE.md §2 G1.
const DeliveredTTL = 60 * time.Second

// markDeliveredTimeout caps the detached write that closes a delivery
// receipt. Detached so shutdown doesn't abort an in-flight receipt — a
// truncated UPDATE here would surface as a phantom undelivered row in
// the G6b sweep.
const markDeliveredTimeout = 5 * time.Second

// receiptConcurrency bounds in-flight markDelivered goroutines per pod.
// Each holds at most one Redis SET + one Postgres UPDATE; 64 is more
// than the steady-state of any reasonable pub/sub burst and keeps a
// slow Postgres from spawning goroutines without limit.
const receiptConcurrency = 64

// dispatchConcurrency bounds in-flight dispatch goroutines. The pub/sub
// pump produces messages faster than a single goroutine fanning to
// multiple hub.Send + receipt-schedule can drain under reconnect-storm
// load — without this pool the pump's 1024 buffer fills and pubsub
// drops start. 128 covers a burst where every connected user has a
// notification in flight; capped so a misbehaving handler can't fork
// goroutines without bound.
const dispatchConcurrency = 128

// setEXRetryDelay is the gap before retrying a failed delivered:<event_id>
// write. One brief retry is enough to ride a Redis blip without letting
// the FCM consumer see a stale EXISTS=0 and push a duplicate.
const setEXRetryDelay = 100 * time.Millisecond

// Channels this service subscribes to. Source of truth is
// monolith/apps/core/channels.py — keep these strings in lockstep.
//
// Every Django publish flows through `redis_bus.publish_after_commit`,
// which enriches the payload with `event_id`, `ts`, and `targets:[uid,...]`.
// The dispatcher unmarshals only that envelope and fans the raw payload
// to each target's local WS sockets — payload semantics (match_id,
// offer_id, code, etc.) are mobile's concern, not Go's.
var subscribeChannels = []string{
	// trips
	"trip.created",
	"trip.updated",
	"trip.cancelled",
	// parcels
	"parcel.created",
	"parcel.cancelled",
	// matching
	"match.created",
	"match.in_transit",
	"match.completed",
	"offer.created",
	"offer.updated",
	"offer.accepted",
	// payments
	"payment.captured",
	"payment.refunded",
	// verification
	"handover.confirmed",
	"handover.code_issued",
	// kyc
	"kyc.status_changed",
}

// targetsEnvelope is the shared shape every Django publish carries.
// We deliberately keep this minimal — the rest of the payload is
// forwarded raw to the client.
type targetsEnvelope struct {
	EventID string  `json:"event_id"`
	Targets []int64 `json:"targets"`
}

// Dispatcher consumes Redis pub/sub events, fans them to local WS
// sockets via the Hub, and writes G1 delivery receipts.
type Dispatcher struct {
	rdb     *redisbus.Client
	pool    *pgxpool.Pool
	hub     *Hub
	log     *slog.Logger
	metrics *metrics.Group

	// dispatchSem bounds in-flight per-message goroutines so the pub/sub
	// pump never blocks on a slow hub.Send or receipt schedule. dispatchWG
	// tracks them so Run drains at shutdown — letting a goroutine outlive
	// Run would mean Send on a closed Hub or write to a closed Postgres.
	dispatchSem chan struct{}
	dispatchWG  sync.WaitGroup

	// receiptSem bounds in-flight markDelivered goroutines. receiptWG
	// tracks them so Run waits at shutdown — a half-finished UPDATE on
	// core_published_event would look like a missed delivery to the G6b
	// audit sweep.
	receiptSem chan struct{}
	receiptWG  sync.WaitGroup
}

func NewDispatcher(rdb *redisbus.Client, pool *pgxpool.Pool, hub *Hub, log *slog.Logger, m *metrics.Group) *Dispatcher {
	if log == nil {
		log = slog.Default()
	}
	return &Dispatcher{
		rdb:         rdb,
		pool:        pool,
		hub:         hub,
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
	sub, err := d.rdb.Subscribe(ctx, subscribeChannels...)
	if err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}
	defer func() { _ = sub.Close() }()
	// dispatchWG must drain before receiptWG — a still-running dispatch
	// goroutine could schedule another receipt after we'd already waited
	// on the receipt pool.
	defer d.receiptWG.Wait()
	defer d.dispatchWG.Wait()

	d.log.Info("dispatcher subscribed", "channels", subscribeChannels)

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
// pool. Saturation drops the message — pub/sub is best-effort and the
// next pod (also subscribed) will deliver if it has a free slot. The
// drop is logged with event_id so G6b can attribute the loss.
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
		var env targetsEnvelope
		_ = json.Unmarshal(msg.Payload, &env)
		d.log.Warn("dispatcher: pool saturated; dropping",
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
	var env targetsEnvelope
	if err := json.Unmarshal(msg.Payload, &env); err != nil {
		d.log.Error("dispatcher: bad envelope", "channel", msg.Channel, "err", err)
		return
	}
	if env.EventID == "" {
		d.log.Error("dispatcher: missing event_id", "channel", msg.Channel)
		return
	}
	if len(env.Targets) == 0 {
		// Django built the publish without targets. We don't speculate on
		// legacy keys here — once the publisher migrates everything to
		// targets=[...] this branch goes away. Log so misses are visible.
		d.log.Warn("dispatcher: no targets", "channel", msg.Channel, "event_id", env.EventID)
		return
	}

	wsEnv := wsproto.Envelope{
		EventID: env.EventID,
		Type:    msg.Channel,
		Payload: msg.Payload,
	}

	var sockets int
	for _, uid := range env.Targets {
		if uid == 0 {
			continue
		}
		sockets += d.hub.Send(uid, wsEnv)
	}
	if sockets == 0 {
		// All targets are on other pods or offline. Either another pod
		// (also subscribed) owns the receipt, or FCM fallback will fire.
		d.log.Debug("dispatcher: no local recipients",
			"channel", msg.Channel,
			"event_id", env.EventID,
			"targets", len(env.Targets),
		)
		return
	}

	d.scheduleReceipt(env.EventID, sockets)
}

// scheduleReceipt fires markDelivered through the bounded worker pool.
// Dropping the receipt on a full pool is preferable to growing goroutines
// without bound — the G6b audit sweep will flag the event next run, and
// pub/sub fan-out has already happened.
func (d *Dispatcher) scheduleReceipt(eventID string, sockets int) {
	select {
	case d.receiptSem <- struct{}{}:
	default:
		if d.metrics != nil {
			d.metrics.Counter("receipt_drops_total", 1)
		}
		d.log.Warn("dispatcher: receipt pool saturated; dropping",
			"event_id", eventID, "sockets", sockets,
			"capacity", receiptConcurrency)
		return
	}
	d.receiptWG.Go(func() {
		defer func() { <-d.receiptSem }()
		d.markDelivered(eventID, sockets)
	})
}

// markDelivered performs the G1 two-step:
//  1. SET delivered:<event_id> 1 EX 60 — signals the FCM consumer to skip
//  2. UPDATE core_published_event SET delivered_at = now() WHERE event_id = $1
//     AND delivered_at IS NULL — closes the G6b detection-only audit row.
//
// Always invoked through the bounded pool so a slow Redis or Postgres
// can't stall the pub/sub loop and back up other channels. The detached,
// bounded context further insulates the receipt write from shutdown —
// the G6b sweep would otherwise flag an event that was actually delivered.
//
// Rows-affected = 0 on the second pod fanning the same event (the first
// pod's UPDATE already filled delivered_at). That's the intended outcome
// and not worth logging.
func (d *Dispatcher) markDelivered(eventID string, sockets int) {
	ctx, cancel := context.WithTimeout(context.Background(), markDeliveredTimeout)
	defer cancel()

	// One retry on SetEX failure. The FCM consumer reads EXISTS
	// delivered:<event_id> after a 2s grace period; if our key is missing
	// it will push a duplicate. A brief retry rides the typical Redis
	// blip without delaying the receipt update.
	key := "delivered:" + eventID
	if err := d.rdb.SetEX(ctx, key, "1", DeliveredTTL); err != nil {
		if d.metrics != nil {
			d.metrics.Counter("delivered_setex_failures_total", 1)
		}
		d.log.Warn("delivered key set failed (retrying)",
			"event_id", eventID, "err", err)
		select {
		case <-ctx.Done():
			return
		case <-time.After(setEXRetryDelay):
		}
		if err := d.rdb.SetEX(ctx, key, "1", DeliveredTTL); err != nil {
			if d.metrics != nil {
				d.metrics.Counter("delivered_setex_failures_final_total", 1)
			}
			d.log.Error("delivered key set failed after retry; FCM may duplicate",
				"event_id", eventID, "err", err)
		}
	}

	if _, err := d.pool.Exec(ctx,
		`UPDATE core_published_event
		    SET delivered_at = now()
		  WHERE event_id = $1
		    AND delivered_at IS NULL`,
		eventID,
	); err != nil {
		if d.metrics != nil {
			d.metrics.Counter("receipt_update_failures_total", 1)
		}
		d.log.Warn("published_event update failed", "event_id", eventID, "err", err)
		return
	}
	if d.metrics != nil {
		d.metrics.Counter("events_delivered_total", 1)
	}
	d.log.Debug("event delivered", "event_id", eventID, "sockets", sockets)
}
