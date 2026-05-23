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
// socket. The FCM consumer (V2) reads this to decide whether to skip the
// push fallback. 60s is per CLAUDE.md §2 G1.
const DeliveredTTL = 60 * time.Second

// markDeliveredTimeout caps the detached write that closes a delivery
// receipt. Detached so shutdown doesn't abort an in-flight receipt — a
// truncated UPDATE here would surface as a phantom undelivered row in
// the G6b sweep.
const markDeliveredTimeout = 5 * time.Second

// receiptConcurrency bounds in-flight markDelivered goroutines per pod.
const receiptConcurrency = 64

// Channels this service subscribes to. The list is the contract with
// apps/core/channels.py — keep them aligned. Every payload carries
// `event_id`, `ts`, and `targets: [user_id, ...]` (apps/core/redis_bus.py
// enriches before publish), so a single typed wrapper handles them all.
var subscribedChannels = []string{
	"offer.created",
	"offer.accepted",
	"offer.updated",
	"match.created",
	"match.in_transit",
	"match.completed",
	"payment.captured",
	"payment.refunded",
	"handover.code_issued",
	"handover.confirmed",
	"parcel.created",
	"parcel.cancelled",
	"trip.created",
	"trip.updated",
	"trip.cancelled",
	"kyc.status_changed",
}

// envelopeHeader is the canonical wrapper Django writes via
// `apps.core.redis_bus.publish_after_commit`. Each payload also carries
// channel-specific fields, but routing only needs these three.
type envelopeHeader struct {
	EventID string  `json:"event_id"`
	Ts      string  `json:"ts"`
	Targets []int64 `json:"targets"`
}

// Dispatcher consumes Redis pub/sub events, fans them to local WS
// sockets via the Hub, and writes G1 delivery receipts.
type Dispatcher struct {
	rdb  *redisbus.Client
	pool *pgxpool.Pool
	hub  *Hub
	log  *slog.Logger

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
func (d *Dispatcher) Run(ctx context.Context) error {
	sub, err := d.rdb.Subscribe(ctx, subscribedChannels...)
	if err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}
	defer func() { _ = sub.Close() }()
	defer d.receiptWG.Wait()

	d.log.Info("dispatcher subscribed", "channels", subscribedChannels)

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

// dispatch unmarshals the envelope header, fans the raw payload to every
// `targets[]` user with a local socket on this pod, and schedules the G1
// delivery receipt if at least one socket received it. The raw bytes are
// passed through unmodified — mobile parses channel-specific fields from
// them — so adding a new channel server-side requires no Go change beyond
// the `subscribedChannels` list.
func (d *Dispatcher) dispatch(msg redisbus.Message) {
	var h envelopeHeader
	if err := json.Unmarshal(msg.Payload, &h); err != nil {
		d.log.Error("dispatch: bad envelope", "channel", msg.Channel, "err", err)
		return
	}
	if h.EventID == "" {
		d.log.Error("dispatch: missing event_id", "channel", msg.Channel)
		return
	}
	if len(h.Targets) == 0 {
		// A publish with no targets is a legit Django-side state event
		// nobody on mobile needs to react to (or a publisher bug). Log
		// at debug — alerting belongs in the G6b sweep, not here.
		d.log.Debug("dispatch: no targets",
			"channel", msg.Channel, "event_id", h.EventID)
		return
	}

	env := wsproto.Envelope{
		EventID: h.EventID,
		Ts:      h.Ts,
		Type:    msg.Channel,
		Payload: msg.Payload,
	}

	var sockets int
	for _, uid := range h.Targets {
		if uid == 0 {
			continue
		}
		sockets += d.hub.Send(uid, env)
	}
	if sockets == 0 {
		d.log.Debug("dispatch: no local recipients",
			"channel", msg.Channel,
			"event_id", h.EventID,
			"targets", h.Targets,
		)
		return
	}

	d.scheduleReceipt(h.EventID, sockets)
}

// markDelivered performs the G1 two-step:
//  1. SET delivered:<event_id> 1 EX 60 — signals the FCM consumer to skip
//  2. UPDATE core_published_event SET delivered_at = now() WHERE event_id = $1
//     AND delivered_at IS NULL — closes the G6b detection-only audit row.
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
	d.log.Debug("delivered", "event_id", eventID, "sockets", sockets)
}
