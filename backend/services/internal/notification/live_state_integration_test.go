//go:build integration

package notification

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"shiptrip/pkg/wsproto"
)

// A neutral lifecycle refresh must traverse the actual Redis subscription and
// authenticated socket. Dispatch-only tests cannot catch an omitted channel.
func TestDealUpdatedReachesBothPartySockets(t *testing.T) {
	rdb, raw := itRedis(t)
	itStream(t, raw)
	hub := NewHub()
	srv := itServer(t, hub, NewPresence(rdb, discardLogger()))
	const senderID int64 = 4901
	const travelerID int64 = 4902
	sender := itDial(t, srv, senderID)
	traveler := itDial(t, srv, travelerID)
	receipts := &itReceipts{rdb: rdb}
	stop := itRunDispatcher(t, rdb, raw, hub, receipts)
	defer stop()
	for _, userID := range []int64{senderID, travelerID} {
		itWaitFor(t, "party socket registration", 5*time.Second, func() bool {
			return hub.Send(userID, wsproto.Envelope{Type: "it.probe"}) == 1
		})
	}
	readEnvelope(t, sender, 5*time.Second)
	readEnvelope(t, traveler, 5*time.Second)

	eventID := itEventID(t, "deal-refresh")
	body, err := json.Marshal(map[string]any{
		"event_id": eventID, "ts": time.Now().UTC().Format(time.RFC3339),
		"targets": []int64{senderID, travelerID},
		"deal_id": 71, "match_id": 72, "parcel_id": 73, "journey_id": 74,
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := rdb.Publish(context.Background(), "deal.updated", body); err != nil {
		t.Fatal(err)
	}
	for _, got := range []map[string]any{
		readEnvelope(t, sender, 5*time.Second),
		readEnvelope(t, traveler, 5*time.Second),
	} {
		if got["type"] != "deal.updated" || got["event_id"] != eventID {
			t.Fatalf("incorrect refresh envelope: %v", got)
		}
		payload, ok := got["payload"].(map[string]any)
		if !ok || payload["deal_id"] != float64(71) || payload["match_id"] != float64(72) {
			t.Fatalf("resource identity lost: %v", got)
		}
	}
}
