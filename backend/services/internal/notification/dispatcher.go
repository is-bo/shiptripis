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
	rdb  *redisbus.Client
	pool *pgxpool.Pool
	hub  *Hub
	log  *slog.Logger

	// receiptSem bounds in-flight markDelivered goroutines. receiptWG
	// tracks them so Run waits at shutdown — a half-finished UPDATE on
	// core_published_event would look like a missed delivery to the G6b
	// audit sweep.
	receiptSem chan struct{}
	receiptWG  sync.WaitGroup
}

func NewDispatcher(rdb *redisbus.Client, pool *pgxpool.Pool, hub *Hub, log *slog.Logger) *Dispatcher {
	if log == nil {
		log = slog.Default()
	}
	return &Dispatcher{
		rdb:        rdb,
		pool:       pool,
		hub:        hub,
		log:        log,
		receiptSem: make(chan struct{}, receiptConcurrency),
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
	defer d.receiptWG.Wait()

	d.log.Info("dispatcher subscribed", "channels", subscribeChannels)

	for {
		select {
		case <-ctx.Done():
			return nil
		case msg, ok := <-sub.Channel():
			if !ok {
				return errors.New("subscription closed unexpectedly")
			}
			d.dispatch(msg)
		}
	}
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

	if err := d.rdb.SetEX(ctx, "delivered:"+eventID, "1", DeliveredTTL); err != nil {
		d.log.Warn("delivered key set failed", "event_id", eventID, "err", err)
	}

	if _, err := d.pool.Exec(ctx,
		`UPDATE core_published_event
		    SET delivered_at = now()
		  WHERE event_id = $1
		    AND delivered_at IS NULL`,
		eventID,
	); err != nil {
		d.log.Warn("published_event update failed", "event_id", eventID, "err", err)
		return
	}
	d.log.Debug("event delivered", "event_id", eventID, "sockets", sockets)
}
