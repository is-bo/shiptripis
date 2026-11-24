"""Fix plan P2: the public city name, on rows shaped like the real catalogue.

Names, parents and tiers below are copied from the 2026 manifest
(`apps/locations/data/geography_manifest_2026.json.gz`), so each case is a
row the live catalogue actually holds.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from apps.locations.city_names import card_place, city_name
from apps.locations.models import AirportLocalityMapping, Country, Place

COUNTRIES = (("DZ", "Algeria"), ("FR", "France"), ("ES", "Spain"), ("DE", "Germany"))


class CityNameTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.countries = {
            code: Country.objects.create(
                code=code,
                name=name,
                source="p2-test",
                source_id=f"country-{code}",
                source_version="p2",
            )
            for code, name in COUNTRIES
        }
        cls._serial = 0

    @classmethod
    def place(
        cls, country, name, *, parent=None, tier="", kind=Place.PlaceType.LOCALITY, **extra
    ):
        cls._serial += 1
        return Place.objects.create(
            country=cls.countries[country],
            place_type=kind,
            source="p2-test",
            source_id=f"{country}-{cls._serial}",
            source_version="p2",
            name=name,
            parent=parent,
            admin_level=tier,
            **extra,
        )

    @classmethod
    def region(cls, country, name, tier):
        return cls.place(country, name, tier=tier, kind=Place.PlaceType.ADMIN_REGION)

    @classmethod
    def airport(cls, country, name, iata, *, served=None, parent=None):
        airport = cls.place(
            country,
            name,
            parent=parent,
            kind=Place.PlaceType.AIRPORT,
            iata_code=iata,
            passenger_use=True,
            latitude=Decimal("36.691014"),
            longitude=Decimal("3.215408"),
        )
        if served is not None:
            AirportLocalityMapping.objects.create(
                airport=airport,
                locality=served,
                relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
                is_primary=True,
                source="p2-test",
                source_id=f"mapping-{iata}",
                source_version="p2",
            )
        return airport

    def assertCity(self, place, expected):
        # Read back the way the public payloads load a place.
        fresh = Place.objects.select_related("parent").get(pk=place.pk)
        self.assertEqual(city_name(fresh), expected)

    def test_algeria_names_the_wilaya(self):
        alger = self.region("DZ", "Alger", "wilaya")
        tamanrasset = self.region("DZ", "Tamanrasset", "wilaya")
        cases = (
            (self.place("DZ", "Alger Centre", parent=alger, tier="commune"), "Alger"),
            (self.place("DZ", "Bab Ezzouar", parent=alger, tier="commune"), "Alger"),
            (
                self.place("DZ", "Tamanghasset", parent=tamanrasset, tier="commune"),
                "Tamanrasset",
            ),
        )
        for place, expected in cases:
            with self.subTest(place.name):
                self.assertCity(place, expected)

    def test_algeria_without_a_wilaya_names_nothing(self):
        # Only a parent recorded as a wilaya counts: a commune without one, or
        # under any other tier, never falls back to its own or a daïra's name.
        orphan = self.place("DZ", "Bab Ezzouar", tier="commune")
        daira = self.region("DZ", "Dar El Beida", "daira")
        under_daira = self.place("DZ", "Bab Ezzouar", parent=daira, tier="commune")
        self.assertCity(orphan, "")
        self.assertCity(under_daira, "")

    def test_the_card_projection_names_the_city_in_every_name_field(self):
        alger = self.region("DZ", "Alger", "wilaya")
        centre = self.place("DZ", "Alger Centre", parent=alger, tier="commune")
        alg = self.airport(
            "DZ", "Houari Boumediene Airport", "ALG", served=centre, parent=alger
        )
        self.assertEqual(
            card_place(alg),
            {
                "id": alg.pk,
                "name": "Alger",
                "display_label": "Alger",
                "place_type": Place.PlaceType.AIRPORT,
                "country_code": "DZ",
                "iata_code": "ALG",
                "matching_locality_id": centre.pk,
            },
        )
        orphan = self.airport("DZ", "Unmapped Field", "QZY", parent=alger)
        self.assertEqual(card_place(orphan)["name"], "")
        self.assertIsNone(card_place(orphan)["matching_locality_id"])
        self.assertIsNone(card_place(None))

    def test_france_names_the_commune_never_the_department(self):
        paris = self.region("FR", "Paris", "department")
        rhone = self.region("FR", "Rhône", "department")
        self.assertCity(self.place("FR", "Paris", parent=paris, tier="commune"), "Paris")
        self.assertCity(self.place("FR", "Lyon", parent=rhone, tier="commune"), "Lyon")

    def test_spain_moves_the_postposed_article_to_the_front(self):
        alicante = self.region("ES", "Alicante/Alacant", "province")
        cases = (
            ("Coruña, A", "A Coruña"),
            ("Palmas de Gran Canaria, Las", "Las Palmas de Gran Canaria"),
            ("Alfàs del Pi, l'", "l'Alfàs del Pi"),
            # The municipality's official spelling (the province is
            # "Alicante/Alacant").
            ("Alacant/Alicante", "Alacant/Alicante"),
            # Part by part around the slash of a bilingual name.
            ("Vila Joiosa, la/Villajoyosa", "la Vila Joiosa/Villajoyosa"),
            ("Orxa, l'/Lorcha", "l'Orxa/Lorcha"),
            # A comma that introduces no article is part of the name.
            ("Saus, Camallera i Llampaies", "Saus, Camallera i Llampaies"),
            ("Madrid", "Madrid"),
        )
        for name, expected in cases:
            with self.subTest(name):
                place = self.place("ES", name, parent=alicante, tier="municipality")
                self.assertCity(place, expected)

    def test_germany_drops_the_status_after_the_first_comma(self):
        cases = (
            ("Berlin, Stadt", "Berlin"),
            ("München, Landeshauptstadt", "München"),
            ("Halle (Saale), Stadt", "Halle (Saale)"),
            ("Erkrath, Fundort des Neanderthalers, Stadt", "Erkrath"),
            ("Frankfurt am Main, Stadt", "Frankfurt am Main"),
            # The one catalogue row Destatis writes without the space.
            ("Ebstorf,Klosterflecken", "Ebstorf"),
            ("Kirchheim b.München", "Kirchheim b.München"),
        )
        for name, expected in cases:
            with self.subTest(name):
                district = self.region("DE", name, "district")
                place = self.place("DE", name, parent=district, tier="municipality")
                self.assertCity(place, expected)

    def test_an_airport_reads_as_the_city_it_serves(self):
        alger = self.region("DZ", "Alger", "wilaya")
        centre = self.place("DZ", "Alger Centre", parent=alger, tier="commune")
        alg = self.airport("DZ", "Houari Boumediene Airport", "ALG", served=centre, parent=alger)
        self.assertEqual(city_name(alg), "Alger")

        berlin = self.place("DE", "Berlin, Stadt")
        ber = self.airport("DE", "Berlin Brandenburg Airport", "BER", served=berlin)
        self.assertEqual(city_name(ber), "Berlin")

    def test_an_unmapped_airport_names_nothing(self):
        alger = self.region("DZ", "Alger", "wilaya")
        orphan = self.airport("DZ", "Unmapped Field", "QZX", parent=alger)
        self.assertEqual(city_name(orphan), "")
        self.assertEqual(city_name(None), "")

    def test_a_loaded_place_reads_no_row(self):
        alger = self.region("DZ", "Alger", "wilaya")
        centre = self.place("DZ", "Alger Centre", parent=alger, tier="commune")
        self.airport("DZ", "Houari Boumediene Airport", "ALG", served=centre, parent=alger)
        locality = Place.objects.select_related("parent").get(pk=centre.pk)
        airport = (
            Place.objects.select_related("parent")
            .prefetch_related("airport_mappings__locality__parent")
            .get(iata_code="ALG")
        )
        with self.assertNumQueries(0):
            self.assertEqual(city_name(locality), "Alger")
            self.assertEqual(city_name(airport), "Alger")

    def test_the_catalogue_label_is_unchanged(self):
        alger = self.region("DZ", "Alger", "wilaya")
        centre = self.place("DZ", "Alger Centre", parent=alger, tier="commune")
        self.assertEqual(
            Place.objects.select_related("parent").get(pk=centre.pk).display_label,
            "Alger Centre · Alger",
        )
