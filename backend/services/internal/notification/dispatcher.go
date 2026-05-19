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

const DeliveredTTL = 60 * time.Second
const markDeliveredTimeout = 5 * time.Second

// Channels this service subscribes to.
//
// Every Django payload is wrapped as {event_id, ts, targets:[user_id,...], ...}
// (see apps/core/redis_bus.py). The dispatcher walks `targets` and fans
// each event to those users' local WS sockets. Channels listed here that
// predate the `targets` convention fall back to legacy keys
// (sender_id/traveler_id/recipient_id) on missing/empty targets.
var subscribedChannels = []string{
	"match.created",
	"match.in_transit",
	"match.completed",
	"offer.created",
	"offer.updated",
	"offer.accepted",
	"parcel.created",
	"parcel.cancelled",
	"trip.created",
	"trip.cancelled",
	"payment.captured",
	"payment.refunded",
	"handover.code_issued",
	"handover.confirmed",
}

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

func (d *Dispatcher) Run(ctx context.Context) error {
	sub, err := d.rdb.Subscribe(ctx, subscribedChannels...)
	if err != nil {
		return fmt.Errorf("subscribe: %w", err)
	}
	defer func() { _ = sub.Close() }()

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

// genericPayload is the envelope every Django publish now produces.
// Channel-specific fields are read on-demand from the raw bytes for the
// legacy-fallback path.
type genericPayload struct {
	EventID string  `json:"event_id"`
	Ts      string  `json:"ts"`
	Targets []int64 `json:"targets"`
}

// legacyTargets is read only when `targets` is absent/empty (older
// publishes during the rollout). Channels that don't carry any of these
// keys simply produce no recipients and the event is dropped silently.
type legacyTargets struct {
	SenderID    int64 `json:"sender_id"`
	TravelerID  int64 `json:"traveler_id"`
	RecipientID int64 `json:"recipient_id"`
	PayerID     int64 `json:"payer_id"`
	IssuedToID  int64 `json:"issued_to_id"`
}

func (d *Dispatcher) dispatch(msg redisbus.Message) {
	var env genericPayload
	if err := json.Unmarshal(msg.Payload, &env); err != nil {
		d.log.Error("dispatcher: bad payload", "channel", msg.Channel, "err", err)
		return
	}
	if env.EventID == "" {
		d.log.Error("dispatcher: missing event_id", "channel", msg.Channel)
		return
	}

	targets := env.Targets
	if len(targets) == 0 {
		var lg legacyTargets
		_ = json.Unmarshal(msg.Payload, &lg)
		targets = uniqueNonZero([]int64{
			lg.SenderID, lg.TravelerID, lg.RecipientID, lg.PayerID, lg.IssuedToID,
		})
	}
	if len(targets) == 0 {
		d.log.Debug("dispatcher: no targets",
			"channel", msg.Channel, "event_id", env.EventID)
		return
	}

	wsEnv := wsproto.Envelope{
		EventID: env.EventID,
		Ts:      env.Ts,
		Type:    msg.Channel,
		Payload: msg.Payload,
	}

	var sockets int
	for _, uid := range targets {
		sockets += d.hub.Send(uid, wsEnv)
	}
	if sockets == 0 {
		d.log.Debug("dispatcher: no local recipients",
			"channel", msg.Channel,
			"event_id", env.EventID,
			"target_count", len(targets),
		)
		return
	}
	d.markDelivered(env.EventID, msg.Channel, sockets)
}

func uniqueNonZero(in []int64) []int64 {
	seen := make(map[int64]struct{}, len(in))
	out := make([]int64, 0, len(in))
	for _, v := range in {
		if v == 0 {
			continue
		}
		if _, ok := seen[v]; ok {
			continue
		}
		seen[v] = struct{}{}
		out = append(out, v)
	}
	return out
}

func (d *Dispatcher) markDelivered(eventID, channel string, sockets int) {
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
	d.log.Debug("dispatched",
		"channel", channel, "event_id", eventID, "sockets", sockets)
}
