package chat

import (
	"context"
	"log/slog"
	"net/http"

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
// V1 is server→client only — Django's REST handler is still the write
// path for chat messages. Inbound frames are read so the library can
// process pong control frames; any envelope is logged and dropped.
func WSHandler(
	parentCtx context.Context,
	validator *auth.Validator,
	hub *Hub,
	log *slog.Logger,
) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		conn, err := wsproto.Upgrade(w, r, validator, log)
		if err != nil {
			log.Debug("chat ws upgrade failed", "err", err)
			return
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
