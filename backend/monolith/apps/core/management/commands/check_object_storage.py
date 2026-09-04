"""Prove the application can actually use every bucket it is configured for.

This exists because of a real deployed failure, twice over. Django's object
storage credential and the Go KYC service's credential are different keys with
different bucket grants, and nothing in `readyz`, the settings validation or the
admin console could tell "a bucket name is set" from "the key we would use may
read it". The first time anyone found out was a traveller getting a 500 on a
boarding-pass upload; the second was a KYC reviewer getting a broken image.

A name in an environment variable is not access, and a *presigned URL is not
access either* — signing is a local HMAC that succeeds with any key, so the
only way to know is to make the request. This command does the round trip —
head, put, get, delete — with **the credential that logical storage class
actually uses**, and reports per class.

Because several logical classes legitimately share one bucket and one key, the
report says which credential profile each class resolved to, and probes each
distinct (credential, bucket) pair once.

Usage::

    python manage.py check_object_storage
    python manage.py check_object_storage --bucket kyc --read-only
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.core.storage import STORAGE_CLASSES, storage_for

#: Logical classes, in the order an operator wants to read them. `media` is an
#: alias of `parcel` in every current environment and is omitted so the report
#: does not imply a store that does not separately exist.
CHECKED_CLASSES = ("parcel", "proof", "dispute", "kyc")


class Command(BaseCommand):
    help = (
        "Verify each private storage class is readable and writable with the "
        "credential that owns it."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--bucket",
            action="append",
            choices=sorted(STORAGE_CLASSES),
            help="Check only these logical storage classes. Repeatable.",
        )
        parser.add_argument(
            "--read-only",
            action="store_true",
            help="Only probe reachability; do not write a probe object.",
        )

    def handle(self, *args, **options):
        selected = options.get("bucket") or list(CHECKED_CLASSES)
        read_only = options["read_only"]

        failures: list[str] = []
        # One probe per distinct (credential, bucket) pair. Probing one bucket
        # four times because four names point at it proves nothing extra — but
        # the same bucket under a *different* credential is a different fact,
        # which is the whole point of this command.
        seen: dict[tuple[str, str], str] = {}

        for name in selected:
            store = storage_for(name)
            profile = store.credential_source
            if not store.bucket:
                failures.append(f"{name}: no bucket configured")
                self.stdout.write(self.style.ERROR(f"{name:8} NOT CONFIGURED"))
                continue

            identity = (profile, store.bucket)
            if identity in seen:
                self.stdout.write(
                    f"{name:8} {store.bucket}  [{profile}]  "
                    f"(same bucket and credential as {seen[identity]}, "
                    f"already checked)"
                )
                continue
            seen[identity] = name

            self.stdout.write(
                f"{name:8} {store.bucket}  [{profile}]  "
                f"endpoint {store.client.meta.endpoint_url}"
            )
            problem = store.probe(read_only=read_only)
            if problem is None:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{'':8} {'reachable' if read_only else 'writable and readable'}"
                    )
                )
            else:
                failures.append(f"{name} ({store.bucket}) [{profile}]: {problem}")
                self.stdout.write(self.style.ERROR(f"{'':8} {problem}"))

        if failures:
            raise CommandError(
                "Object storage is not usable for: " + "; ".join(failures)
            )
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Every checked storage class is usable with its own credential."
            )
        )
