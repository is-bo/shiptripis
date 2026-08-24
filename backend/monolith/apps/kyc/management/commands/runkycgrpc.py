"""Run the KYC gRPC server.

Usage:
    python manage.py runkycgrpc                   # default :50051
    python manage.py runkycgrpc --addr 0.0.0.0:50051

Auth modes (selected via GRPC_AUTH_MODE, CLAUDE.md §G5):
    - "bearer" — accept a shared static token via grpc-metadata.
                  Permitted ONLY in docker-compose dev.
    - "mtls"   — verify client cert against the shared CA. Production.

The production mTLS mode requires paths to a CA, server certificate, and
server private key. The matching Go client presents a CA-signed client cert.
"""

from __future__ import annotations

import logging
import signal
from concurrent import futures
from pathlib import Path

import grpc
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.kyc.grpc_gen import kyc_pb2_grpc
from apps.kyc.grpc_server import KYCSubmissionServicer

log = logging.getLogger(__name__)

# 16 MiB on both client and server per CLAUDE.md §G5.
MAX_MESSAGE_BYTES = 16 << 20


class _BearerAuthInterceptor(grpc.ServerInterceptor):
    """Trivial shared-secret check — dev only."""

    def __init__(self, expected_token: str):
        self._expected = expected_token

    def intercept_service(self, continuation, handler_call_details):
        meta = dict(handler_call_details.invocation_metadata or [])
        got = meta.get("authorization", "")
        if got == f"Bearer {self._expected}":
            return continuation(handler_call_details)

        def deny(_request, context):
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid bearer token")

        return grpc.unary_unary_rpc_method_handler(deny)


class Command(BaseCommand):
    help = "Run the KYC gRPC server (RecordSubmission RPC)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--addr",
            default=settings.GRPC_DJANGO_BIND,
            help="bind address (default: $GRPC_DJANGO_BIND or 0.0.0.0:50051)",
        )
        parser.add_argument(
            "--max-workers", type=int, default=4, help="thread pool size"
        )

    def handle(self, *args, **opts):
        addr = opts["addr"]
        max_workers = opts["max_workers"]

        interceptors = []
        server_credentials = None
        mode = settings.GRPC_AUTH_MODE.lower()
        if mode == "bearer":
            token = settings.GRPC_BEARER_TOKEN
            if not token:
                raise SystemExit(
                    "GRPC_AUTH_MODE=bearer but GRPC_BEARER_TOKEN is empty"
                )
            interceptors.append(_BearerAuthInterceptor(token))
            self.stdout.write(self.style.WARNING("kyc gRPC: bearer auth"))
        elif mode == "mtls":
            try:
                ca_cert = Path(settings.GRPC_TLS_CA_CERT).read_bytes()
                server_cert = Path(settings.GRPC_TLS_SERVER_CERT).read_bytes()
                server_key = Path(settings.GRPC_TLS_SERVER_KEY).read_bytes()
            except OSError as exc:
                raise SystemExit(f"cannot read gRPC TLS credentials: {exc}") from exc
            server_credentials = grpc.ssl_server_credentials(
                [(server_key, server_cert)],
                root_certificates=ca_cert,
                require_client_auth=True,
            )
        else:
            raise SystemExit(f"unknown GRPC_AUTH_MODE={mode!r}")

        server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=max_workers),
            interceptors=interceptors,
            options=[
                ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
                ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
            ],
        )
        kyc_pb2_grpc.add_KYCSubmissionServiceServicer_to_server(
            KYCSubmissionServicer(), server
        )
        if server_credentials is None:
            bound_port = server.add_insecure_port(addr)
        else:
            bound_port = server.add_secure_port(addr, server_credentials)
        if bound_port == 0:
            raise SystemExit(f"could not bind gRPC server to {addr}")
        server.start()

        self.stdout.write(self.style.SUCCESS(f"kyc gRPC listening on {addr}"))

        def _shutdown(signum, _frame):
            self.stdout.write(f"received signal {signum}, draining…")
            # Grace = 10s for in-flight RPCs.
            server.stop(grace=10).wait()

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)
        server.wait_for_termination()
