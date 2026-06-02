package notification

import (
	"context"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"github.com/coder/websocket"

	"shiptrip/pkg/auth"
	"shiptrip/pkg/metrics"
	"shiptrip/pkg/wsproto"
)

// presenceRefreshInterval is how often the WS handler re-sets the
// presence:<uid> key for this connection. Must be < PresenceTTL (15s) so
// the key never gaps even if one refresh fails.
const presenceRefreshInterval = 5 * time.Second

// initialPresenceRetryDelay is the gap before retrying the very first
// presence.Refresh on a new WS connection. If both attempts fail we
// proceed with the upgrade anyway — the per-tick refresh loop will
// rehydrate the key within 5s and Django doesn't gate any user-visible
// flow on presence (FCM fallback covers the gap). We log + meter the
// failure so a Redis brown-out is visible without burning sockets.
const initialPresenceRetryDelay = 50 * time.Millisecond

// WSHandler returns an http.HandlerFunc that upgrades to WS, registers
// the connection with the hub + presence, and runs the read loop until
// the client disconnects or the parent context is cancelled.
//
// connWG tracks in-flight handler goroutines so main can wait for them to
// finish their presence.Drop before tearing down Redis/Postgres on
// shutdown. Hijacked WS conns are invisible to http.Server.Shutdown, so
// without this the deferred rdb.Close()/pool.Close() could race a Drop
// still in flight. Pass nil to opt out (tests).
//
// The Flutter client speaks a one-way channel for now: server → client
// only. Inbound frames are read so the library can process pong control
// frames and surface close errors; any unexpected envelope is logged
// and dropped.
func WSHandler(
	parentCtx context.Context,
	validator *auth.Validator,
	hub *Hub,
	presence *Presence,
	log *slog.Logger,
	m *metrics.Group,
	connWG *sync.WaitGroup,
) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		conn, err := wsproto.Upgrade(w, r, validator, log)
		if err != nil {
			// Upgrade already wrote the HTTP error.
			log.Debug("ws upgrade failed", "err", err)
			return
		}

		// Track this handler for shutdown draining. Add only after a
		// successful upgrade so a rejected handshake doesn't skew the count.
		if connWG != nil {
			connWG.Add(1)
			defer connWG.Done()
		}

		// Tie the connection lifetime to both the request ctx and the
		// service-level shutdown ctx. The request ctx alone is not enough:
		// some HTTP servers cancel it on upgrade completion.
		ctx, cancel := context.WithCancel(parentCtx)
		defer cancel()

		hub.Register(conn)
		// One retry on the initial presence write. A first-tick failure
		// would otherwise leave the user with a live WS but no
		// presence:<uid> key — the FCM consumer would then push a
		// duplicate for ~5s until the periodic loop catches up.
		if err := presence.Refresh(ctx, conn.UserID); err != nil {
			if m != nil {
				m.Counter("presence_refresh_failures_total", 1)
			}
			log.Warn("initial presence refresh failed (retrying)",
				"user_id", conn.UserID, "err", err)
			select {
			case <-ctx.Done():
			case <-time.After(initialPresenceRetryDelay):
				if err := presence.Refresh(ctx, conn.UserID); err != nil {
					if m != nil {
						m.Counter("presence_refresh_failures_final_total", 1)
					}
					log.Error("initial presence refresh failed after retry",
						"user_id", conn.UserID, "err", err)
				}
			}
		}

		var wg sync.WaitGroup
		wg.Go(func() {
			refreshPresenceLoop(ctx, presence, conn)
		})

		defer func() {
			hub.Unregister(conn)
			// Cancel the refresh loop and wait for it before issuing Drop,
			// so a hung Redis refresh can't outlive the handler.
			cancel()
			wg.Wait()
			// Use a short detached ctx — parent may already be cancelled
			// during graceful shutdown, but the DEL should still fire.
			dropCtx, dropCancel := context.WithTimeout(context.Background(), 2*time.Second)
			presence.Drop(dropCtx, conn.UserID)
			dropCancel()
			conn.Close(websocket.StatusNormalClosure, "bye")
		}()

		for {
			env, err := conn.Read(ctx)
			if err != nil {
				log.Debug("ws read loop exit",
					"user_id", conn.UserID, "err", err)
				return
			}
			// V1 is server→client only. Log and drop anything inbound so
			// a chatty client can't fill logs at error level.
			log.Debug("ws inbound envelope dropped",
				"user_id", conn.UserID, "type", env.Type)
		}
	}
}

func refreshPresenceLoop(ctx context.Context, p *Presence, conn *wsproto.Conn) {
	t := time.NewTicker(presenceRefreshInterval)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-conn.Done():
			return
		case <-t.C:
			// Detached short ctx per tick: during graceful shutdown the
			// parent ctx is already cancelled, but the presence key SHOULD
			// still be refreshed (Drop runs on disconnect, not on signal —
			// the socket may keep serving until the WS read returns).
			// Mirrors the Drop pattern at handler.go:61-63.
			rctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
			_ = p.Refresh(rctx, conn.UserID)
			cancel()
		}
	}
}
