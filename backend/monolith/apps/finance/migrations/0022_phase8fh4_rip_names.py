"""Correct dormant postal names, retaining every existing ciphertext and mask."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("finance", "0021_phase8fh3_guards")]
    operations = [
        migrations.RenameField(
            "dzdpayoutprofilerevision", "nip_encrypted", "rip_encrypted"
        ),
        migrations.RenameField(
            "dzdpayoutprofilerevision", "nip_last_four", "rip_last_four"
        ),
    ]
