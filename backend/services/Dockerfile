# Multi-stage build for any ShipTrip Go service.
#
# One Dockerfile builds all three binaries; compose selects which via the
# SERVICE build-arg (kyc | notification | chat), matching the cmd/<SERVICE>
# package. Keeps the build context (the whole Go workspace) shared so the
# layer cache is reused across services on a rebuild.

# ---- build ----------------------------------------------------------------
FROM golang:1.26-alpine AS build

# Which cmd/<SERVICE> to compile. Override per service in docker-compose.
ARG SERVICE=kyc

WORKDIR /src

# Module graph first so `go mod download` is cached unless go.mod/go.sum move.
COPY go.mod go.sum ./
RUN go mod download

# Then the source. A change here doesn't bust the module-download layer.
COPY . .

# CGO off → a static binary that runs on the scratch-ish runtime image.
# Build only the selected command.
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" \
    -o /out/service ./cmd/${SERVICE}

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

COPY --from=build /out/service /usr/local/bin/service

ENTRYPOINT ["/usr/local/bin/service"]
