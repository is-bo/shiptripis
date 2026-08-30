package redisbus

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"

	"shiptrip/pkg/metrics"
)

type Client struct {
	rdb     *redis.Client
	log     *slog.Logger
	metrics *metrics.Group
}

type Config struct {
	URL    string
	Logger *slog.Logger

	// Metrics is the service's metrics group. Pass nil to disable the
	// pubsub_drops / pubsub_drops_total counters (used by tests).
	Metrics *metrics.Group

	// Pool / timeout knobs. Zero values fall through to go-redis defaults
	// (PoolSize = 10 × GOMAXPROCS). Set them explicitly in main.go so the
	// per-service connection budget is reviewable — same discipline as
	// the Postgres pool in CLAUDE.md §3.
	PoolSize     int
	MinIdleConns int
	DialTimeout  time.Duration
	ReadTimeout  time.Duration
	WriteTimeout time.Duration
}

func NewClient(ctx context.Context, cfg Config) (*Client, error) {
	if cfg.URL == "" {
		return nil, errors.New("redis url is empty")
	}

	log := cfg.Logger
	if log == nil {
		log = slog.Default()
	}

	opts, err := redis.ParseURL(cfg.URL)
	if err != nil {
		return nil, fmt.Errorf("parse redis url: %w", err)
	}

	if cfg.PoolSize > 0 {
		opts.PoolSize = cfg.PoolSize
	}
	if cfg.MinIdleConns > 0 {
		opts.MinIdleConns = cfg.MinIdleConns
	}
	if cfg.DialTimeout > 0 {
		opts.DialTimeout = cfg.DialTimeout
	}
	if cfg.ReadTimeout > 0 {
		opts.ReadTimeout = cfg.ReadTimeout
	}
	if cfg.WriteTimeout > 0 {
		opts.WriteTimeout = cfg.WriteTimeout
	}

	rdb := redis.NewClient(opts)

	pingCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	if err := rdb.Ping(pingCtx).Err(); err != nil {
		_ = rdb.Close()
		return nil, fmt.Errorf("ping redis: %w", err)
	}

	log.Info("redis client ready",
		"addr", opts.Addr,
		"pool_size", opts.PoolSize,
		"min_idle", opts.MinIdleConns,
	)
	return &Client{rdb: rdb, log: log, metrics: cfg.Metrics}, nil
}

func (c *Client) Close() error {
	return c.rdb.Close()
}

// ── Pub/Sub (G1: WS fan-out) ─────────────────────────────────────────────────

func (c *Client) Publish(ctx context.Context, channel string, payload []byte) error {
	return c.rdb.Publish(ctx, channel, payload).Err()
}

// Message is the wrapped pub/sub message — keeps callers off the redis package.
type Message struct {
	Channel string
	Payload []byte
}

// Subscription wraps *redis.PubSub so callers don't import go-redis.
// Lifetime is controlled by Close, not the ctx passed to Subscribe —
// that ctx only bounds the initial handshake.
type Subscription struct {
	ps        *redis.PubSub
	out       chan Message
	log       *slog.Logger
	metrics   *metrics.Group
	stop      chan struct{}
	done      chan struct{}
	closeOnce sync.Once
}

// subscribeBuffer sizes the pump's outbound channel. 1024 is large
// enough that a reconnect storm (CLAUDE.md §7: thousands of devices
// reconnecting after a tower hiccup) fills the buffer for several
// seconds before drops start, giving the dispatcher's worker pool time
// to catch up. The trade-off vs heap is ~32 KiB per subscription —
// trivial against the alternative of losing a notification.
const subscribeBuffer = 1024

// pubsubEventID is the JSON-tagged subset of the envelope every
// publisher wraps payloads in (see monolith/apps/core/redis_bus.py).
// Decoded only when we drop a message so a healthy subscription pays
// no JSON cost; on backpressure we surface event_id to the G6b sweep.
type pubsubEventID struct {
	EventID string `json:"event_id"`
}

// Subscribe opens a pub/sub subscription. The provided ctx bounds only
// the initial handshake; the subscription itself runs until Close().
// Callers read from Channel() and must call Close() to release the
// connection and stop the pump goroutine.
func (c *Client) Subscribe(ctx context.Context, channels ...string) (*Subscription, error) {
	ps := c.rdb.Subscribe(ctx, channels...)
	if _, err := ps.Receive(ctx); err != nil {
		_ = ps.Close()
		return nil, fmt.Errorf("subscribe: %w", err)
	}

	s := &Subscription{
		ps:      ps,
		out:     make(chan Message, subscribeBuffer),
		log:     c.log,
		metrics: c.metrics,
		stop:    make(chan struct{}),
		done:    make(chan struct{}),
	}
	go s.pump()
	return s, nil
}

// pump forwards messages from go-redis's PubSub channel to our buffered
// out channel. On backpressure (out is full) we DROP the message and:
//
//   - parse event_id from the envelope so G6b can correlate the loss
//     with the undelivered core_published_event row,
//   - increment a per-channel drop counter (pubsub_drops_<channel>),
//   - increment the global pubsub_drops_total counter.
//
// Dropping is preferable to blocking — a blocked reader would let
// go-redis's internal buffer fill and Redis would terminate the
// subscription for slow consumption, which is strictly worse.
func (s *Subscription) pump() {
	defer close(s.done)
	defer close(s.out)
	ch := s.ps.Channel()
	for {
		select {
		case <-s.stop:
			return
		case m, ok := <-ch:
			if !ok {
				return
			}
			msg := Message{Channel: m.Channel, Payload: []byte(m.Payload)}
			select {
			case s.out <- msg:
			case <-s.stop:
				return
			default:
				s.recordDrop(m.Channel, msg.Payload)
			}
		}
	}
}

func (s *Subscription) recordDrop(channel string, payload []byte) {
	var env pubsubEventID
	_ = json.Unmarshal(payload, &env) // best-effort; missing event_id is fine
	s.log.Warn("pubsub buffer full, dropping message",
		"channel", channel,
		"event_id", env.EventID,
		"buffer", subscribeBuffer,
	)
	if s.metrics != nil {
		s.metrics.Counter("pubsub_drops_total", 1)
		s.metrics.Counter("pubsub_drops_"+channel, 1)
	}
}

func (s *Subscription) Channel() <-chan Message { return s.out }

// Close signals the pump to stop, closes the underlying PubSub, and
// waits for the pump goroutine to exit. Safe to call from multiple
// goroutines; only the first call performs the shutdown.
func (s *Subscription) Close() error {
	var err error
	s.closeOnce.Do(func() {
		close(s.stop)
		err = s.ps.Close()
		<-s.done
	})
	return err
}

// ── Presence + delivery receipts (G1) ────────────────────────────────────────

func (c *Client) SetEX(ctx context.Context, key string, value any, ttl time.Duration) error {
	return c.rdb.Set(ctx, key, value, ttl).Err()
}

func (c *Client) Del(ctx context.Context, keys ...string) error {
	return c.rdb.Del(ctx, keys...).Err()
}

func (c *Client) Exists(ctx context.Context, key string) (bool, error) {
	n, err := c.rdb.Exists(ctx, key).Result()
	if err != nil {
		return false, err
	}
	return n > 0, nil
}

// FixedWindowBucket describes one independent budget consumed by an atomic
// fixed-window operation. Keys are supplied by the caller so a domain package
// can choose a stable, versioned namespace without exposing the Redis client.
type FixedWindowBucket struct {
	Key    string
	Limit  int64
	Window time.Duration
}

// FixedWindowDecision is the result of ConsumeFixedWindow. RetryAfter is only
// meaningful when Allowed is false and is derived from the longest remaining
// TTL among the exhausted buckets.
type FixedWindowDecision struct {
	Allowed    bool
	RetryAfter time.Duration
}

// fixedWindowScript checks every bucket before incrementing any of them, then
// increments all buckets in one Redis Lua invocation. This makes the
// multi-dimensional user+IP budget all-or-nothing and closes read-then-write
// races when several service instances receive the same user's requests.
// Each key is a fixed window anchored by its first request; PTTL is returned
// for Retry-After. A missing/invalid TTL is treated as a full window so a
// manually altered key cannot become an unbounded lockout.
var fixedWindowScript = redis.NewScript(`
local retry_after = 0
local bucket_count = #KEYS
for i = 1, bucket_count do
  local arg = (i - 1) * 2
  local current = tonumber(redis.call("GET", KEYS[i]) or "0")
  local limit = tonumber(ARGV[arg + 1])
  local window = tonumber(ARGV[arg + 2])
  if current >= limit then
    local ttl = redis.call("PTTL", KEYS[i])
    if ttl <= 0 then
      ttl = window
      redis.call("PEXPIRE", KEYS[i], window)
    end
    if ttl > retry_after then
      retry_after = ttl
    end
  end
end

if retry_after > 0 then
  return {0, retry_after}
end

for i = 1, bucket_count do
  local arg = (i - 1) * 2
  local value = redis.call("INCR", KEYS[i])
  local ttl = redis.call("PTTL", KEYS[i])
  if value == 1 or ttl <= 0 then
    redis.call("PEXPIRE", KEYS[i], tonumber(ARGV[arg + 2]))
  end
end
return {1, 0}
`)

// ConsumeFixedWindow atomically checks and consumes one request from every
// supplied bucket. It is intentionally a low-level Redis primitive: callers
// must validate and namespace keys before reaching this method. Empty buckets
// and non-positive limits/windows are rejected instead of silently disabling a
// protection policy.
func (c *Client) ConsumeFixedWindow(ctx context.Context, buckets ...FixedWindowBucket) (FixedWindowDecision, error) {
	if len(buckets) == 0 {
		return FixedWindowDecision{}, errors.New("redis fixed window: at least one bucket is required")
	}
	keys := make([]string, len(buckets))
	args := make([]any, 0, len(buckets)*2)
	for i, bucket := range buckets {
		if bucket.Key == "" {
			return FixedWindowDecision{}, errors.New("redis fixed window: bucket key is required")
		}
		if bucket.Limit <= 0 {
			return FixedWindowDecision{}, fmt.Errorf("redis fixed window: bucket %q limit must be positive", bucket.Key)
		}
		windowMS := bucket.Window.Milliseconds()
		if windowMS <= 0 {
			return FixedWindowDecision{}, fmt.Errorf("redis fixed window: bucket %q window must be positive", bucket.Key)
		}
		keys[i] = bucket.Key
		args = append(args, bucket.Limit, windowMS)
	}

	result, err := fixedWindowScript.Run(ctx, c.rdb, keys, args...).Result()
	if err != nil {
		return FixedWindowDecision{}, err
	}
	values, ok := result.([]any)
	if !ok || len(values) != 2 {
		return FixedWindowDecision{}, errors.New("redis fixed window: malformed script response")
	}
	allowed, ok := redisScriptInt(values[0])
	if !ok {
		return FixedWindowDecision{}, errors.New("redis fixed window: malformed allow result")
	}
	retryMS, ok := redisScriptInt(values[1])
	if !ok {
		return FixedWindowDecision{}, errors.New("redis fixed window: malformed retry result")
	}
	return FixedWindowDecision{
		Allowed:    allowed == 1,
		RetryAfter: time.Duration(retryMS) * time.Millisecond,
	}, nil
}

func redisScriptInt(value any) (int64, bool) {
	switch n := value.(type) {
	case int64:
		return n, true
	case int:
		return int64(n), true
	case string:
		parsed, err := strconv.ParseInt(n, 10, 64)
		return parsed, err == nil
	default:
		return 0, false
	}
}

// ── Streams (G1: FCM queue) ──────────────────────────────────────────────────

// XAddCapped enforces MAXLEN ~ N (G1: stream MUST be capped, default 10_000).
// Pass 0 for the default cap.
func (c *Client) XAddCapped(ctx context.Context, stream string, maxLen int64, fields map[string]any) (string, error) {
	if maxLen <= 0 {
		maxLen = 10_000
	}
	return c.rdb.XAdd(ctx, &redis.XAddArgs{
		Stream: stream,
		MaxLen: maxLen,
		Approx: true,
		Values: fields,
	}).Result()
}

// StreamMessage is the wrapped stream entry — keeps callers off the redis package.
type StreamMessage struct {
	ID     string
	Values map[string]any
}

// XReadGroupArgs reads a single stream — V1's only consumer (notif:fcm) needs no more.
// Note: BLOCK is server-side; ctx cancellation only takes effect AFTER Block elapses.
// Keep Block ≤ 5s so graceful shutdowns aren't held up.
type XReadGroupArgs struct {
	Group    string
	Consumer string
	Stream   string
	ID       string // ">" for new, "0" to replay PEL
	Count    int64
	Block    time.Duration
}

func (c *Client) XReadGroup(ctx context.Context, args XReadGroupArgs) ([]StreamMessage, error) {
	res, err := c.rdb.XReadGroup(ctx, &redis.XReadGroupArgs{
		Group:    args.Group,
		Consumer: args.Consumer,
		Streams:  []string{args.Stream, args.ID},
		Count:    args.Count,
		Block:    args.Block,
	}).Result()
	if err != nil {
		if errors.Is(err, redis.Nil) {
			return nil, nil
		}
		return nil, err
	}
	if len(res) == 0 {
		return nil, nil
	}
	return wrapMessages(res[0].Messages), nil
}

func (c *Client) XAck(ctx context.Context, stream, group string, ids ...string) error {
	return c.rdb.XAck(ctx, stream, group, ids...).Err()
}

func wrapMessages(in []redis.XMessage) []StreamMessage {
	out := make([]StreamMessage, len(in))
	for i, m := range in {
		out[i] = StreamMessage{ID: m.ID, Values: m.Values}
	}
	return out
}

// XGroupCreate is idempotent: BUSYGROUP (group already exists) is treated as success.
func (c *Client) XGroupCreate(ctx context.Context, stream, group, start string) error {
	err := c.rdb.XGroupCreateMkStream(ctx, stream, group, start).Err()
	if err != nil && strings.HasPrefix(err.Error(), "BUSYGROUP") {
		return nil
	}
	return err
}

type XAutoClaimArgs struct {
	Stream   string
	Group    string
	Consumer string
	MinIdle  time.Duration
	Start    string // "0-0" to start from the beginning of the PEL
	Count    int64
}

func (c *Client) XAutoClaim(ctx context.Context, args XAutoClaimArgs) ([]StreamMessage, string, error) {
	msgs, next, err := c.rdb.XAutoClaim(ctx, &redis.XAutoClaimArgs{
		Stream:   args.Stream,
		Group:    args.Group,
		Consumer: args.Consumer,
		MinIdle:  args.MinIdle,
		Start:    args.Start,
		Count:    args.Count,
	}).Result()
	if err != nil {
		return nil, "", err
	}
	return wrapMessages(msgs), next, nil
}
