import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0002_outboundmessage'),
    ]

    operations = [
        migrations.AlterField(
            model_name='outboundmessage',
            name='kind',
            field=models.CharField(choices=[('email_verification', 'Email verification'), ('password_reset', 'Password reset'), ('admin_invitation', 'Admin invitation'), ('kyc_status', 'KYC status'), ('flight_proof_status', 'Flight proof status'), ('payment_required', 'Payment required'), ('payment_processing', 'Payment processing'), ('payment_failed', 'Payment failed'), ('payment_succeeded', 'Payment succeeded'), ('guest_payment', 'Guest payment'), ('refund_status', 'Refund status'), ('recipient_delivery_code', 'Delivery code for the recipient'), ('pickup_confirmed', 'Pickup confirmed'), ('delivery_code_released', 'Delivery code available to the sender'), ('delivery_confirmed', 'Delivery confirmed'), ('protection_ending', 'Protection window ending'), ('protection_ended', 'Protection window ended'), ('dispute_opened', 'Dispute opened'), ('evidence_request', 'Evidence requested'), ('dispute_resolved', 'Dispute resolved'), ('payout_status', 'Payout status'), ('deal_cancelled', 'Deal cancelled'), ('rating_available', 'Rating available'), ('security_event', 'Security/account event')], db_index=True, max_length=32),
        ),
        migrations.CreateModel(
            name='OutboundSecret',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('key', models.CharField(max_length=160, unique=True)),
                ('purpose', models.CharField(choices=[('email_verification', 'Email verification'), ('password_reset', 'Password reset'), ('admin_invitation', 'Admin invitation')], max_length=32)),
                ('sealed_value', models.TextField()),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('consumed_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'notification_outbound_secret',
                'indexes': [models.Index(fields=['purpose', 'expires_at'], name='outbound_secret_exp_idx')],
            },
        ),
    ]
