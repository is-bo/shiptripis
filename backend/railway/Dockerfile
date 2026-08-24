FROM golang:1.26-alpine AS go-build

WORKDIR /src
COPY backend/services/go.mod backend/services/go.sum ./
RUN go mod download
COPY backend/services/ ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/chat ./cmd/chat \
    && CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/notification ./cmd/notification \
    && CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/kyc ./cmd/kyc \
    && CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/email ./cmd/email

FROM caddy:2.10.0-alpine AS caddy

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp/shiptrip

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates redis-server \
    && rm -rf /var/lib/apt/lists/* \
    && adduser --disabled-password --gecos "" --uid 10001 app \
    && mkdir -p /app /tmp/shiptrip \
    && chown -R app:app /app /tmp/shiptrip

WORKDIR /app
COPY backend/monolith/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY --chown=app:app backend/monolith/ /app/
COPY --from=go-build /out/ /usr/local/bin/
COPY --from=caddy /usr/bin/caddy /usr/local/bin/caddy
COPY backend/railway/Caddyfile /etc/caddy/Caddyfile
COPY backend/railway/start.py /usr/local/bin/shiptrip-start

USER app
EXPOSE 8080

CMD ["python", "/usr/local/bin/shiptrip-start"]
