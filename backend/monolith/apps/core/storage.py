"""S3-compatible object storage, split by which credential owns which bucket.

ARCHITECTURE.md §9 (G4): no MinIO-specific code; the client speaks plain S3 v4
against a custom endpoint so the provider can be swapped by environment alone.

**The reason this module has more than one client.** ShipTrip's buckets are not
all owned by the same key. The Go KYC service holds a credential scoped to the
private KYC bucket, and on the deployed environment that credential is the only
one granted there; Django's generic ``S3_*`` key is refused with
``AccessDenied``. Everything else Django writes — parcel media, flight proof,
dispute evidence — lives in the private media bucket that Django's own key
owns.

That distinction is invisible at presign time, which is what made it expensive
to find. ``generate_presigned_url`` is a local HMAC: it never contacts the
provider and therefore never fails, whatever key it is handed. A URL signed
with the wrong credential is a perfectly well-formed URL that the browser is
then denied. The admin console did not show an error; it showed a broken
image.

So storage is addressed by **logical class**, and each class names both its
bucket and the credential profile that owns it:

    storage_for("kyc").presigned_get(key)      # KYC_S3_* credential
    storage_for("parcel").put(key, body, ct)   # S3_* credential

`readable(key)` exists for the same reason: it is the only way to find out
before rendering a page whether the object can actually be fetched.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from PIL import Image, UnidentifiedImageError

#: Credential profiles, by the environment prefix that supplies them. The name
#: is reported to operators so a storage failure says *which key* was refused,
#: without any part of the key itself appearing anywhere.
GENERIC_CREDENTIAL = "S3_*"
KYC_CREDENTIAL = "KYC_S3_*"

#: Logical storage class → the setting naming its bucket, and the credential
#: profile that owns it. Keyed by what the code calls the store, not by the
#: deployed bucket name, which differs per environment (and where several
#: logical classes legitimately share one bucket).
STORAGE_CLASSES: dict[str, tuple[str, str]] = {
    # The generic private media store. `parcel` is its primary name here
    # because parcel item photos are what write to it most; flight proof and
    # dispute evidence share the same bucket and the same credential.
    "media": ("S3_BUCKET_PARCEL", GENERIC_CREDENTIAL),
    "parcel": ("S3_BUCKET_PARCEL", GENERIC_CREDENTIAL),
    "proof": ("S3_BUCKET_PROOF", GENERIC_CREDENTIAL),
    "dispute": ("S3_BUCKET_DISPUTE", GENERIC_CREDENTIAL),
    # Identity evidence. Separate bucket, separate credential, deliberately.
    "kyc": ("S3_BUCKET_KYC", KYC_CREDENTIAL),
}


class StorageNotConfigured(RuntimeError):
    """A storage class has no bucket, so nothing can be read or written."""


@dataclass(frozen=True, slots=True)
class _Credential:
    """One S3 identity. Never rendered, logged or returned to a caller."""

    endpoint_url: str
    region: str
    access_key: str
    secret_key: str
    use_path_style: bool


def _generic_credential() -> _Credential:
    return _Credential(
        endpoint_url=settings.S3_ENDPOINT_URL,
        region=settings.S3_REGION,
        access_key=settings.S3_ACCESS_KEY,
        secret_key=settings.S3_SECRET_KEY,
        use_path_style=settings.S3_USE_PATH_STYLE,
    )


def _kyc_credential() -> _Credential:
    """The KYC bucket's own key, falling back to the generic one.

    The fallback is not a loophole: in local and compose environments a single
    key owns every bucket, and refusing to work there would break development
    for a separation that only exists in the deployed environment. Where the
    deployment does supply `KYC_S3_ACCESS_KEY`, it wins.
    """

    access_key = getattr(settings, "KYC_S3_ACCESS_KEY", "")
    secret_key = getattr(settings, "KYC_S3_SECRET_KEY", "")
    if not (access_key and secret_key):
        return _generic_credential()
    return _Credential(
        endpoint_url=getattr(settings, "KYC_S3_ENDPOINT_URL", "")
        or settings.S3_ENDPOINT_URL,
        region=getattr(settings, "KYC_S3_REGION", "") or settings.S3_REGION,
        access_key=access_key,
        secret_key=secret_key,
        use_path_style=bool(
            getattr(settings, "KYC_S3_USE_PATH_STYLE", settings.S3_USE_PATH_STYLE)
        ),
    )


def _credential_for(profile: str) -> _Credential:
    return _kyc_credential() if profile == KYC_CREDENTIAL else _generic_credential()


#: A health probe answers a page an operator is looking at. It must fail fast
#: and give up: an unreachable store is the thing being reported, and taking a
#: minute of retries to report it would make the console unusable in exactly
#: the incident it exists for. With one retry that bounds a probe at roughly
#: eight seconds. Uploads keep the library defaults, because a slow large PUT
#: is not a fault.
_PROBE_TIMEOUT_SECONDS = 4


@lru_cache(maxsize=16)
def _client_for(credential: _Credential, *, probe: bool = False):
    """One boto3 client per distinct identity.

    Cached on the credential rather than on the storage class, so four logical
    classes sharing one key share one client and one connection pool.
    """

    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path" if credential.use_path_style else "virtual"},
        **(
            {
                "connect_timeout": _PROBE_TIMEOUT_SECONDS,
                "read_timeout": _PROBE_TIMEOUT_SECONDS,
                "retries": {"max_attempts": 1},
            }
            if probe
            else {}
        ),
    )
    return boto3.client(
        "s3",
        endpoint_url=credential.endpoint_url,
        region_name=credential.region,
        aws_access_key_id=credential.access_key,
        aws_secret_access_key=credential.secret_key,
        config=config,
    )


@dataclass(frozen=True, slots=True)
class ObjectStore:
    """One logical storage class, bound to its bucket and its owning key."""

    name: str
    bucket: str
    #: `S3_*` or `KYC_S3_*`. An operator-facing label, never a credential.
    credential_source: str
    _credential: _Credential

    @property
    def client(self):
        return _client_for(self._credential)

    @property
    def probe_client(self):
        """The same identity, with timeouts short enough to answer a page."""

        return _client_for(self._credential, probe=True)

    @property
    def uses_dedicated_credential(self) -> bool:
        """Whether this class is actually using a key of its own."""

        return self._credential != _generic_credential()

    def require_bucket(self) -> str:
        if not self.bucket:
            raise StorageNotConfigured(
                f"No bucket is configured for the {self.name} object store."
            )
        return self.bucket

    def put(self, key: str, body: bytes, content_type: str) -> None:
        """Upload an object. The bucket must already exist; buckets are
        managed out-of-band because Supabase/Tigris S3 does not expose
        CreateBucket."""

        self.client.put_object(
            Bucket=self.require_bucket(),
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.require_bucket(), Key=key)[
            "Body"
        ].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.require_bucket(), Key=key)

    def presigned_get(
        self,
        key: str,
        *,
        expires_in: int,
        content_disposition: str = "",
    ) -> str:
        """A short-lived download URL.

        This is a local signing operation. It succeeds against a bucket this
        credential cannot read, which is why nothing may treat a returned URL
        as evidence that the object is reachable — call `readable()` for that.
        """

        params: dict[str, str] = {"Bucket": self.require_bucket(), "Key": key}
        if content_disposition:
            params["ResponseContentDisposition"] = content_disposition
        return self.client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=int(expires_in)
        )

    def readable(self, key: str) -> bool:
        """Whether this credential can actually fetch this object right now.

        One HEAD. Used before a page renders an object it is about to link or
        embed, so an authorization or outage problem becomes a sentence the
        operator can act on instead of a broken image.
        """

        if not self.bucket or not key:
            return False
        try:
            self.probe_client.head_object(Bucket=self.bucket, Key=key)
        except (ClientError, BotoCoreError, ValueError):
            return False
        return True

    def probe(self, *, read_only: bool = False) -> str | None:
        """Round-trip the bucket with this credential.

        Returns None when the store works, or a one-line failure carrying the
        provider's error code and no credential material.
        """

        if not self.bucket:
            return "no bucket configured"
        # `--read-only` is the health path and must fail fast; a write probe is
        # a deliberate operator command and keeps the ordinary timeouts.
        client = self.probe_client if read_only else self.client
        try:
            client.head_bucket(Bucket=self.bucket)
        except Exception as exc:  # noqa: BLE001 — the message is the report
            return f"head_bucket failed: {short_storage_error(exc)}"
        if read_only:
            return None

        key = f"{PROBE_PREFIX}/{secrets.token_urlsafe(12)}.txt"
        payload = b"shiptrip storage check"
        try:
            client.put_object(
                Bucket=self.bucket, Key=key, Body=payload, ContentType="text/plain"
            )
        except Exception as exc:  # noqa: BLE001
            return f"put_object failed: {short_storage_error(exc)}"
        try:
            if client.get_object(Bucket=self.bucket, Key=key)["Body"].read() != payload:
                return "get_object returned different bytes than were written"
        except Exception as exc:  # noqa: BLE001
            return f"get_object failed: {short_storage_error(exc)}"
        finally:
            try:
                client.delete_object(Bucket=self.bucket, Key=key)
            except Exception:  # noqa: BLE001 — cleanup, not the verdict
                pass
        return None


#: Probe objects are written under this prefix and removed again.
PROBE_PREFIX = ".shiptrip-storage-check"


def short_storage_error(exc: Exception) -> str:
    """One line with the provider's error code and nothing identifying."""

    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        http = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code:
            return f"{code} (HTTP {http})"
    return f"{type(exc).__name__}: {str(exc)[:120]}"


def storage_for(name: str) -> ObjectStore:
    """The object store for one logical storage class."""

    try:
        bucket_setting, profile = STORAGE_CLASSES[name]
    except KeyError as exc:  # pragma: no cover — a typo in a call site
        raise StorageNotConfigured(f"Unknown storage class {name!r}.") from exc
    return ObjectStore(
        name=name,
        bucket=getattr(settings, bucket_setting, "") or "",
        credential_source=profile,
        _credential=_credential_for(profile),
    )


def reset_storage_clients() -> None:
    """Drop every cached client. For tests that swap credentials wholesale.

    Rarely needed: the cache is keyed on the credential itself, so changing any
    part of one already produces a different client.
    """

    _client_for.cache_clear()


def store_for_bucket(bucket: str, *, default: str = "media") -> ObjectStore:
    """The store that owns a bucket name recorded on a historical row.

    Evidence rows persist the bucket they were written to, so an object stored
    before a bucket was reassigned still resolves to whichever credential can
    actually read it today. An unrecognised bucket falls back to Django's own
    credential, which is the correct guess for anything Django itself wrote.
    """

    if bucket:
        for name, (bucket_setting, profile) in STORAGE_CLASSES.items():
            if getattr(settings, bucket_setting, "") == bucket:
                return ObjectStore(
                    name=name,
                    bucket=bucket,
                    credential_source=profile,
                    _credential=_credential_for(profile),
                )
    fallback = storage_for(default)
    return ObjectStore(
        name=fallback.name,
        bucket=bucket or fallback.bucket,
        credential_source=fallback.credential_source,
        _credential=fallback._credential,
    )


def s3_client():
    """The generic media credential's client.

    Kept for callers that legitimately speak to Django's own buckets without a
    logical class. New code should use `storage_for(...)`, which cannot be
    pointed at a bucket the chosen credential does not own.
    """

    return _client_for(_generic_credential())


def put_object(*, bucket: str, key: str, body: bytes, content_type: str) -> None:
    """Upload with the generic credential. Prefer `storage_for(...).put`."""

    s3_client().put_object(
        Bucket=bucket, Key=key, Body=body, ContentType=content_type
    )


def make_key(prefix: str, ext: str) -> str:
    """`<prefix>/<random>.<ext>` — random component prevents enumeration."""
    return f"{prefix}/{secrets.token_urlsafe(16)}.{ext.lstrip('.')}"


_EXT_BY_CT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def ext_for_content_type(ct: str) -> str | None:
    return _EXT_BY_CT.get((ct or "").lower())


def image_bytes_match_extension(body: bytes, expected_ext: str) -> bool:
    """Verify decoded image bytes match the declared upload type.

    Browser-supplied content types are untrusted. Pillow parses only the
    header/structure here; the pixel limit also rejects decompression bombs.
    """
    format_to_ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
    try:
        with Image.open(BytesIO(body)) as image:
            if image.width * image.height > 40_000_000:
                return False
            actual_ext = format_to_ext.get(image.format or "")
            image.verify()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        return False
    return actual_ext == expected_ext
