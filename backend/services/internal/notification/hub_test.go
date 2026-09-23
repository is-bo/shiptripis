package notification

import (
	"testing"

	"shiptrip/pkg/wsproto"
)

func TestHubStatsCountSocketsUsersAndConnects(t *testing.T) {
	h := NewHub()
	phone, tablet, other := &wsproto.Conn{UserID: 1}, &wsproto.Conn{UserID: 1}, &wsproto.Conn{UserID: 2}
	h.Register(phone)
	h.Register(tablet)
	h.Register(other)
	h.Register(phone) // a repeated Register is not a new connection

	if sockets, users, connects := h.Stats(); sockets != 3 || users != 2 || connects != 3 {
		t.Fatalf("Stats() = %d sockets, %d users, %d connects; want 3, 2, 3", sockets, users, connects)
	}

	h.Unregister(phone)
	h.Unregister(phone) // idempotent
	h.Unregister(other)
	if sockets, users, connects := h.Stats(); sockets != 1 || users != 1 || connects != 3 {
		t.Fatalf("after disconnects Stats() = %d, %d, %d; want 1, 1, 3", sockets, users, connects)
	}
}
