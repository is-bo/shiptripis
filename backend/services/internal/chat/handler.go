package chat

import (
	"context"
	"log/slog"
	"net/http"
	"sync"

	"github.com/coder/websocket"

	"shiptrip/pkg/auth"
	"shiptrip/pkg/wsproto"
)

// WSHandler returns an http.HandlerFunc that upgrades to WS and
// registers the connection with the chat Hub. Unlike the notification
// handler this does NOT run a presence refresh loop — presence keys
// (presence:<user_id>) are owned by the notification service. If a
// user has a chat WS but no notification WS, FCM will incorrectly push
// for chat events; that's acceptable for V1 since chat traffic is
// rare enough that the duplicate notification is the lesser problem
// vs. wiring a second presence refresher with TTL coordination.
//
// connWG tracks in-flight handler goroutines so main can drain them on
// shutdown before tearing down Redis/Postgres (hijacked WS conns are
// invisible to http.Server.Shutdown). Pass nil to opt out (tests).
//
// V1 is server→client only — Django's REST handler is still the write
// path for chat messages. Inbound frames are read so the library can
// process pong control frames; any envelope is logged and dropped.
func WSHandler(
	parentCtx context.Context,
	validator *auth.Validator,
	hub *Hub,
	log *slog.Logger,
	connWG *sync.WaitGroup,
) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		conn, err := wsproto.Upgrade(w, r, validator, log)
		if err != nil {
			log.Debug("chat ws upgrade failed", "err", err)
			return
		}

		// Track this handler for shutdown draining. Add only after a
		// successful upgrade so a rejected handshake doesn't skew the count.
		if connWG != nil {
			connWG.Add(1)
			defer connWG.Done()
		}

		ctx, cancel := context.WithCancel(parentCtx)
		defer cancel()

		hub.Register(conn)
		defer func() {
			hub.Unregister(conn)
			conn.Close(websocket.StatusNormalClosure, "bye")
		}()

		for {
			env, err := conn.Read(ctx)
			if err != nil {
				log.Debug("chat ws read loop exit",
					"user_id", conn.UserID, "err", err)
				return
			}
			log.Debug("chat ws inbound envelope dropped",
				"user_id", conn.UserID, "type", env.Type)
		}
	}
}
