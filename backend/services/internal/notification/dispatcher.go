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
// Each holds at most one Redis SET + one Postgres UPDATE; 64 is more
// than the steady-state of any reasonable pub/sub burst and keeps a
// slow Postgres from spawning goroutines without limit.
const receiptConcurrency = 64

// Channels this service subscribes to.
//
// Per-channel typed structs (vs. a generic `targets:[user_id,...]` shape)
// stay readable while the set is small. If a fourth/fifth channel lands
// with identical routing, factor the unmarshal+route+receipt path into a
// generic handler then.
const (
	channelOfferAccepted = "offer.accepted"
	channelOfferCreated  = "offer.created"
)

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
	channels := []string{channelOfferAccepted, channelOfferCreated}
	sub, err := d.rdb.Subscribe(ctx, channels...)
	if err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}
	defer func() { _ = sub.Close() }()
	defer d.receiptWG.Wait()

	d.log.Info("dispatcher subscribed", "channels", channels)

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

// offerAcceptedPayload mirrors apps/matching/views.py L441-L452.
// Django wraps every publish in {event_id, ts, ...payload}; `ts` is
// re-derived by the client from message metadata so we don't unmarshal
// it server-side.
type offerAcceptedPayload struct {
	EventID    string `json:"event_id"`
	MatchID    int64  `json:"match_id"`
	OfferID    int64  `json:"offer_id"`
	ParcelID   int64  `json:"parcel_id"`
	TripID     int64  `json:"trip_id"`
	SenderID   int64  `json:"sender_id"`
	TravelerID int64  `json:"traveler_id"`
	TotalDZD   int64  `json:"total_dzd"`
}

// offerCreatedPayload mirrors apps/matching/views.py L233-L242 + L368-L379.
// Django picks the recipient (sender for traveler-proposed offers, traveler
// for sender-proposed counters) and sends it as a single `recipient_id`
// — no fan-out at this layer.
type offerCreatedPayload struct {
	EventID     string `json:"event_id"`
	MatchID     int64  `json:"match_id"`
	OfferID     int64  `json:"offer_id"`
	ProposedBy  string `json:"proposed_by"`
	TotalDZD    int64  `json:"total_dzd"`
	RecipientID int64  `json:"recipient_id"`
}

func (d *Dispatcher) dispatch(msg redisbus.Message) {
	switch msg.Channel {
	case channelOfferAccepted:
		d.dispatchOfferAccepted(msg.Payload)
	case channelOfferCreated:
		d.dispatchOfferCreated(msg.Payload)
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

	d.scheduleReceipt(p.EventID, sockets)
}

func (d *Dispatcher) dispatchOfferCreated(raw []byte) {
	var p offerCreatedPayload
	if err := json.Unmarshal(raw, &p); err != nil {
		d.log.Error("offer.created: bad payload", "err", err)
		return
	}
	if p.EventID == "" {
		d.log.Error("offer.created: missing event_id")
		return
	}
	if p.RecipientID == 0 {
		d.log.Error("offer.created: missing recipient_id", "event_id", p.EventID)
		return
	}

	env := wsproto.Envelope{
		EventID: p.EventID,
		Type:    channelOfferCreated,
		Payload: raw,
	}

	sockets := d.hub.Send(p.RecipientID, env)
	if sockets == 0 {
		d.log.Debug("offer.created: no local recipient",
			"event_id", p.EventID,
			"recipient_id", p.RecipientID,
		)
		return
	}

	d.scheduleReceipt(p.EventID, sockets)
}

// markDelivered performs the G1 two-step:
//  1. SET delivered:<event_id> 1 EX 60 — signals the FCM consumer to skip
//  2. UPDATE core_published_event SET delivered_at = now() WHERE event_id = $1
//     AND delivered_at IS NULL — closes the G6b detection-only audit row.
//
// Always invoked in its own goroutine so a slow Redis or Postgres can't
// stall the pub/sub loop and back up other channels. The detached,
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
	d.log.Debug("offer.accepted delivered", "event_id", eventID, "sockets", sockets)
}
