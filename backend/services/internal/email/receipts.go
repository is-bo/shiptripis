package email

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// ReceiptStore is the durable acknowledgement boundary between SMTP and the
// Django outbox. An email stream entry is acknowledged only after the matching
// core_published_event row records delivery.
type ReceiptStore interface {
	Delivered(ctx context.Context, eventID string) (bool, error)
	MarkDelivered(ctx context.Context, eventID string) error
}

type noopReceiptStore struct{}

func (noopReceiptStore) Delivered(context.Context, string) (bool, error) { return false, nil }
func (noopReceiptStore) MarkDelivered(context.Context, string) error     { return nil }

type DeliveryPolicy struct {
	ActivationNotBefore time.Time
	RateLimitPerMinute  int
}
type postgresReceiptStore struct {
	pool   *pgxpool.Pool
	policy DeliveryPolicy
}

// NewPostgresReceiptStore builds the production receipt store. The pool is
// owned by cmd/email and outlives every consumer handler.
func NewPostgresReceiptStore(pool *pgxpool.Pool, policies ...DeliveryPolicy) (ReceiptStore, error) {
	if pool == nil {
		return nil, errors.New("email: PostgreSQL receipt pool is required")
	}
	policy := DeliveryPolicy{RateLimitPerMinute: 60}
	if len(policies) > 0 {
		policy = policies[0]
	}
	return &postgresReceiptStore{pool: pool, policy: policy}, nil
}

// Deliver is the production last-mile guard. PostgreSQL owns exclusion, rate
// budget, retry scheduling and terminal failures; Redis remains a wake-up hint.
// false means keep the PEL entry for recovery; true means it is safe to ACK.
func (s *postgresReceiptStore) Deliver(ctx context.Context, p EmailPayload, send func() error) (bool, error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return false, errors.New("email: database unavailable")
	}
	// Keep rollback inside the handler's deadline. pgx discards the connection
	// if rollback cannot complete, releasing the server-side transaction lock.
	defer tx.Rollback(ctx)
	var locked bool
	if err = tx.QueryRow(ctx, "SELECT pg_try_advisory_xact_lock(877431106)").Scan(&locked); err != nil {
		return false, errors.New("email: lock unavailable")
	}
	if !locked {
		return false, nil
	}
	var id int64
	var status, recipient, kind, lastError string
	var created time.Time
	var reviewed, next *time.Time
	var attempts, maxAttempts int
	var rawContext []byte
	err = tx.QueryRow(ctx, `SELECT id,status,to_email,kind,created_at,activation_reviewed_at,next_attempt_at,last_error,attempts,max_attempts,context
	 FROM notification_outbound_message WHERE transport_event_id=$1 FOR UPDATE`, p.EventID).Scan(
		&id, &status, &recipient, &kind, &created, &reviewed, &next, &lastError, &attempts, &maxAttempts, &rawContext)
	if errors.Is(err, pgx.ErrNoRows) {
		return true, nil
	} // orphan legacy stream work is never sent
	if err != nil {
		return false, errors.New("email: obligation unavailable")
	}
	if status != "pending" || recipient != p.To || kind != p.Kind {
		return true, nil
	}
	switch kind {
	case "email_verification", "password_reset", "admin_invitation", "recipient_delivery_code":
		return true, nil // these obligations belong to Django's trusted SMTP path
	}
	if (reviewed == nil || reviewed.Before(time.Now().Add(-24*time.Hour))) && ((!s.policy.ActivationNotBefore.IsZero() && created.Before(s.policy.ActivationNotBefore)) || created.Before(time.Now().Add(-48*time.Hour))) {
		return true, nil
	}
	var accepted bool
	err = tx.QueryRow(ctx, "SELECT delivered_at IS NOT NULL FROM core_published_event WHERE event_id=$1", p.EventID).Scan(&accepted)
	if err != nil {
		return false, errors.New("email: receipt unavailable")
	}
	if accepted {
		return true, nil
	}
	if kind == "protection_ending" {
		var facts struct {
			Deadline string `json:"protection_ends_at"`
		}
		parseErr := json.Unmarshal(rawContext, &facts)
		deadline, timeErr := time.Parse(time.RFC3339Nano, facts.Deadline)
		if parseErr != nil || timeErr != nil || !deadline.After(time.Now()) {
			_, err = tx.Exec(ctx, `UPDATE notification_outbound_message SET status='failed',last_error='email_notice_expired',next_attempt_at=NULL,updated_at=now() WHERE id=$1`, id)
			if err != nil {
				return false, errors.New("email: expiry outcome persistence failed")
			}
			if err = tx.Commit(ctx); err != nil {
				return false, errors.New("email: expiry outcome commit failed")
			}
			return true, nil
		}
	}
	if lastError != "" && next != nil && next.After(time.Now()) {
		return true, nil
	}
	var used int
	err = tx.QueryRow(ctx, `SELECT count(*) FROM notification_outbound_message WHERE
	 dispatched_at >= now()-interval '1 minute' OR (last_error IN ('smtp_transient','smtp_permanent') AND updated_at >= now()-interval '1 minute')`).Scan(&used)
	if err != nil {
		return false, errors.New("email: rate budget unavailable")
	}
	if used >= s.policy.RateLimitPerMinute {
		return false, nil
	}
	sendErr := send()
	if sendErr == nil {
		_, err = tx.Exec(ctx, "UPDATE core_published_event SET delivered_at=COALESCE(delivered_at,now()) WHERE event_id=$1", p.EventID)
		if err == nil {
			_, err = tx.Exec(ctx, `UPDATE notification_outbound_message SET status='dispatched', dispatched_at=now(),last_error='',next_attempt_at=NULL,updated_at=now() WHERE id=$1`, id)
		}
	} else {
		_, permanent := AsPermanent(sendErr)
		state, failure := "pending", "smtp_transient"
		if permanent || attempts >= maxAttempts {
			state = "failed"
		}
		if permanent {
			failure = "smtp_permanent"
		}
		delay := min(60*(1<<min(max(attempts-1, 0), 9)), 21600)
		_, err = tx.Exec(ctx, `UPDATE notification_outbound_message SET status=$2,last_error=$3,
		 next_attempt_at=CASE WHEN $2::varchar='failed' THEN NULL ELSE now()+make_interval(secs=>$4::double precision) END,updated_at=now() WHERE id=$1`, id, state, failure, delay)
	}
	if err != nil {
		return false, errors.New("email: outcome persistence failed")
	}
	if err = tx.Commit(ctx); err != nil {
		return false, errors.New("email: outcome commit failed")
	}
	return true, sendErr
}

func (s *postgresReceiptStore) Delivered(ctx context.Context, eventID string) (bool, error) {
	if eventID == "" {
		return false, errors.New("email: receipt event id is required")
	}
	var delivered bool
	err := s.pool.QueryRow(ctx,
		`SELECT delivered_at IS NOT NULL
		   FROM core_published_event
		  WHERE event_id = $1`,
		eventID,
	).Scan(&delivered)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, fmt.Errorf("email: published event %s does not exist", eventID)
	}
	if err != nil {
		return false, fmt.Errorf("email: read delivery receipt: %w", err)
	}
	return delivered, nil
}

func (s *postgresReceiptStore) MarkDelivered(ctx context.Context, eventID string) error {
	if eventID == "" {
		return errors.New("email: receipt event id is required")
	}
	tag, err := s.pool.Exec(ctx,
		`UPDATE core_published_event
		    SET delivered_at = COALESCE(delivered_at, now())
		  WHERE event_id = $1`,
		eventID,
	)
	if err != nil {
		return fmt.Errorf("email: write delivery receipt: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return fmt.Errorf("email: published event %s does not exist", eventID)
	}
	return nil
}
