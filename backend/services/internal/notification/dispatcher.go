package notification

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
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

// Channels this service subscribes to.
//
// V1 scope: only offer.accepted with hardcoded {sender_id, traveler_id}
// routing. When Islam confirms the multi-channel routing strategy (likely
// Django adding `targets:[user_id,...]` to every payload), this list
// grows and routing moves out of the per-channel switch in Dispatch.
const (
	channelOfferAccepted = "offer.accepted"
)

// Dispatcher consumes Redis pub/sub events, fans them to local WS
// sockets via the Hub, and writes G1 delivery receipts.
type Dispatcher struct {
	rdb  *redisbus.Client
	pool *pgxpool.Pool
	hub  *Hub
	log  *slog.Logger
}

func NewDispatcher(rdb *redisbus.Client, pool *pgxpool.Pool, hub *Hub, log *slog.Logger) *Dispatcher {
	if log == nil {
		log = slog.Default()
	}
	return &Dispatcher{rdb: rdb, pool: pool, hub: hub, log: log}
}

// Run subscribes and pumps messages until ctx is cancelled. Blocks.
// Caller (main.go) should run this in its own goroutine and Close the
// returned subscription on shutdown.
func (d *Dispatcher) Run(ctx context.Context) error {
	sub, err := d.rdb.Subscribe(ctx, channelOfferAccepted)
	if err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}
	defer func() { _ = sub.Close() }()

	d.log.Info("dispatcher subscribed", "channels", []string{channelOfferAccepted})

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

// offerAcceptedPayload mirrors apps/matching/views.py L441-L452.
// Django wraps every publish in {event_id, ts, ...payload}, so those
// two fields are always present alongside the channel-specific keys.
type offerAcceptedPayload struct {
	EventID    string `json:"event_id"`
	Ts         string `json:"ts"`
	MatchID    int64  `json:"match_id"`
	OfferID    int64  `json:"offer_id"`
	ParcelID   int64  `json:"parcel_id"`
	TripID     int64  `json:"trip_id"`
	SenderID   int64  `json:"sender_id"`
	TravelerID int64  `json:"traveler_id"`
	TotalDZD   int64  `json:"total_dzd"`
}

func (d *Dispatcher) dispatch(msg redisbus.Message) {
	switch msg.Channel {
	case channelOfferAccepted:
		d.dispatchOfferAccepted(msg.Payload)
	default:
		// Unreachable: we control the subscribe list. Logged just in case
		// go-redis ever surfaces a misrouted message.
		d.log.Warn("dispatcher: unknown channel", "channel", msg.Channel)
	}
}

func (d *Dispatcher) dispatchOfferAccepted(raw []byte) {
	var p offerAcceptedPayload
	if err := json.Unmarshal(raw, &p); err != nil {
		d.log.Error("offer.accepted: bad payload", "err", err)
		return
	}
	if p.EventID == "" {
		d.log.Error("offer.accepted: missing event_id")
		return
	}
	if p.SenderID == 0 || p.TravelerID == 0 {
		d.log.Error("offer.accepted: missing party id",
			"sender_id", p.SenderID,
			"traveler_id", p.TravelerID,
			"event_id", p.EventID,
		)
		return
	}

	env := wsproto.Envelope{
		EventID: p.EventID,
		Ts:      p.Ts,
		Type:    channelOfferAccepted,
		Payload: raw,
	}

	sockets := d.hub.Send(p.SenderID, env) + d.hub.Send(p.TravelerID, env)
	if sockets == 0 {
		// Neither party is on this pod. Either they're on another pod
		// (which is also subscribed and will deliver) or they're offline
		// (FCM fallback, V2). Either way this pod does not own the receipt.
		d.log.Debug("offer.accepted: no local recipients",
			"event_id", p.EventID,
			"sender_id", p.SenderID,
			"traveler_id", p.TravelerID,
		)
		return
	}

	d.markDelivered(p.EventID, sockets)
}

// markDelivered performs the G1 two-step:
//  1. SET delivered:<event_id> 1 EX 60 — signals the FCM consumer to skip
//  2. UPDATE core_published_event SET delivered_at = now() WHERE event_id = $1
//     AND delivered_at IS NULL — closes the G6b detection-only audit row.
//
// Uses a detached, bounded context so a shutdown mid-fanout doesn't
// abandon the receipt write — the G6b sweep would otherwise flag an
// event that was actually delivered.
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
	d.log.Debug("offer.accepted delivered", "event_id", eventID, "sockets", sockets)
}
