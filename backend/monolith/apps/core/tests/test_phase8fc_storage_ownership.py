"""Phase 8F-C: which credential owns which bucket, and why that is not cosmetic.

The deployed failure this file locks down: the Go KYC service holds a key
scoped to the private KYC bucket, and on Railway that key is the *only* one
granted there. Django's generic `S3_*` key gets `AccessDenied`. Django was
nonetheless presigning KYC objects with it — and presigning never fails, because
it is a local HMAC. The reviewer therefore received a perfectly well-formed URL
and a broken image, with no error anywhere in the stack.

Two properties follow, and both are tested here:

1. A storage class resolves to the credential that owns its bucket.
2. Reachability is a question you have to *ask*, separately from signing.
"""

from __future__ import annotations

from unittest import mock

from botocore.exceptions import ClientError
from django.test import SimpleTestCase, override_settings

from apps.core.storage import (
    GENERIC_CREDENTIAL,
    KYC_CREDENTIAL,
    STORAGE_CLASSES,
    StorageNotConfigured,
    reset_storage_clients,
    storage_for,
    store_for_bucket,
)

DEPLOYED = {
    "S3_ENDPOINT_URL": "https://t3.example.invalid",
    "S3_REGION": "ams",
    "S3_ACCESS_KEY": "generic-access",
    "S3_SECRET_KEY": "generic-secret",
    "S3_BUCKET_PARCEL": "shiptrip-media",
    "S3_BUCKET_PROOF": "shiptrip-media",
    "S3_BUCKET_DISPUTE": "shiptrip-media",
    "S3_BUCKET_KYC": "shiptrip-kyc",
    "KYC_S3_ENDPOINT_URL": "https://t3.example.invalid",
    "KYC_S3_REGION": "ams",
    "KYC_S3_ACCESS_KEY": "kyc-only-access",
    "KYC_S3_SECRET_KEY": "kyc-only-secret",
}


class StorageOwnershipTests(SimpleTestCase):
    def setUp(self):
        reset_storage_clients()
        self.addCleanup(reset_storage_clients)

    @override_settings(**DEPLOYED)
    def test_kyc_uses_its_own_credential_and_everything_else_uses_djangos(self):
        assert storage_for("kyc").credential_source == KYC_CREDENTIAL
        for name in ("parcel", "proof", "dispute", "media"):
            with self.subTest(store=name):
                assert storage_for(name).credential_source == GENERIC_CREDENTIAL

    @override_settings(**DEPLOYED)
    def test_the_kyc_client_is_not_the_generic_client(self):
        # The specific bug: one client for every bucket. If these are the same
        # object the KYC bucket is being addressed with a key that has no grant
        # on it, and no test below can catch it because signing still works.
        assert storage_for("kyc").client is not storage_for("parcel").client
        assert storage_for("kyc").uses_dedicated_credential is True
        assert storage_for("parcel").uses_dedicated_credential is False

    @override_settings(**DEPLOYED)
    def test_stores_sharing_one_credential_share_one_client(self):
        # Four logical names over one bucket should not mean four connection
        # pools.
        assert storage_for("parcel").client is storage_for("proof").client
        assert storage_for("proof").client is storage_for("dispute").client

    @override_settings(**{**DEPLOYED, "KYC_S3_ACCESS_KEY": "", "KYC_S3_SECRET_KEY": ""})
    def test_without_a_dedicated_key_kyc_falls_back_to_the_generic_one(self):
        # Local and compose environments give one key every bucket. Refusing to
        # work there would break development for a separation that only exists
        # on the deployed environment.
        store = storage_for("kyc")
        assert store.uses_dedicated_credential is False
        assert store.client is storage_for("parcel").client

    @override_settings(**DEPLOYED)
    def test_a_recorded_bucket_resolves_to_the_credential_that_can_read_it(self):
        # Evidence rows persist the bucket they were written to, so an object
        # stored before a bucket moved still resolves correctly today.
        assert store_for_bucket("shiptrip-kyc").credential_source == KYC_CREDENTIAL
        assert (
            store_for_bucket("shiptrip-media").credential_source == GENERIC_CREDENTIAL
        )
        # An unrecognised bucket is assumed to be Django's own, which is the
        # right guess for anything Django itself wrote.
        assert store_for_bucket("some-old-bucket").credential_source == (
            GENERIC_CREDENTIAL
        )
        assert store_for_bucket("some-old-bucket").bucket == "some-old-bucket"

    @override_settings(**{**DEPLOYED, "S3_BUCKET_KYC": ""})
    def test_an_unconfigured_store_refuses_rather_than_writing_nowhere(self):
        store = storage_for("kyc")
        assert store.bucket == ""
        with self.assertRaises(StorageNotConfigured):
            store.require_bucket()
        # And nothing is ever "readable" in a store with no bucket.
        assert store.readable("some/key") is False

    def test_every_declared_storage_class_names_a_real_setting(self):
        for name, (setting, profile) in STORAGE_CLASSES.items():
            with self.subTest(store=name):
                assert setting.startswith("S3_BUCKET_")
                assert profile in (GENERIC_CREDENTIAL, KYC_CREDENTIAL)


class ReachabilityIsSeparateFromSigningTests(SimpleTestCase):
    """A signed URL proves nothing about access. Only a request does."""

    def setUp(self):
        reset_storage_clients()
        self.addCleanup(reset_storage_clients)

    @override_settings(**DEPLOYED)
    def test_presigning_succeeds_even_where_the_credential_has_no_grant(self):
        # Stated as a test because it is the counter-intuitive fact the whole
        # repair rests on. Nothing here touches the network.
        url = storage_for("kyc").presigned_get("front.jpg", expires_in=300)

        assert url.startswith("https://")
        assert "shiptrip-kyc" in url

    @override_settings(**DEPLOYED)
    def test_readable_is_false_when_the_store_denies_the_object(self):
        denied = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied."}},
            "HeadObject",
        )
        store = storage_for("kyc")
        with mock.patch.object(store.client, "head_object", side_effect=denied):
            assert store.readable("front.jpg") is False

    @override_settings(**DEPLOYED)
    def test_readable_is_true_when_the_store_answers(self):
        store = storage_for("kyc")
        with mock.patch.object(store.client, "head_object", return_value={}):
            assert store.readable("front.jpg") is True

    @override_settings(**DEPLOYED)
    def test_a_probe_failure_reports_a_code_and_no_credential_material(self):
        denied = ClientError(
            {
                "Error": {"Code": "AccessDenied", "Message": "Access Denied."},
                "ResponseMetadata": {"HTTPStatusCode": 403},
            },
            "HeadBucket",
        )
        store = storage_for("kyc")
        with mock.patch.object(store.client, "head_bucket", side_effect=denied):
            problem = store.probe(read_only=True)

        assert problem is not None
        assert "AccessDenied" in problem
        assert "403" in problem
        assert DEPLOYED["KYC_S3_ACCESS_KEY"] not in problem
        assert DEPLOYED["KYC_S3_SECRET_KEY"] not in problem


class ObjectStoreHidesItsCredentialTests(SimpleTestCase):
    def setUp(self):
        reset_storage_clients()
        self.addCleanup(reset_storage_clients)

    @override_settings(**DEPLOYED)
    def test_the_operator_label_names_the_variable_not_the_value(self):
        for name in STORAGE_CLASSES:
            with self.subTest(store=name):
                store = storage_for(name)
                rendered = f"{store.name} {store.bucket} {store.credential_source}"
                assert DEPLOYED["S3_SECRET_KEY"] not in rendered
                assert DEPLOYED["KYC_S3_SECRET_KEY"] not in rendered
                assert store.credential_source.endswith("*")
