// Package notification implements the WS fan-out + presence + delivery-receipt
// loop described in CLAUDE.md §2 G1.
//
// The dispatcher subscribes to all 16 Django channels (see
// dispatcher.subscribeChannels, mirroring monolith/apps/core/channels.py)
// and routes generically: every envelope carries targets:[uid,...] from
// redis_bus.publish_after_commit, and the raw payload is fanned to each
// target's local sockets. FCM push fallback is implemented in fcm.go and
// gated behind FCM_ENABLED until the fcm_token schema + Django publisher land.
package notification

import (
	"sync"

	"shiptrip/pkg/wsproto"
)

// Hub tracks every WS connection owned by *this* pod, keyed by user_id.
// A user may have multiple sockets (phone + tablet, or a reconnect race);
// Send fans to all of them.
//
// Hub is per-pod; cross-pod fan-out is what Redis pub/sub gives us — every
// pod subscribes, every pod calls Hub.Send, only the pod holding the socket
// actually writes. This is the "multi-pod presence" half of G1.
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
// Returns the number of sockets the envelope was queued to; callers use
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
