"""L11A: the three-step tracking number migration, on a database with requests.

Rolls the parcels app back to before the column existed, so the requests
already in the database lose their numbers, then migrates forward again: every
request must come back with its own valid number, and the column must refuse a
duplicate.
"""

from __future__ import annotations

import unittest

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from apps.finance.tests.factories import build_scenario
from apps.finance.tests.test_concurrency import _seed_settings
from apps.parcels import tracking
from apps.parcels.models import ParcelRequest

BEFORE = ("parcels", "0010_j2_boost_reward")
FILLED = ("parcels", "0012_tracking_number_fill")


@unittest.skipUnless(connection.vendor == "postgresql", "PostgreSQL rehearsal")
class TrackingNumberMigrationTests(TransactionTestCase):
    def test_existing_requests_each_get_their_own_number(self):
        _seed_settings()
        build_scenario(prefix="l11a-mig-a")
        build_scenario(prefix="l11a-mig-b").accept()
        build_scenario(prefix="l11a-mig-c", open_request=False)
        ids = set(ParcelRequest.objects.values_list("pk", flat=True))
        assert len(ids) == 3

        executor = MigrationExecutor(connection)
        leaves = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([BEFORE])
            with connection.cursor() as cursor:
                columns = {
                    column.name
                    for column in connection.introspection.get_table_description(
                        cursor, "parcels_request"
                    )
                }
            assert "tracking_number" not in columns

            # Step 2 alone fills every row that step 1 left empty.
            MigrationExecutor(connection).migrate([FILLED])
            historic = (
                MigrationExecutor(connection)
                .loader.project_state([FILLED])
                .apps.get_model("parcels", "ParcelRequest")
            )
            filled = dict(historic.objects.values_list("pk", "tracking_number"))
            assert set(filled) == ids
            assert all(tracking.is_valid(number) for number in filled.values())
            assert len(set(filled.values())) == len(filled)
        finally:
            MigrationExecutor(connection).migrate(leaves)

        numbers = dict(ParcelRequest.objects.values_list("pk", "tracking_number"))
        assert numbers == filled
        # Step 3 made it unique and required.
        first, second = sorted(numbers)[:2]
        with self.assertRaises(IntegrityError), transaction.atomic():
            ParcelRequest.objects.filter(pk=second).update(
                tracking_number=numbers[first]
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ParcelRequest.objects.filter(pk=second).update(tracking_number=None)
