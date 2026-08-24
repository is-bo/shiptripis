#!/bin/sh
set -eu

case "${SHIPTRIP_SERVICE:-}" in
  chat|notification|kyc|email)
    exec "/usr/local/bin/${SHIPTRIP_SERVICE}"
    ;;
  *)
    echo "SHIPTRIP_SERVICE must be one of: chat, notification, kyc, email" >&2
    exit 64
    ;;
esac
