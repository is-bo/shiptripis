// Package chat implements the WS relay for chat.message.new and
// adjacent channels. V1 is a stateless relay — Django owns persistence
// via chat_message (Claude A scope), publishes after commit, this
// service fans the event to the recipient's local WS.
//
// Why not reuse notification's Hub directly? Same shape, separate
// lifecycle. Importing notification.Hub would entangle a chat pod
// shutdown with notification's presence loop and complicate the
// CLAUDE.md §3 connection-pool budget (chat would inherit notif's
// import surface). Mirroring the small struct is cheaper than the
// abstraction tax. If a third service emerges with the same pattern,
// then extract pkg/wshub.
package chat

import (
	"sync"

	"shiptrip/pkg/wsproto"
)

// Hub tracks every WS connection owned by *this* pod, keyed by user_id.
// Multi-device users (phone + tablet) get a set of sockets per user;
// Send fans to all of them. Cross-pod fan-out is Redis pub/sub — every
// pod subscribes, every pod calls Hub.Send, only the pod holding the
// socket actually writes.
type Hub struct {
	mu    sync.RWMutex
	conns map[int64]map[*wsproto.Conn]struct{}
}

func NewHub() *Hub {
	return &Hub{conns: make(map[int64]map[*wsproto.Conn]struct{})}
}

// Register adds a connection. Safe to call from the WS handler goroutine.
func (h *Hub) Register(c *wsproto.Conn) {
	h.mu.Lock()
	defer h.mu.Unlock()
	set, ok := h.conns[c.UserID]
	if !ok {
		set = make(map[*wsproto.Conn]struct{}, 1)
		h.conns[c.UserID] = set
	}
	set[c] = struct{}{}
}

// Unregister removes a connection. Idempotent.
func (h *Hub) Unregister(c *wsproto.Conn) {
	h.mu.Lock()
	defer h.mu.Unlock()
	set, ok := h.conns[c.UserID]
	if !ok {
		return
	}
	delete(set, c)
	if len(set) == 0 {
		delete(h.conns, c.UserID)
	}
}

// Send fans an envelope to every socket this pod holds for userID.
// Returns the number of sockets the envelope was queued to. Callers use
// this to decide whether the user is locally present (vs another pod or
// offline entirely).
//
// Sending is non-blocking — wsproto.Conn.Send drops on per-conn overflow.
func (h *Hub) Send(userID int64, env wsproto.Envelope) int {
	h.mu.RLock()
	set := h.conns[userID]
	conns := make([]*wsproto.Conn, 0, len(set))
	for c := range set {
		conns = append(conns, c)
	}
	h.mu.RUnlock()

	for _, c := range conns {
		c.Send(env)
	}
	return len(conns)
}
