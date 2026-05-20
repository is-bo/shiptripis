package notification

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/coder/websocket"

	"shiptrip/pkg/auth"
	"shiptrip/pkg/wsproto"
)

// presenceRefreshInterval is how often the WS handler re-sets the
// presence:<uid> key for this connection. Must be < PresenceTTL (15s) so
// the key never gaps even if one refresh fails.
const presenceRefreshInterval = 5 * time.Second

// WSHandler returns an http.HandlerFunc that upgrades to WS, registers
// the connection with the hub + presence, and runs the read loop until
// the client disconnects or the parent context is cancelled.
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
) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		conn, err := wsproto.Upgrade(w, r, validator, log)
		if err != nil {
			// Upgrade already wrote the HTTP error.
			log.Debug("ws upgrade failed", "err", err)
			return
		}

		// Tie the connection lifetime to both the request ctx and the
		// service-level shutdown ctx. The request ctx alone is not enough:
		// some HTTP servers cancel it on upgrade completion.
		ctx, cancel := context.WithCancel(parentCtx)
		defer cancel()

		hub.Register(conn)
		if err := presence.Refresh(ctx, conn.UserID); err != nil {
			log.Warn("initial presence refresh failed",
				"user_id", conn.UserID, "err", err)
		}

		go refreshPresenceLoop(ctx, presence, conn)

		defer func() {
			hub.Unregister(conn)
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
