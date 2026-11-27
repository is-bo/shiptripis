package notification

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"
)

// stillBoundQuery reads the devices of a queued push that are still switched
// on for its recipient. Django owns the table (apps.notifications.PushDevice).
const stillBoundQuery = `SELECT id, token_fingerprint FROM notification_push_device
WHERE user_id = $1 AND active AND id = ANY($2)`

// PostgresDevices is the DeviceRegistry over the Django database.
type PostgresDevices struct {
	Pool *pgxpool.Pool
}

func (d PostgresDevices) StillBound(ctx context.Context, userID int64, deviceIDs []int64, fingerprints []string) ([]bool, error) {
	if len(fingerprints) != len(deviceIDs) {
		return nil, fmt.Errorf("device check: %d fingerprints for %d devices", len(fingerprints), len(deviceIDs))
	}
	rows, err := d.Pool.Query(ctx, stillBoundQuery, userID, deviceIDs)
	if err != nil {
		return nil, fmt.Errorf("device check: %w", err)
	}
	defer rows.Close()
	current := make(map[int64]string, len(deviceIDs))
	for rows.Next() {
		var id int64
		var fingerprint string
		if err := rows.Scan(&id, &fingerprint); err != nil {
			return nil, fmt.Errorf("device check: %w", err)
		}
		current[id] = fingerprint
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("device check: %w", err)
	}
	bound := make([]bool, len(deviceIDs))
	for index, id := range deviceIDs {
		fingerprint, ok := current[id]
		bound[index] = ok && fingerprint == fingerprints[index]
	}
	return bound, nil
}
