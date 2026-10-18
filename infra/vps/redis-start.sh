#!/bin/sh
set -eu
umask 077
password=$(cat /run/secrets/redis_password)
# Hex-only avoids config/URL quoting ambiguities. Never put the password in argv.
case "$password" in ''|*[!0-9a-fA-F]*) echo 'Redis password must be hex' >&2; exit 1;; esac
[ "${#password}" -ge 64 ] || exit 1
cp /etc/wacla/redis.conf /run/wacla/redis.conf
printf '\nrequirepass %s\n' "$password" >> /run/wacla/redis.conf
chown redis:redis /run/wacla/redis.conf
exec /usr/local/bin/docker-entrypoint.sh redis-server /run/wacla/redis.conf
