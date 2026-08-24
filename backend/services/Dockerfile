# Multi-stage build for all ShipTrip Go services. Building every small static
# binary makes one immutable image usable by Railway's chat, notification,
# KYC, and email services without relying on provider-specific build args.

# ---- build ----------------------------------------------------------------
FROM golang:1.26-alpine AS build

WORKDIR /src

# Module graph first so `go mod download` is cached unless go.mod/go.sum move.
COPY go.mod go.sum ./
RUN go mod download

# Then the source. A change here doesn't bust the module-download layer.
COPY . .

# CGO off → static binaries that run on the small runtime image.
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/chat ./cmd/chat && \
    CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/notification ./cmd/notification && \
    CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/kyc ./cmd/kyc && \
    CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/email ./cmd/email

# ---- runtime --------------------------------------------------------------
# alpine (not scratch) so the compose healthcheck has a wget (busybox ships
# one) and a shell. The build is HERMETIC — no `apk add`, so it never touches
# the Alpine package mirror and won't break in CI / airgapped / sandboxed
# builds. CA roots for real-S3 / FCM TLS dials are copied from the golang
# build image, which already has them.
FROM alpine:3.20

COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt

# Non-root run user. `adduser` is busybox-provided, no network needed.
RUN adduser -D -u 10001 app
USER app

COPY --from=build /out/ /usr/local/bin/
COPY railway-entrypoint.sh /usr/local/bin/railway-entrypoint

ENTRYPOINT ["/bin/sh", "/usr/local/bin/railway-entrypoint"]
