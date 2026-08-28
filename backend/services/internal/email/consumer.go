package email

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"shiptrip/pkg/redisbus"
)

// Consumer drains the `email:send` Redis Stream and sends each entry over
// SMTP. It mirrors notification.Consumer (the FCM worker) minus the
// FCM-specific bits: there is no 2s delivery-grace wait and no
// `delivered:<event_id>` WS-dedup, because email has no WebSocket counterpart
// that might satisfy the same event first.
//
// Per entry:
//  1. XReadGroup pulls a batch off the stream (consumer-group semantics: each
//     entry goes to exactly one pod's group member).
//  2. EXISTS email:sent:<event_id> — skip+ack if a prior send already
//     recorded it (sweeper re-delivery after a crash-before-ack).
//  3. Send via the EmailSender. On success, SET email:sent:<event_id> then
//     XAck. On failure, leave it in the PEL so the sweeper retries.
//
// A separate Sweep goroutine runs XAUTOCLAIM to reclaim PEL entries from pods
// that died after XReadGroup but before XAck.
type Consumer struct {
	rdb           *redisbus.Client
	sender        EmailSender
	receipts      ReceiptStore
	stream        string
	group         string
	name          string
	log           *slog.Logger
	sweepMinIdle  time.Duration
	sweepInterval time.Duration

	// sem bounds concurrent handle() goroutines so a slow SMTP endpoint can't
	// grow goroutines without limit. wg tracks them so Run/Sweep don't return
	// until in-flight handlers finish — an XAck on a cancelled ctx would
	// re-deliver via the sweeper.
	sem chan struct{}
	wg  sync.WaitGroup
}

// ConsumerConfig wires the runtime knobs. Defaults match the FCM consumer's
// G1 guidance; override only with a reason.
type ConsumerConfig struct {
	Stream        string
	ConsumerGroup string
	ConsumerName  string
	// Sender is the actual SMTP backend. Pass nil to install LogOnlySender —
	// the consumer never panics on nil. cmd/email passes the real smtpSender
	// when EMAIL_ENABLED=true.
	Sender EmailSender
	// Receipts is the durable PostgreSQL acknowledgement boundary. Production
	// always supplies it; tests may omit it to use the no-op implementation.
	Receipts ReceiptStore
}

const (
	// SweepMinIdle is the PEL idle threshold before XAUTOCLAIM reclaims.
	SweepMinIdle = 60 * time.Second
	// SweepInterval is how often the sweeper runs.
	SweepInterval = 30 * time.Second

	// xreadBlock bounds the XReadGroup BLOCK so graceful shutdown isn't held
	// for the full server timeout (ctx cancellation only takes effect after
	// Block elapses).
	xreadBlock = 2 * time.Second
	// xreadCount is the batch size per loop.
	xreadCount = 16
	// handleConcurrency bounds in-flight handle() goroutines per pod. Each
	// holds one PEL entry and at most one SMTP dial's worth of memory.
	handleConcurrency = 32

	// sendTimeout caps a single SMTP send (dial + STARTTLS + auth + DATA).
	// Detached from the parent ctx so a graceful shutdown mid-send completes
	// rather than leaving the entry half-sent and unacked.
	sendTimeout = 30 * time.Second

	// sentKeyTTL is how long the email:sent:<event_id> dedup marker lives.
	// Long enough to cover any realistic sweeper-retry window; short enough
	// not to accumulate. 10 minutes mirrors the OTP validity ballpark.
	sentKeyTTL = 10 * time.Minute
)

// NewConsumer builds a Consumer with sensible defaults. Caller need not
// pre-create the group — Run does it (idempotent via redisbus.XGroupCreate).
func NewConsumer(rdb *redisbus.Client, cfg ConsumerConfig, log *slog.Logger) *Consumer {
	if log == nil {
		log = slog.Default()
	}
	if cfg.Stream == "" {
		cfg.Stream = "email:send"
	}
	if cfg.ConsumerGroup == "" {
		cfg.ConsumerGroup = "email-send-workers"
	}
	if cfg.ConsumerName == "" {
		cfg.ConsumerName = "email-1"
	}
	sender := cfg.Sender
	if sender == nil {
		sender = LogOnlySender{Log: log}
	}
	receipts := cfg.Receipts
	if receipts == nil {
		receipts = noopReceiptStore{}
	}
	return &Consumer{
		rdb:           rdb,
		sender:        sender,
		receipts:      receipts,
		stream:        cfg.Stream,
		group:         cfg.ConsumerGroup,
		name:          cfg.ConsumerName,
		log:           log,
		sweepMinIdle:  SweepMinIdle,
		sweepInterval: SweepInterval,
		sem:           make(chan struct{}, handleConcurrency),
	}
}

// Run is the main consumer loop. Blocks until ctx is cancelled and every
// in-flight handler has finished.
func (c *Consumer) Run(ctx context.Context) error {
	if err := c.rdb.XGroupCreate(ctx, c.stream, c.group, "$"); err != nil {
		return fmt.Errorf("email: xgroup create: %w", err)
	}
	c.log.Info("email consumer started",
		"stream", c.stream, "group", c.group, "consumer", c.name)
	defer c.wg.Wait()

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
			c.log.Error("email xreadgroup", "err", err)
			// Don't tight-loop on a broken Redis.
			select {
			case <-ctx.Done():
				return nil
			case <-time.After(time.Second):
			}
			continue
		}
		for _, m := range msgs {
			if !c.dispatchHandle(ctx, m) {
				return nil
			}
		}
	}
}

// Sweep runs XAUTOCLAIM on a fixed interval, reclaiming PEL entries from dead
// pods. Returns when ctx is cancelled. Run and Sweep share the same in-flight
// WaitGroup, so the first to return waits for both fleets of handlers —
// main.go must cancel the shared ctx before joining either.
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
				c.log.Warn("email sweep", "err", err)
			}
			return
		}
		for _, m := range msgs {
			if !c.dispatchHandle(ctx, m) {
				return
			}
		}
		// "0-0" sentinel means the scan finished.
		if next == "" || next == "0-0" {
			return
		}
		start = next
	}
}

// dispatchHandle acquires a semaphore slot and spawns a handler. Returns false
// iff ctx was cancelled while waiting for a slot — the caller stops pulling new
// work; the PEL entry stays claimed for the next pod's sweeper.
func (c *Consumer) dispatchHandle(ctx context.Context, m redisbus.StreamMessage) bool {
	select {
	case <-ctx.Done():
		return false
	case c.sem <- struct{}{}:
	}
	c.wg.Go(func() {
		defer func() { <-c.sem }()
		c.handle(ctx, m)
	})
	return true
}

// handle processes a single stream entry: decode → dedup-check → send →
// mark-sent → ack. Only XAck failures (or a send failure) leave the entry in
// the PEL for the sweeper. The dedup is best-effort, not a hard guarantee:
// two pods can race the EXISTS and both send. That's accepted — a duplicate is
// at worst one extra email carrying the same still-valid code.
func (c *Consumer) handle(ctx context.Context, m redisbus.StreamMessage) {
	p, err := decodePayload(m.Values)
	if err != nil {
		c.log.Warn("email: bad payload; acking to drop", "id", m.ID, "err", err)
		c.ack(m.ID)
		return
	}

	// Detach from the parent ctx: once we're past decode we've committed to
	// either acking or leaving in PEL, and Run's defer wg.Wait() already holds
	// shutdown until handle returns. A shutdown-cancelled send would otherwise
	// surface as a duplicate on the next pod's sweep.
	sendCtx, cancel := context.WithTimeout(context.Background(), sendTimeout)
	defer cancel()

	sentKey := "email:sent:" + p.EventID
	if p.EventID != "" {
		delivered, err := c.receipts.Delivered(sendCtx, p.EventID)
		if err != nil {
			c.log.Warn("email: durable receipt check failed; leaving in PEL",
				"event_id", p.EventID, "err", err)
			return
		}
		if delivered {
			c.log.Debug("email: skip; PostgreSQL receipt already recorded", "event_id", p.EventID)
			c.ack(m.ID)
			return
		}

		already, err := c.rdb.Exists(sendCtx, sentKey)
		if err != nil {
			c.log.Warn("email: dedup check failed", "event_id", p.EventID, "err", err)
			// Don't ack — sweeper reclaims and retries.
			return
		}
		if already {
			// SMTP accepted this event on an earlier attempt but the durable
			// receipt failed. Repair PostgreSQL before acknowledging the stream;
			// otherwise Django would retry the logical obligation forever.
			if err := c.receipts.MarkDelivered(sendCtx, p.EventID); err != nil {
				c.log.Warn("email: durable receipt repair failed; leaving in PEL",
					"event_id", p.EventID, "err", err)
				return
			}
			c.log.Debug("email: repaired durable receipt for prior send", "event_id", p.EventID)
			c.ack(m.ID)
			return
		}
	}

	if err := c.sender.Send(sendCtx, p); err != nil {
		c.log.Warn("email send failed; leaving in PEL for sweep",
			"event_id", p.EventID, "kind", p.Kind, "err", err)
		return
	}

	// Record the short-lived send marker before the durable receipt. If the
	// PostgreSQL write fails, the PEL retry repairs the receipt without sending
	// again. A simultaneous Redis restart and receipt failure can still produce
	// one duplicate; SMTP offers no idempotency primitive, so at-least-once is
	// the honest boundary.
	if p.EventID != "" {
		if err := c.rdb.SetEX(sendCtx, sentKey, "1", sentKeyTTL); err != nil {
			c.log.Warn("email: sent-marker write failed", "event_id", p.EventID, "err", err)
		}
		if err := c.receipts.MarkDelivered(sendCtx, p.EventID); err != nil {
			c.log.Warn("email: durable receipt write failed; leaving in PEL",
				"event_id", p.EventID, "err", err)
			return
		}
	}
	c.ack(m.ID)
}

// ack detaches from the caller's ctx so a cancelled parent (graceful shutdown,
// sweep abort) doesn't leave a sent mail unacked — which would surface as a
// duplicate on next sweep.
func (c *Consumer) ack(id string) {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := c.rdb.XAck(ctx, c.stream, c.group, id); err != nil {
		c.log.Warn("email xack failed", "id", id, "err", err)
	}
}
