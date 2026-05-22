package notification

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"shiptrip/pkg/redisbus"
)

// Consumer is the G1 FCM-fallback worker (CLAUDE.md §2 G1).
//
// Path per event:
//  1. XReadGroup pulls a message off the durable stream Django writes to
//     (default `notif:fcm`).
//  2. Wait `DeliverGracePeriod` so the WS-owning pod has a chance to
//     write `delivered:<event_id>` if the user has a live socket.
//  3. EXISTS delivered:<event_id> — if set, the user got the WS push and
//     FCM would be a duplicate. XAck and move on.
//  4. Otherwise, Send via FCM (currently stubbed — see FCMSender). On
//     success, XAck. On failure, leave in the PEL so the sweeper retries.
//
// A separate `Sweep` goroutine runs XAUTOCLAIM every `SweepInterval` to
// reclaim PEL entries idle longer than `SweepMinIdle` — covers the case
// where a pod crashed after XReadGroup but before XAck.
type Consumer struct {
	rdb           *redisbus.Client
	sender        FCMSender
	stream        string
	group         string
	name          string
	log           *slog.Logger
	deliverGrace  time.Duration
	sweepMinIdle  time.Duration
	sweepInterval time.Duration
}

// ConsumerConfig wires the runtime knobs. Defaults match CLAUDE.md G1
// guidance; override only with a reason.
type ConsumerConfig struct {
	Stream        string
	ConsumerGroup string
	ConsumerName  string
	// Sender is the actual FCM HTTP backend. Pass nil to install the
	// LogOnlySender stub — useful while Django + fcm_token are still
	// landing. The consumer never panics on nil.
	Sender FCMSender
}

// Default timings — tracked here so changes are diff-reviewable.
const (
	// DeliverGracePeriod is the wait between stream read and the
	// delivered-key check. CLAUDE.md G1 specifies 2s — must be greater
	// than the typical Redis pub/sub fan-out + WS write latency.
	DeliverGracePeriod = 2 * time.Second

	// SweepMinIdle is the PEL idle threshold before XAUTOCLAIM reclaims.
	// 60s per CLAUDE.md G1 ("entries idle > 60s").
	SweepMinIdle = 60 * time.Second

	// SweepInterval is how often the sweeper runs. 30s per CLAUDE.md G1.
	SweepInterval = 30 * time.Second

	// xreadBlock bounds the XReadGroup BLOCK so graceful shutdown isn't
	// held for the full server timeout. ctx cancellation only takes
	// effect after Block elapses (see redisbus.XReadGroupArgs comment).
	xreadBlock = 2 * time.Second

	// xreadCount is the batch size per loop. 16 keeps each iteration
	// short (loop latency = grace + send × 16) while still amortising
	// the round-trip to Redis.
	xreadCount = 16
)

// NewConsumer builds a Consumer with sensible defaults. Caller must
// XGroupCreate the stream/group before Run (idempotent — see redisbus).
func NewConsumer(rdb *redisbus.Client, cfg ConsumerConfig, log *slog.Logger) *Consumer {
	if log == nil {
		log = slog.Default()
	}
	if cfg.Stream == "" {
		cfg.Stream = "notif:fcm"
	}
	if cfg.ConsumerGroup == "" {
		cfg.ConsumerGroup = "notif-fcm-workers"
	}
	if cfg.ConsumerName == "" {
		cfg.ConsumerName = "notif-fcm-1"
	}
	sender := cfg.Sender
	if sender == nil {
		sender = LogOnlySender{Log: log}
	}
	return &Consumer{
		rdb:           rdb,
		sender:        sender,
		stream:        cfg.Stream,
		group:         cfg.ConsumerGroup,
		name:          cfg.ConsumerName,
		log:           log,
		deliverGrace:  DeliverGracePeriod,
		sweepMinIdle:  SweepMinIdle,
		sweepInterval: SweepInterval,
	}
}

// Run is the main consumer loop. Blocks until ctx is cancelled. Run the
// sweeper in a separate goroutine via Sweep — they share the consumer
// name but read the stream independently (XAUTOCLAIM reassigns to the
// caller's consumer, not to a different one).
func (c *Consumer) Run(ctx context.Context) error {
	if err := c.rdb.XGroupCreate(ctx, c.stream, c.group, "$"); err != nil {
		return fmt.Errorf("fcm: xgroup create: %w", err)
	}
	c.log.Info("fcm consumer started",
		"stream", c.stream, "group", c.group, "consumer", c.name)

	for {
		if err := ctx.Err(); err != nil {
			return nil
		}
		msgs, err := c.rdb.XReadGroup(ctx, redisbus.XReadGroupArgs{
			Group:    c.group,
			Consumer: c.name,
			Stream:   c.stream,
			ID:       ">",
			Count:    xreadCount,
			Block:    xreadBlock,
		})
		if err != nil {
			if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
				return nil
			}
			c.log.Error("fcm xreadgroup", "err", err)
			// Tight loop on a broken Redis would be wasteful — pause briefly
			// before retrying so we don't burn CPU during an outage.
			select {
			case <-ctx.Done():
				return nil
			case <-time.After(time.Second):
			}
			continue
		}
		for _, m := range msgs {
			c.handle(ctx, m)
		}
	}
}

// Sweep runs XAUTOCLAIM on a fixed interval, reclaiming PEL entries from
// dead pods. Returns when ctx is cancelled. Caller runs in its own
// goroutine.
func (c *Consumer) Sweep(ctx context.Context) error {
	t := time.NewTicker(c.sweepInterval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-t.C:
			c.sweepOnce(ctx)
		}
	}
}

func (c *Consumer) sweepOnce(ctx context.Context) {
	start := "0-0"
	for {
		msgs, next, err := c.rdb.XAutoClaim(ctx, redisbus.XAutoClaimArgs{
			Stream:   c.stream,
			Group:    c.group,
			Consumer: c.name,
			MinIdle:  c.sweepMinIdle,
			Start:    start,
			Count:    xreadCount,
		})
		if err != nil {
			if !errors.Is(err, context.Canceled) {
				c.log.Warn("fcm sweep", "err", err)
			}
			return
		}
		for _, m := range msgs {
			c.handle(ctx, m)
		}
		// "0-0" sentinel means the scan finished — XAUTOCLAIM signals
		// completion this way per Redis docs.
		if next == "" || next == "0-0" {
			return
		}
		start = next
	}
}

// handle processes a single stream entry: wait, check delivered, send, ack.
// All errors are logged; only XAck failures leave the entry in the PEL
// for the sweeper. The delivered-key check is intentionally NOT a
// guarantee against duplicates — two pods can race the EXISTS, both
// see "not delivered", and both push. CLAUDE.md accepts this; the
// alternative (distributed lock per event) is far worse for V1.
func (c *Consumer) handle(ctx context.Context, m redisbus.StreamMessage) {
	eventID := stringField(m.Values, "event_id")
	if eventID == "" {
		c.log.Warn("fcm: stream entry missing event_id; acking to drop", "id", m.ID)
		c.ack(ctx, m.ID)
		return
	}

	// Grace period — give the WS-owning pod a chance to mark delivered.
	select {
	case <-ctx.Done():
		return
	case <-time.After(c.deliverGrace):
	}

	delivered, err := c.rdb.Exists(ctx, "delivered:"+eventID)
	if err != nil {
		c.log.Warn("fcm: delivered check failed", "event_id", eventID, "err", err)
		// Don't ack — sweeper will reclaim and retry.
		return
	}
	if delivered {
		c.log.Debug("fcm: skipping; ws delivered", "event_id", eventID)
		c.ack(ctx, m.ID)
		return
	}

	payload, err := decodePayload(m.Values)
	if err != nil {
		c.log.Warn("fcm: bad payload; acking to drop",
			"event_id", eventID, "id", m.ID, "err", err)
		c.ack(ctx, m.ID)
		return
	}

	if err := c.sender.Send(ctx, payload); err != nil {
		c.log.Warn("fcm send failed; leaving in PEL for sweep",
			"event_id", eventID, "err", err)
		return
	}
	c.ack(ctx, m.ID)
}

func (c *Consumer) ack(ctx context.Context, id string) {
	// Detach so a cancelled parent ctx doesn't leave a delivered push
	// un-ack'd, which would re-send on next sweep.
	ackCtx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if ctx.Err() != nil {
		// If parent is already gone, use the detached ctx alone.
		ctx = ackCtx
	}
	if err := c.rdb.XAck(ackCtx, c.stream, c.group, id); err != nil {
		c.log.Warn("fcm xack failed", "id", id, "err", err)
	}
}

// FCMPayload is the wire shape Django writes onto the stream. Mirrors
// what the Django publisher will produce — kept here as the contract
// since the Go side reads it. Tokens are pre-resolved by Django from
// accounts_user.fcm_token at publish time so the consumer doesn't need
// a database lookup on the hot path.
type FCMPayload struct {
	EventID string   `json:"event_id"`
	UserID  int64    `json:"user_id"`
	Tokens  []string `json:"tokens"`
	Title   string   `json:"title"`
	Body    string   `json:"body"`
	// Data is the FCM `data` payload — opaque key/value pairs the app
	// uses for in-app routing (e.g. open the right chat thread).
	Data map[string]string `json:"data,omitempty"`
}

// decodePayload pulls the JSON `payload` field from the stream entry.
// Django writes a single `payload` field (matches the redis_bus shape);
// other fields like `event_id` are denormalised for cheap filtering.
func decodePayload(values map[string]any) (FCMPayload, error) {
	raw := stringField(values, "payload")
	if raw == "" {
		return FCMPayload{}, errors.New("missing payload field")
	}
	var p FCMPayload
	if err := json.Unmarshal([]byte(raw), &p); err != nil {
		return FCMPayload{}, fmt.Errorf("unmarshal: %w", err)
	}
	if len(p.Tokens) == 0 {
		return FCMPayload{}, errors.New("no tokens")
	}
	return p, nil
}

func stringField(values map[string]any, key string) string {
	v, ok := values[key]
	if !ok {
		return ""
	}
	s, ok := v.(string)
	if !ok {
		return ""
	}
	return s
}

// FCMSender is the swap point for the real FCM HTTP client. Exported
// so cmd/notification can inject a concrete implementation once Django
// + fcm_token land. The most likely production wiring is
// firebase.google.com/go/v4, but it pulls a large dep tree and we don't
// want to commit until the publisher exists.
type FCMSender interface {
	Send(ctx context.Context, p FCMPayload) error
}

// LogOnlySender is the dev / pre-launch stub. Logs the event and
// returns nil so the consumer flow can be exercised end-to-end without
// a Firebase project. Swap for a real client by passing a different
// `Sender` to NewConsumer once Django writes to the stream.
type LogOnlySender struct {
	Log *slog.Logger
}

func (s LogOnlySender) Send(_ context.Context, p FCMPayload) error {
	log := s.Log
	if log == nil {
		log = slog.Default()
	}
	log.Info("fcm: would-send (stub)",
		"event_id", p.EventID,
		"user_id", p.UserID,
		"tokens", len(p.Tokens),
		"title", p.Title,
	)
	return nil
}
