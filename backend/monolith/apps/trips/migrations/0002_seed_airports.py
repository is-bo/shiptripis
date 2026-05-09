"""Seed Airport rows. Mirror of mobile/lib/shared/mock/airports.dart."""

from django.db import migrations


AIRPORTS = [
    # Algeria
    ("ALG", "Algiers", "Houari Boumediene", "DZ"),
    ("ORN", "Oran", "Ahmed Ben Bella", "DZ"),
    ("CZL", "Constantine", "Mohamed Boudiaf", "DZ"),
    ("AAE", "Annaba", "Rabah Bitat", "DZ"),
    ("TLM", "Tlemcen", "Zenata – Messali El Hadj", "DZ"),
    ("BJA", "Béjaïa", "Soummam – Abane Ramdane", "DZ"),
    ("TMR", "Tamanrasset", "Aguenar – Hadj Bey Akhamok", "DZ"),
    ("HME", "Hassi Messaoud", "Oued Irara – Krim Belkacem", "DZ"),
    # France
    ("CDG", "Paris", "Charles de Gaulle", "FR"),
    ("ORY", "Paris", "Orly", "FR"),
    ("MRS", "Marseille", "Provence", "FR"),
    ("LYS", "Lyon", "Saint-Exupéry", "FR"),
    ("NCE", "Nice", "Côte d'Azur", "FR"),
    ("TLS", "Toulouse", "Blagnac", "FR"),
    ("BOD", "Bordeaux", "Mérignac", "FR"),
    ("NTE", "Nantes", "Atlantique", "FR"),
    ("LIL", "Lille", "Lesquin", "FR"),
    ("SXB", "Strasbourg", "Entzheim", "FR"),
]


def seed(apps, schema_editor):
    Airport = apps.get_model("trips", "Airport")
    Airport.objects.bulk_create(
        [Airport(iata=i, city=c, name=n, country=co) for i, c, n, co in AIRPORTS],
        ignore_conflicts=True,
    )


def unseed(apps, schema_editor):
    Airport = apps.get_model("trips", "Airport")
    Airport.objects.filter(iata__in=[row[0] for row in AIRPORTS]).delete()


class Migration(migrations.Migration):
    dependencies = [("trips", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
