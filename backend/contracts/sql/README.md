# Database contracts — Django ↔ Go

`schema.sql` is the **single source of truth** for the Postgres schema. It is
**generated** from Django by `task contract:sync-db` — never hand-edit it.

## For Claude A (Django side)

Whenever you land a Django migration that touches a Go-read table
(`chat_message`, `notification`, `kyc_submission`, `media_object`,
`published_event`):

1. Apply the migration locally (`task migrate`)
2. Re-export the schema (`task contract:sync-db`)
3. Commit `schema.sql` in the **same PR** as the migration
4. Flag the change in the PR description so Claude B knows to regenerate

## For Claude B (Go side)

Write SQL query files under `queries/<service>/` — one `.sql` file per
logical operation. sqlc reads them, types them against `schema.sql`, and
spits out Go code under `services/internal/<service>/repo/`.

Example `queries/chat/messages.sql`:

```sql
-- name: GetMessage :one
SELECT * FROM chat_message WHERE id = $1;

-- name: ListThreadMessages :many
SELECT * FROM chat_message
WHERE thread_id = $1 AND created_at > $2
ORDER BY created_at ASC
LIMIT $3;
```

Then `task contract:generate` runs `sqlc generate` and writes the typed Go
client. **Never hand-edit files under `services/internal/*/repo/`** — they
are regenerated.

## Tables owned by Go (where Go is the writer)

| Table | Service | Notes |
|---|---|---|
| `chat_message` | chat | Django doesn't write here |
| `chat_thread` | chat | Django doesn't write here |
| `notification` | notif | Django doesn't write here |
| `kyc_submission` | kyc | Django reflects via gRPC + Redis |
| `media_object` | media | Bytes live in S3/MinIO |

## Tables Go reads but Django owns

| Table | Reason |
|---|---|
| `accounts_user` | Auth lookup, roles, ban flag |
| `matching_match` | For chat thread → match correlation |
| `parcels_request` | For media uploads to be tied to a parcel |
| `published_event` | Detection-only outbox audit (G6b) |

## Drift gate

`task check-drift` runs both `contract:sync-db` and `contract:generate`
then `git diff --exit-code` on the contracts dir. If anything moved, CI
fails and the PR must rerun before merge.
