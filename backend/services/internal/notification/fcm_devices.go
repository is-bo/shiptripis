package notification

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// stillBoundQuery reads the devices of a queued push that are still switched
// on for its recipient. Django owns the table (apps.notifications.PushDevice).
const stillBoundQuery = `SELECT id, token_fingerprint, session_id::text FROM notification_push_device
WHERE user_id = $1 AND active AND id = ANY($2)`

// PostgresDevices is the DeviceRegistry over the Django database.
type PostgresDevices struct {
	// DB is the pool in production; a test passes a transaction.
	DB interface {
		Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	}
}

type boundDevice struct {
	fingerprint string
	session     string
}

func (d PostgresDevices) StillBound(ctx context.Context, p FCMPayload) ([]bool, error) {
	if len(p.TokenFingerprints) != len(p.DeviceIDs) || len(p.SessionIDs) != len(p.DeviceIDs) {
		return nil, fmt.Errorf("device check: %d fingerprints and %d sign-ins for %d devices",
			len(p.TokenFingerprints), len(p.SessionIDs), len(p.DeviceIDs))
	}
	rows, err := d.DB.Query(ctx, stillBoundQuery, p.UserID, p.DeviceIDs)
	if err != nil {
		return nil, fmt.Errorf("device check: %w", err)
	}
	defer rows.Close()
	current := make(map[int64]boundDevice, len(p.DeviceIDs))
	for rows.Next() {
		var id int64
		var row boundDevice
		if err := rows.Scan(&id, &row.fingerprint, &row.session); err != nil {
			return nil, fmt.Errorf("device check: %w", err)
		}
		current[id] = row
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("device check: %w", err)
	}
	bound := make([]bool, len(p.DeviceIDs))
	for index, id := range p.DeviceIDs {
		row, ok := current[id]
		bound[index] = ok && row.fingerprint == p.TokenFingerprints[index] && row.session == p.SessionIDs[index]
	}
	return bound, nil
}
