package notification

import (
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"testing"
)

// djangoChannelsPath is the canonical channel vocabulary Django publishes on
// (see the subscribeChannels comment). Relative to this package directory.
var djangoChannelsPath = filepath.Join("..", "..", "..", "monolith", "apps", "core", "channels.py")

// channelConst matches a module-level `NAME = "domain.event"` assignment.
var channelConst = regexp.MustCompile(`(?m)^[A-Z][A-Z0-9_]* = "([a-z_]+\.[a-z_.]+)"`)

// TestSubscribeChannelsMatchDjango keeps subscribeChannels in lockstep with
// apps/core/channels.py. A channel Django publishes but this service does not
// subscribe to never reaches a live socket: the inbox row and FCM still land,
// so nothing errors, and the miss stays invisible. That is how the three I1A
// deal.arrival_* channels went unsubscribed. chat.message.new belongs to the
// chat relay and is the only channel this service leaves out.
func TestSubscribeChannelsMatchDjango(t *testing.T) {
	raw, err := os.ReadFile(djangoChannelsPath)
	if err != nil {
		t.Fatalf("read %s: %v", djangoChannelsPath, err)
	}
	var django []string
	for _, m := range channelConst.FindAllStringSubmatch(string(raw), -1) {
		if m[1] != channelChatNew {
			django = append(django, m[1])
		}
	}
	if len(django) < 20 {
		t.Fatalf("parsed only %d channels from channels.py; the parser no longer matches the file", len(django))
	}

	for _, ch := range django {
		if !slices.Contains(subscribeChannels, ch) {
			t.Errorf("Django publishes %q but the notification dispatcher does not subscribe to it", ch)
		}
	}
	for _, ch := range subscribeChannels {
		if !slices.Contains(django, ch) {
			t.Errorf("subscribed to %q, which apps/core/channels.py does not define", ch)
		}
	}
}

// channelChatNew is owned by the chat relay (internal/chat).
const channelChatNew = "chat.message.new"
