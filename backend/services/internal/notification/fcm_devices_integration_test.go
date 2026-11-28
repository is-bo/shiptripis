//go:build integration

package notification

import (
	"context"
	"os"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// notificationDatabase is a transaction on a database loaded with
// contracts/sql/schema.sql, rolled back when the test ends. Foreign keys are
// deferred, so a device row needs no account or sign-in row.
func notificationDatabase(t *testing.T) pgx.Tx {
	t.Helper()
	raw := os.Getenv("NOTIFICATION_TEST_DATABASE_URL")
	if raw == "" {
		t.Skip("NOTIFICATION_TEST_DATABASE_URL requires a database loaded with schema.sql")
	}
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, raw)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	tx, err := conn.Begin(ctx)
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	t.Cleanup(func() {
		_ = tx.Rollback(ctx)
		_ = conn.Close(ctx)
	})
	return tx
}

// N1, N-F: the worker's last check against the row as it is now. A push
// belongs to the sign-in that registered the device when it was queued.
func TestPostgresDevicesKeepAPushToItsSignIn(t *testing.T) {
	tx := notificationDatabase(t)
	ctx := context.Background()
	signIn, fingerprint := uuid.NewString(), strings.Repeat("f", 64)
	var id int64
	if err := tx.QueryRow(ctx, `INSERT INTO notification_push_device
 (provider, platform, installation_id, token, token_fingerprint, app_version, active,
  last_seen_at, created_at, updated_at, user_id, binding_sequence, session_id)
 VALUES ('fcm', 'android', $1, 'token', $2, '', true, now(), now(), now(), 7, 1, $3)
 RETURNING id`, uuid.New(), fingerprint, signIn).Scan(&id); err != nil {
		t.Fatalf("insert device: %v", err)
	}
	queued := FCMPayload{
		UserID: 7, DeviceIDs: []int64{id},
		TokenFingerprints: []string{fingerprint}, SessionIDs: []string{signIn},
	}

	for _, tc := range []struct {
		name   string
		change string
		bound  bool
	}{
		{"unchanged", "", true},
		{"a new sign-in of the same member, same token", "session_id = gen_random_uuid()", false},
		{"another member, same token", "user_id = 8, session_id = gen_random_uuid()", false},
		{"switched off", "active = false", false},
		{"the token rotated", "token_fingerprint = repeat('g', 64)", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			step, err := tx.Begin(ctx)
			if err != nil {
				t.Fatalf("savepoint: %v", err)
			}
			defer func() { _ = step.Rollback(ctx) }()
			if tc.change != "" {
				if _, err := step.Exec(ctx, "UPDATE notification_push_device SET "+tc.change+" WHERE id = $1", id); err != nil {
					t.Fatalf("change: %v", err)
				}
			}
			bound, err := PostgresDevices{DB: step}.StillBound(ctx, queued)
			if err != nil {
				t.Fatalf("StillBound: %v", err)
			}
			if len(bound) != 1 || bound[0] != tc.bound {
				t.Fatalf("bound = %v, want [%v]", bound, tc.bound)
			}
		})
	}
}
