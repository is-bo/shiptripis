# syntax=docker/dockerfile:1
FROM golang:1.26.2-alpine@sha256:f85330846cde1e57ca9ec309382da3b8e6ae3ab943d2739500e08c86393a21b1 AS go-build
WORKDIR /src
COPY backend/services/go.mod backend/services/go.sum ./
RUN --mount=type=secret,id=system_ca \
    if [ -f /run/secrets/system_ca ]; then export SSL_CERT_FILE=/run/secrets/system_ca; fi; \
    go mod download
COPY backend/services/ ./
RUN CGO_ENABLED=0 go build -mod=readonly -trimpath -ldflags="-s -w" -o /out/chat ./cmd/chat \
    && CGO_ENABLED=0 go build -mod=readonly -trimpath -ldflags="-s -w" -o /out/notification ./cmd/notification \
    && CGO_ENABLED=0 go build -mod=readonly -trimpath -ldflags="-s -w" -o /out/kyc ./cmd/kyc \
    && CGO_ENABLED=0 go build -mod=readonly -trimpath -ldflags="-s -w" -o /out/email ./cmd/email
FROM caddy:2.10.0-alpine@sha256:ae4458638da8e1a91aafffb231c5f8778e964bca650c8a8cb23a7e8ac557aa3c AS caddy
FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 DJANGO_SETTINGS_MODULE=config.settings.prod HOME=/tmp/shiptrip
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY infra/vps/requirements.lock /tmp/requirements.lock
RUN --mount=type=secret,id=system_ca \
    if [ -f /run/secrets/system_ca ]; then export PIP_CERT=/run/secrets/system_ca; fi; \
    pip install -r /tmp/requirements.lock
COPY --chown=10001:10001 backend/monolith/ /app/
COPY --chown=10001:10001 web/ /web/
COPY --from=go-build /out/ /usr/local/bin/
COPY --from=caddy /usr/bin/caddy /usr/local/bin/caddy
RUN python -c "import os; p='/usr/local/bin/caddy'; [os.removexattr(p, n) for n in os.listxattr(p) if n == 'security.capability']"
COPY --chmod=0644 infra/vps/gateway.Caddyfile /etc/caddy/Caddyfile
COPY --chmod=0644 infra/vps/launcher.py /opt/vps/launcher.py
COPY --chmod=0644 infra/vps/runtime.py /opt/vps/runtime.py
RUN chmod 0755 /opt/vps /etc/caddy
RUN mkdir -p /app/staticfiles && chown 10001:10001 /app/staticfiles
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["python", "/opt/vps/runtime.py"]
CMD ["serve"]
