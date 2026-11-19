//go:build integration

package email

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"shiptrip/pkg/redisbus"
)

func emailDatabase(t *testing.T) *pgxpool.Pool {
	t.Helper()
	raw := os.Getenv("EMAIL_TEST_DATABASE_URL")
	if raw == "" {
		t.Skip("EMAIL_TEST_DATABASE_URL requires a disposable migrated local database")
	}
	endpoint, err := url.Parse(raw)
	if err != nil || endpoint.Hostname() != "127.0.0.1" || endpoint.Path != "/wacla" {
		t.Fatal("email tests require the disposable loopback wacla database")
	}
	pool, err := pgxpool.New(context.Background(), raw)
	if err != nil {
		t.Fatal("cannot connect to local fixture")
	}
	t.Cleanup(pool.Close)
	return pool
}

func guardedObligation(t *testing.T, pool *pgxpool.Pool) EmailPayload {
	t.Helper()
	ctx := context.Background()
	event := uuid.NewString()
	p := EmailPayload{EventID: event, To: "only@example.invalid", Kind: "kyc_status", Subject: "Waçla", Body: "Local test", HTML: "<p>Local test</p>"}
	_, err := pool.Exec(ctx, `INSERT INTO notification_outbound_message
 (key,kind,channel,to_email,context,language,secret_ref,status,attempts,max_attempts,last_error,transport_event_id,created_at,updated_at,next_attempt_at)
 VALUES ($1,$2,'email',$3,'{}','en','','pending',1,3,'',$1,now(),now(),now()+interval '2 minutes')`, event, p.Kind, p.To)
	if err != nil {
		t.Fatal(err)
	}
	_, err = pool.Exec(ctx, `INSERT INTO core_published_event (id,event_id,channel,payload_hash,published_at) VALUES ($1,$2,'email:send',$3,now())`, uuid.New(), event, fmt.Sprintf("%064d", 0))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		pool.Exec(ctx, "DELETE FROM notification_outbound_message WHERE key=$1", event)
		pool.Exec(ctx, "DELETE FROM core_published_event WHERE event_id=$1", event)
	})
	return p
}

func guardStore(t *testing.T, pool *pgxpool.Pool, policy DeliveryPolicy) *postgresReceiptStore {
	t.Helper()
	store, err := NewPostgresReceiptStore(pool, policy)
	if err != nil {
		t.Fatal(err)
	}
	return store.(*postgresReceiptStore)
}

func TestPostgresSMTPAcceptanceSurvivesWorkerRestartAndDuplicateEntries(t *testing.T) {
	pool := emailDatabase(t)
	p := guardedObligation(t, pool)
	store := guardStore(t, pool, DeliveryPolicy{RateLimitPerMinute: 60})
	var accepted atomic.Int32
	host, port := fakeSMTPWith(t, "250 ok", "250 ok", &accepted)
	sender, err := NewSMTPSender(SMTPConfig{Host: host, Port: port, FromAddr: "notifications@example.invalid", FromName: "Waçla", ReplyTo: "support@example.invalid"}, discardLog())
	if err != nil {
		t.Fatal(err)
	}
	ack, err := store.Deliver(context.Background(), p, func() error { return sender.Send(context.Background(), p) })
	if !ack || err != nil {
		t.Fatalf("send: %v %v", ack, err)
	}
	restarted := guardStore(t, pool, DeliveryPolicy{RateLimitPerMinute: 60})
	ack, err = restarted.Deliver(context.Background(), p, func() error { t.Fatal("duplicate SMTP send"); return nil })
	if !ack || err != nil || accepted.Load() != 1 {
		t.Fatalf("restart: %v %v, accepted %d", ack, err, accepted.Load())
	}
	var status string
	pool.QueryRow(context.Background(), "SELECT status FROM notification_outbound_message WHERE transport_event_id=$1", p.EventID).Scan(&status)
	if status != "dispatched" {
		t.Fatal(status)
	}
}

func TestPostgresSMTPFailuresAndBackoffAreDurable(t *testing.T) {
	for _, reply := range []string{"451 temporary", "550 permanent"} {
		t.Run(reply, func(t *testing.T) {
			pool := emailDatabase(t)
			p := guardedObligation(t, pool)
			store := guardStore(t, pool, DeliveryPolicy{RateLimitPerMinute: 60})
			host, port := fakeSMTP(t, reply)
			sender, _ := NewSMTPSender(SMTPConfig{Host: host, Port: port, FromAddr: "notifications@example.invalid"}, discardLog())
			ack, err := store.Deliver(context.Background(), p, func() error { return sender.Send(context.Background(), p) })
			if !ack || err == nil {
				t.Fatalf("failure: %v %v", ack, err)
			}
			var status, safeError string
			pool.QueryRow(context.Background(), "SELECT status,last_error FROM notification_outbound_message WHERE transport_event_id=$1", p.EventID).Scan(&status, &safeError)
			expected, expectedError := "pending", "provider_transient"
			if reply[0] == '5' {
				expected, expectedError = "failed", "provider_permanent"
			}
			if status != expected || safeError != expectedError {
				t.Fatal(status, safeError)
			}
			store.Deliver(context.Background(), p, func() error { t.Fatal("failure bypassed retry gate"); return nil })
			if expected == "pending" {
				pool.Exec(context.Background(), "UPDATE notification_outbound_message SET next_attempt_at=now(),attempts=2 WHERE transport_event_id=$1", p.EventID)
				ack, err = store.Deliver(context.Background(), p, func() error { return nil })
				if !ack || err != nil {
					t.Fatal("retry did not recover", ack, err)
				}
			}
		})
	}
}

func TestPostgresConcurrentWorkersCannotOverlapSMTP(t *testing.T) {
	pool := emailDatabase(t)
	p := guardedObligation(t, pool)
	store := guardStore(t, pool, DeliveryPolicy{RateLimitPerMinute: 60})
	entered, release, done := make(chan struct{}), make(chan struct{}), make(chan struct{})
	go func() {
		defer close(done)
		store.Deliver(context.Background(), p, func() error { close(entered); <-release; return nil })
	}()
	<-entered
	ack, err := store.Deliver(context.Background(), p, func() error { t.Error("concurrent send"); return nil })
	close(release)
	<-done
	if ack || err != nil {
		t.Fatal("busy entry must stay pending", ack, err)
	}
}

func TestPostgresActivationCancellationAndRateGates(t *testing.T) {
	pool := emailDatabase(t)
	p := guardedObligation(t, pool)
	blocked := func() error { t.Error("send gate bypassed"); return nil }
	cutoff := time.Now().Add(time.Minute)
	store := guardStore(t, pool, DeliveryPolicy{ActivationNotBefore: cutoff, RateLimitPerMinute: 1})
	if ack, err := store.Deliver(context.Background(), p, blocked); !ack || err != nil {
		t.Fatal(ack, err)
	}
	pool.Exec(context.Background(), "UPDATE notification_outbound_message SET activation_reviewed_at=now() WHERE transport_event_id=$1", p.EventID)
	if ack, err := store.Deliver(context.Background(), p, func() error { return nil }); !ack || err != nil {
		t.Fatal(ack, err)
	}
	next := guardedObligation(t, pool)
	pool.Exec(context.Background(), "UPDATE notification_outbound_message SET activation_reviewed_at=now() WHERE transport_event_id=$1", next.EventID)
	if ack, err := store.Deliver(context.Background(), next, blocked); ack || err != nil {
		t.Fatal("rate gate", ack, err)
	}
	pool.Exec(context.Background(), "UPDATE notification_outbound_message SET status='cancelled' WHERE transport_event_id=$1", next.EventID)
	if ack, err := store.Deliver(context.Background(), next, blocked); !ack || err != nil {
		t.Fatal("cancel gate", ack, err)
	}
}

func TestPostgresWorkerCrashReleasesUncommittedSendClaim(t *testing.T) {
	pool := emailDatabase(t)
	p := guardedObligation(t, pool)
	store := guardStore(t, pool, DeliveryPolicy{RateLimitPerMinute: 60})
	func() {
		defer func() { recover() }()
		store.Deliver(context.Background(), p, func() error { panic("simulated worker crash before SMTP") })
	}()
	restarted := guardStore(t, pool, DeliveryPolicy{RateLimitPerMinute: 60})
	if ack, err := restarted.Deliver(context.Background(), p, func() error { return nil }); !ack || err != nil {
		t.Fatal(ack, err)
	}
}

func TestPostgresRejectsProtectionReminderThatExpiredInRedis(t *testing.T) {
	pool := emailDatabase(t)
	p := guardedObligation(t, pool)
	p.Kind = "protection_ending"
	_, err := pool.Exec(context.Background(), `UPDATE notification_outbound_message SET kind=$2,context='{"protection_ends_at":"2020-01-01T00:00:00Z"}' WHERE transport_event_id=$1`, p.EventID, p.Kind)
	if err != nil {
		t.Fatal(err)
	}
	store := guardStore(t, pool, DeliveryPolicy{RateLimitPerMinute: 60})
	ack, err := store.Deliver(context.Background(), p, func() error { t.Fatal("expired reminder sent"); return nil })
	if !ack || err != nil {
		t.Fatal(ack, err)
	}
	var state string
	pool.QueryRow(context.Background(), "SELECT status FROM notification_outbound_message WHERE transport_event_id=$1", p.EventID).Scan(&state)
	if state != "failed" {
		t.Fatal("expired reminder was not recorded")
	}
}

type pacedSender struct{ sender EmailSender }

func (s pacedSender) Send(ctx context.Context, p EmailPayload) error {
	time.Sleep(20 * time.Millisecond) // force overlap if batch handlers race
	return s.sender.Send(ctx, p)
}

func TestPostgresSMTPBurstDoesNotDeferMostOfTheBatchToRecovery(t *testing.T) {
	pool := emailDatabase(t)
	store := guardStore(t, pool, DeliveryPolicy{RateLimitPerMinute: 60})
	var accepted atomic.Int32
	host, port := fakeSMTPWith(t, "250 ok", "250 ok", &accepted)
	sender, err := NewSMTPSender(SMTPConfig{Host: host, Port: port, FromAddr: "notifications@example.invalid"}, discardLog())
	if err != nil {
		t.Fatal(err)
	}
	c := NewConsumer(nil, ConsumerConfig{Sender: pacedSender{sender}, Receipts: store}, discardLog())
	c.rdb = &fakeStream{}
	for n := range 20 {
		p := guardedObligation(t, pool)
		payload, _ := json.Marshal(p)
		if !c.dispatchHandle(context.Background(), redisbus.StreamMessage{ID: sid(n), Values: map[string]any{"payload": string(payload)}}) {
			t.Fatal("dispatch refused")
		}
	}
	c.wg.Wait()
	if accepted.Load() != 20 {
		t.Fatalf("only %d of 20 queued messages sent; batch was left waiting for recovery", accepted.Load())
	}
}

// The Sender.net API sender writes the same durable outcomes through the
// PostgreSQL guard as SMTP: 422 fails the obligation, 503 keeps it pending
// with backoff, and an accepted send records the receipt once.
func TestPostgresSenderNetOutcomesAreDurable(t *testing.T) {
	for _, tc := range []struct {
		status            int
		answer            string
		wantStatus, wantE string
	}{
		{200, accepted, "dispatched", ""},
		{422, `{"message": "invalid"}`, "failed", "provider_permanent"},
		{503, ``, "pending", "provider_transient"},
	} {
		t.Run(fmt.Sprint(tc.status), func(t *testing.T) {
			pool := emailDatabase(t)
			p := guardedObligation(t, pool)
			store := guardStore(t, pool, DeliveryPolicy{RateLimitPerMinute: 60})
			api := &senderNetAPI{status: tc.status, answer: tc.answer}
			sender := newSenderNetTest(t, api, SenderNetConfig{})
			ack, err := store.Deliver(context.Background(), p, func() error { return sender.Send(context.Background(), p) })
			if !ack || (err == nil) != (tc.wantE == "") {
				t.Fatalf("deliver: ack %v err %v", ack, err)
			}
			var status, safeError string
			pool.QueryRow(context.Background(), "SELECT status,last_error FROM notification_outbound_message WHERE transport_event_id=$1", p.EventID).Scan(&status, &safeError)
			if status != tc.wantStatus || safeError != tc.wantE {
				t.Fatal(status, safeError)
			}
			store.Deliver(context.Background(), p, func() error { t.Fatal("outcome bypassed the guard"); return nil })
			if api.hits.Load() != 1 {
				t.Fatalf("API called %d times", api.hits.Load())
			}
		})
	}
}
