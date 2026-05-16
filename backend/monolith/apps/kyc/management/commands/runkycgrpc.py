"""Run the KYC gRPC server.

Usage:
    python manage.py runkycgrpc                   # default :50051
    python manage.py runkycgrpc --addr 0.0.0.0:50051

Auth modes (selected via GRPC_AUTH_MODE env, CLAUDE.md §G5):
    - "bearer" — accept a shared static token via grpc-metadata.
                  Permitted ONLY in docker-compose dev.
    - "mtls"   — verify client cert against the shared CA. Production.

For now we ship the bearer interceptor and gate it on
GRPC_AUTH_MODE=bearer + GRPC_BEARER_TOKEN. mTLS wiring lands when
cert-manager is set up.
"""

from __future__ import annotations

import logging
import os
import signal
from concurrent import futures

import grpc
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
            default=os.getenv("KYC_GRPC_ADDR", "0.0.0.0:50051"),
            help="bind address (default: $KYC_GRPC_ADDR or 0.0.0.0:50051)",
        )
        parser.add_argument(
            "--max-workers", type=int, default=4, help="thread pool size"
        )

    def handle(self, *args, **opts):
        addr = opts["addr"]
        max_workers = opts["max_workers"]

        interceptors = []
        mode = os.getenv("GRPC_AUTH_MODE", "bearer").lower()
        if mode == "bearer":
            token = os.getenv("GRPC_BEARER_TOKEN", "")
            if not token:
                raise SystemExit(
                    "GRPC_AUTH_MODE=bearer but GRPC_BEARER_TOKEN is empty"
                )
            interceptors.append(_BearerAuthInterceptor(token))
            self.stdout.write(self.style.WARNING("kyc gRPC: bearer auth (dev only)"))
        elif mode == "mtls":
            # TODO: load CA + server cert from disk and use
            # grpc.ssl_server_credentials with require_client_auth=True.
            raise SystemExit("GRPC_AUTH_MODE=mtls is not yet wired (TODO §G5)")
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
        server.add_insecure_port(addr)
        server.start()

        self.stdout.write(self.style.SUCCESS(f"kyc gRPC listening on {addr}"))

        def _shutdown(signum, _frame):
            self.stdout.write(f"received signal {signum}, draining…")
            # Grace = 10s for in-flight RPCs.
            server.stop(grace=10).wait()

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)
        server.wait_for_termination()
