#!/bin/sh
# restic encrypts, authenticates and content-addresses all database backup chunks.
set -eu
set -o pipefail
umask 077
export RESTIC_CACHE_DIR=/tmp/restic-cache
: "${RESTIC_REPOSITORY:?configure an offsite restic repository}"
if [ "${BACKUP_TEST_MODE:-false}" != true ]; then
  case "$RESTIC_REPOSITORY" in *@*) echo 'Use separate backup credentials, never inline URI credentials' >&2; exit 1;; esac
  case "$RESTIC_REPOSITORY" in s3:https://*) ;;
    *) echo 'An HTTPS S3-compatible offsite repository is required' >&2; exit 1;; esac
fi
mode=${1:-backup}
snapshot=${2:-}
mkdir -p /work /status
status() {
  result=$?
  if [ "$result" -ne 0 ]; then date -u +%s > /status/last-failure; fi
}
trap status EXIT
case "$mode" in
  init)
    # Explicit operation: never reset/reinitialize a repo on an access failure.
    restic init
    ;;
  backup)
    export PGPASSWORD="$(cat /run/secrets/postgres_password)"
    : "${BACKUP_KEEP_DAILY:?owner must select backup retention}"
    : "${BACKUP_KEEP_WEEKLY:?owner must select backup retention}"
    : "${BACKUP_KEEP_MONTHLY:?owner must select backup retention}"
    for count in "$BACKUP_KEEP_DAILY" "$BACKUP_KEEP_WEEKLY" "$BACKUP_KEEP_MONTHLY"; do
      case "$count" in ''|*[!0-9]*) exit 1;; esac
      [ "$count" -gt 0 ] || exit 1
    done
    # restic waits for pg_dump and refuses a failed command. No plaintext dump
    # is staged in RAM or on disk; encrypted chunks carry SHA-256 content IDs.
    restic backup --host wacla-vps --tag wacla-postgres --stdin-from-command \
      --stdin-filename database.dump -- pg_dump --format=custom --no-owner --no-privileges
    restic check --read-data
    # Retention only after a successful upload and repository check.
    restic forget --host wacla-vps --tag wacla-postgres \
      --keep-daily "$BACKUP_KEEP_DAILY" --keep-weekly "$BACKUP_KEEP_WEEKLY" \
      --keep-monthly "$BACKUP_KEEP_MONTHLY" --prune
    date -u +%s > /status/last-success
    ;;
  verify|export)
    # Require a reviewed immutable snapshot ID; never silently choose 'latest'.
    case "$snapshot" in ''|*[!0-9a-f]*) echo 'Supply immutable snapshot ID' >&2; exit 1;; esac
    [ "${#snapshot}" -eq 64 ] || { echo 'Use full 64-character snapshot ID' >&2; exit 1; }
    restic check --read-data >&2
    if [ "$mode" = export ]; then
      restic dump "$snapshot" /database.dump
    else
      # --list reads the TOC only. Drain remaining bytes so a valid large
      # archive does not make the producer fail with SIGPIPE under pipefail.
      restic dump "$snapshot" /database.dump | (pg_restore --list >/dev/null; cat >/dev/null)
    fi
    ;;
  snapshots) restic snapshots --host wacla-vps --tag wacla-postgres ;;
  *) echo 'Expected init, backup, snapshots, verify ID, or export ID' >&2; exit 1;;
esac
