package email

import (
	"context"
	"errors"
	"fmt"

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

type postgresReceiptStore struct{ pool *pgxpool.Pool }

// NewPostgresReceiptStore builds the production receipt store. The pool is
// owned by cmd/email and outlives every consumer handler.
func NewPostgresReceiptStore(pool *pgxpool.Pool) (ReceiptStore, error) {
	if pool == nil {
		return nil, errors.New("email: PostgreSQL receipt pool is required")
	}
	return &postgresReceiptStore{pool: pool}, nil
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
