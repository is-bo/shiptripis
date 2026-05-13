package notification

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"shiptrip/pkg/redisbus"
)

// PresenceTTL is the lifetime of a presence:<user_id> key in Redis.
//
// Must be tighter than wsproto.PingInterval (10s) — a missed pong drops
// the socket *before* the presence key expires, so a stale key never
// masks a dropped connection (CLAUDE.md §5).
const PresenceTTL = 15 * time.Second

// Presence wraps the Redis-side bookkeeping for "user X has a live socket
// somewhere in the cluster". It is intentionally tiny: every pod refreshes
// the same key on its own cadence (see handler.presenceRefreshInterval),
// last-writer-wins is fine.
type Presence struct {
	rdb *redisbus.Client
	log *slog.Logger
}

func NewPresence(rdb *redisbus.Client, log *slog.Logger) *Presence {
	if log == nil {
		log = slog.Default()
	}
	return &Presence{rdb: rdb, log: log}
}

func presenceKey(userID int64) string {
	return fmt.Sprintf("presence:%d", userID)
}

// Refresh sets presence:<user_id> with PresenceTTL. Called once at WS
// upgrade and again on a ticker tighter than the TTL so the key never
// gaps for a live socket.
func (p *Presence) Refresh(ctx context.Context, userID int64) error {
	return p.rdb.SetEX(ctx, presenceKey(userID), "1", PresenceTTL)
}

// Drop removes the presence key on socket teardown. Best-effort; the
// TTL will reap it within 15s even if this fails.
func (p *Presence) Drop(ctx context.Context, userID int64) {
	if err := p.rdb.Del(ctx, presenceKey(userID)); err != nil {
		p.log.Debug("presence drop failed", "user_id", userID, "err", err)
	}
}
